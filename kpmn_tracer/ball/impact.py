"""Automatic impact detection from audio transients and the ball leaving its spot.

Definition: the *impact frame* is the last frame in which the ball still rests
at its start position (contact happens between it and the next frame). The
tracer starts there.

* Audio: every club-like transient at time ``t`` -> frame shown at ``t``.
* Video: the user clicks the ball once (or a preset supplies it). A small
  template of the resting ball is compared with the same spot in every frame
  (normalised cross-correlation, small search radius, ROI follows slow camera
  drift). A present -> absent transition that stays absent is an impact.
  Long clips with sound skip this frame-by-frame scan.
* Ball gone at a sound: around every audio transient four frames show whether
  a resting ball left the hitting zone (anywhere around the clicked ball - the
  tee spot changes during a session). This also gives each shot its own start.
* Fusion: audio and video events within ``match_window_s`` are merged (audio
  frame wins, it is sample-accurate). Audio-only events are dropped when the
  video clearly saw the ball resting there before *and* after (a hit from the
  next bay) and get a very low confidence when the spot was empty. Video-only
  events need a confirmed take-off (ball tracker launch hypothesis rising from
  the spot); otherwise the club at address, a ball rolled into place or a
  camera move would count as impacts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

from kpmn_tracer.ball.audio_onsets import OnsetParams, detect_onsets, read_wav
from kpmn_tracer.io.decode import CancelFn, CancelledError, ProgressFn, extract_audio
from kpmn_tracer.io.reader import FrameReader
from kpmn_tracer.session import ClipSession

log = logging.getLogger(__name__)


@dataclass
class ImpactParams:
    onset: OnsetParams = field(default_factory=OnsetParams)
    ball_radius: float | None = None  # proxy px; None = estimate from the hint frame
    presence_threshold: float = 0.5  # relative ball contrast above = ball present
    min_present_frames: int = 3
    min_absent_s: float = 1.0  # a hit ball leaves the spot empty until the next ball is teed
    match_window_s: float = 0.25
    search_px: int = 3  # template search radius around the expected position
    zone_frac: float = 0.08  # hitting zone around the hint (fraction of the long image side)
    full_scan_max_s: float = 120.0  # longer clips with sound: no frame-by-frame scan (see D43)


@dataclass
class ImpactCandidate:
    frame: int
    time: float  # absolute source time (s)
    confidence: float
    sources: list[str]
    ball_pos: tuple[float, float] | None = None  # source pixel coords

    def to_dict(self) -> dict:
        return {"frame": self.frame, "time": self.time, "confidence": self.confidence,
                "sources": self.sources, "ball_pos": list(self.ball_pos) if self.ball_pos else None}

    @classmethod
    def from_dict(cls, d: dict) -> ImpactCandidate:
        bp = d.get("ball_pos")
        return cls(int(d["frame"]), float(d["time"]), float(d["confidence"]), list(d["sources"]),
                   tuple(bp) if bp else None)


# ---------------------------------------------------------------- ball location
def ball_tophat(img: np.ndarray, k: int) -> np.ndarray:
    """White top-hat; for colour images the maximum over B, G, R.

    A yellow range ball on green turf hardly differs in grey but clearly in red.
    """
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    if img.ndim == 2:
        return cv2.morphologyEx(img, cv2.MORPH_TOPHAT, se)
    return np.max(np.stack([cv2.morphologyEx(np.ascontiguousarray(img[..., c]), cv2.MORPH_TOPHAT, se)
                            for c in range(img.shape[2])]), axis=0)


def locate_ball(img: np.ndarray, hint: tuple[float, float], search_r: float = 40,
                max_r: float = 30) -> tuple[float, float, float] | None:
    """Find a bright compact blob near ``hint`` (grey or BGR image) -> (x, y, radius) or None."""
    h, w = img.shape[:2]
    x0, y0 = int(max(0, hint[0] - search_r - max_r)), int(max(0, hint[1] - search_r - max_r))
    x1, y1 = int(min(w, hint[0] + search_r + max_r + 1)), int(min(h, hint[1] + search_r + max_r + 1))
    roi = img[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    tophat = ball_tophat(roi, int(2 * max_r + 1))
    if tophat.max() < 25:
        return None
    best, best_score = None, -1.0
    # several thresholds: a big, moderately bright ball must not lose against a small,
    # very bright tee or glint just because the threshold is relative to the brightest pixel
    for frac in (0.25, 0.35, 0.45, 0.6):
        _, bw = cv2.threshold(tophat, max(20, int(tophat.max() * frac)), 255, cv2.THRESH_BINARY)
        n, lab, stats, cent = cv2.connectedComponentsWithStats(bw)
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            bw_, bh_ = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            if area < 2 or max(bw_, bh_) > 2.5 * max_r:
                continue
            fill = area / float(bw_ * bh_)
            aspect = min(bw_, bh_) / max(bw_, bh_)
            cx, cy = cent[i][0] + x0, cent[i][1] + y0
            dist = np.hypot(cx - hint[0], cy - hint[1])
            if dist > search_r:
                continue
            bright = float(tophat[lab == i].mean())
            # compact, bright and reasonably large (glints are tiny); close to the click
            score = bright * aspect * fill * np.sqrt(area) / (1.0 + dist / 10.0)
            if score > best_score:
                best, best_score = (cx, cy, max(1.0, np.sqrt(area / np.pi))), score
    return best


# ---------------------------------------------------------------- video presence
def _shift(prev: np.ndarray, cur: np.ndarray) -> np.ndarray:
    """Global translation prev -> cur on a small downsample (phase correlation)."""
    (dx, dy), resp = cv2.phaseCorrelate(prev.astype(np.float32), cur.astype(np.float32))
    return np.array([dx, dy]) if resp > 0.05 else np.zeros(2)


def presence_signal(
    reader: FrameReader, ball_xy: tuple[float, float], ball_r: float, template_frame: int,
    p: ImpactParams, progress: ProgressFn | None = None, cancel: CancelFn | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Per frame: (presence score, ROI centre (n,2) in proxy px).

    Score = min(ball contrast relative to the template frame, template similarity / 0.8):
    the contrast separates tiny balls from their background, the similarity separates
    big, close balls from bright textured grass behind them (contrast alone stays high).
    """
    r = max(1, int(np.ceil(ball_r * 0.7))) + 2  # the ball itself (+2 px), not its neighbourhood
    k = int(2 * np.ceil(ball_r * 2.5) + 1)  # top-hat kernel: larger than the ball
    pad = k
    g0 = reader.read(template_frame)
    cx, cy = ball_xy

    def plane(img: np.ndarray, c: int) -> np.ndarray:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if c == 3 else np.ascontiguousarray(img[..., c])

    def measure(g: np.ndarray, x: float, y: float, c: int) -> float | None:
        xi, yi = int(round(x)), int(round(y))
        win = g[yi - r - pad:yi + r + pad + 1, xi - r - pad:xi + r + pad + 1]
        if win.shape[:2] != (2 * (r + pad) + 1, 2 * (r + pad) + 1):
            return None
        th = ball_tophat(plane(win, c), k)
        return float(th[pad:-pad, pad:-pad].max())

    def separation(c: int) -> float:
        """Ball peak vs. the strongest structure around it, in plane ``c`` of the template frame."""
        xi, yi = int(round(cx)), int(round(cy))
        R = r + 3 * pad
        win = g0[max(0, yi - R):yi + R + 1, max(0, xi - R):xi + R + 1]
        th = ball_tophat(plane(win, c), k).astype(np.float32)
        oy, ox = yi - max(0, yi - R), xi - max(0, xi - R)
        yy, xx = np.ogrid[:th.shape[0], :th.shape[1]]
        inner = (yy - oy) ** 2 + (xx - ox) ** 2 <= (r + 1) ** 2
        around = th[~inner]
        return float(th[inner].max()) / (float(np.percentile(around, 99)) + 5.0) if around.size else 0.0

    # the colour plane in which this ball stands out most (white ball: grey/blue, yellow on green: red)
    chan = max(range(4), key=separation)
    log.debug("presence: using plane %s", "BGR"[chan] if chan < 3 else "grey")

    ref = measure(g0, cx, cy, chan)
    if ref is None:
        raise ValueError("ball too close to the image border")
    tr = int(np.ceil(2.2 * ball_r))
    tpl = g0[int(cy) - tr:int(cy) + tr + 1, int(cx) - tr:int(cx) + tr + 1].copy()
    s_px = p.search_px

    def similarity(g: np.ndarray, x: float, y: float) -> float:
        xi, yi = int(round(x)), int(round(y))
        win = g[yi - tr - s_px:yi + tr + s_px + 1, xi - tr - s_px:xi + tr + s_px + 1]
        if tpl.shape[:2] != (2 * tr + 1, 2 * tr + 1) or win.shape[:2] != (2 * (tr + s_px) + 1,) * 2:
            return 1.0  # near the border: rely on the contrast alone
        return float(cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED).max())

    ref = max(ref, 10.0)
    n = len(reader)
    scale = 320.0 / max(reader.width, reader.height)
    small = lambda g: cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)  # noqa: E731
    centres = np.zeros((n, 2))
    score = np.zeros(n)
    # ROI follows slow camera drift: accumulate translation outward from the template frame
    order = list(range(template_frame, n)) + list(range(template_frame - 1, -1, -1))
    pos = {template_frame: np.array([cx, cy])}
    prev_small: dict[int, np.ndarray] = {}
    for i, f in enumerate(order):
        if cancel is not None and cancel():
            raise CancelledError("impact detection cancelled")
        g = reader.read(f)
        sm = small(cv2.cvtColor(g, cv2.COLOR_BGR2GRAY))
        if f != template_frame:
            nb = f - 1 if f > template_frame else f + 1
            pos[f] = pos[nb] + _shift(prev_small[nb], sm) / scale
        prev_small[f] = sm
        old = f - 2 if f > template_frame else f + 2
        if old != template_frame:  # the backward pass starts again from the template frame
            prev_small.pop(old, None)
        v = measure(g, *pos[f], chan)
        score[f] = 0.0 if v is None else min(1.5, v / ref, similarity(g, *pos[f]) / 0.8)
        centres[f] = pos[f]
        if progress is not None and i % 10 == 0:
            progress(i / n)
    return score, centres


def video_impacts(ncc: np.ndarray, fps: float, p: ImpactParams) -> list[int]:
    """Last present frame of every present -> lasting-absent transition."""
    present = ncc >= p.presence_threshold
    min_abs = max(2, int(round(p.min_absent_s * fps)))
    out = []
    run = 0
    n = len(present)
    for f in range(n - 1):
        run = run + 1 if present[f] else 0
        if present[f] and not present[f + 1] and run >= p.min_present_frames:
            after = present[f + 1:f + 1 + min_abs]
            if after.size >= min(min_abs, n - f - 1) and not after.any():
                out.append(f)
    return out


# ---------------------------------------------------------------- ball gone at a sound
VANISH_BEFORE_S = (-0.3, -0.1)  # top of the backswing / downswing: the ball still rests
VANISH_AFTER_S = (0.2, 0.3)  # follow-through: the club is high, the spot is empty


def vanished_ball(
    read, frame: int, n: int, zone_xy: tuple[float, float], zone_r: float, fps: float,
    ball_r: float | None = None,
) -> tuple[float, float, float] | None:
    """Did a resting ball disappear from the hitting zone around ``frame``? -> (x, y, r).

    Four frames suffice: two before the sound, two after. A hit ball leaves a spot
    that is unchanged within each pair but differs between them (golfer and club
    move within the pairs), was a bright compact blob before (top-hat) and is not
    any more. This works wherever in the zone the ball was teed - a session rarely
    uses one exact spot - and needs no scan of the whole clip. With the clicked
    ball's size most shoe tips and fingers leaving the spot are rejected (colour
    is no help: it drifts with the light over a session).
    """
    fs = [frame + int(round(t * fps)) for t in (*VANISH_BEFORE_S, *VANISH_AFTER_S)]
    if fs[0] < 0 or fs[-1] >= n:
        return None
    img0 = read(fs[0])
    h, w = img0.shape[:2]
    x0, y0 = int(max(0, zone_xy[0] - zone_r)), int(max(0, zone_xy[1] - zone_r))
    x1, y1 = int(min(w, zone_xy[0] + zone_r)), int(min(h, zone_xy[1] + zone_r))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None

    def crop(img: np.ndarray) -> np.ndarray:
        return cv2.GaussianBlur(img[y0:y1, x0:x1], (3, 3), 0).astype(np.int16)

    b1, b2, a1, a2 = crop(img0), *(crop(read(f)) for f in fs[1:])

    def d(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return np.abs(a - b).max(axis=2) if a.ndim == 3 else np.abs(a - b)

    change = np.minimum.reduce([d(b1, a1), d(b2, a2), d(b1, a2), d(b2, a1)])
    unstable = np.maximum(d(b1, b2), d(a1, a2))
    mask = ((change >= 25) & (unstable < 0.5 * change)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, lab, stats, cent = cv2.connectedComponentsWithStats(mask)
    r_lo, r_hi = (0.75 * ball_r, 1.6 * ball_r) if ball_r else (0.002 * max(h, w), 0.03 * max(h, w))
    best, best_score = None, 0.0
    for i in range(1, count):
        area = stats[i, cv2.CC_STAT_AREA]
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        r = float(np.sqrt(area / np.pi))
        if not r_lo <= r <= r_hi or min(bw, bh) < 0.5 * max(bw, bh) or area < 0.5 * bw * bh:
            continue
        cx, cy = cent[i][0] + x0, cent[i][1] + y0
        # it must have been a ball: a bright blob before, gone after (a club head or a hand
        # entering or leaving the spot is no bright compact blob)
        before = min(_blob_peak(c, cx - x0, cy - y0, r) for c in (b1, b2))
        after = max(_blob_peak(c, cx - x0, cy - y0, r) for c in (a1, a2))
        if before < 25 or after > 0.7 * before:
            continue
        score = before * area / (1.0 + np.hypot(cx - zone_xy[0], cy - zone_xy[1]) / zone_r)
        if score > best_score:
            best, best_score = (float(cx), float(cy), r), score
    return best


def _blob_peak(img: np.ndarray, x: float, y: float, r: float) -> float:
    """Top-hat peak of a ball-sized blob at (x, y) of a crop."""
    k = int(2 * np.ceil(2.5 * r) + 1)
    pad = k
    xi, yi = int(round(x)), int(round(y))
    win = img[max(0, yi - pad):yi + pad + 1, max(0, xi - pad):xi + pad + 1]
    if win.size == 0:
        return 0.0
    th = ball_tophat(np.clip(win, 0, 255).astype(np.uint8), k)
    oy, ox = yi - max(0, yi - pad), xi - max(0, xi - pad)
    q = int(np.ceil(0.7 * r)) + 1
    return float(th[max(0, oy - q):oy + q + 1, max(0, ox - q):ox + q + 1].max())


def vanished_at_sounds(
    path, frames: list[int], n: int, zone_xy: tuple[float, float], zone_r: float, fps: float,
    ball_r: float | None, progress: ProgressFn | None = None, cancel: CancelFn | None = None,
) -> dict[int, tuple[float, float, float]]:
    """:func:`vanished_ball` for every sound frame, with several readers in threads."""
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor

    local = threading.local()
    readers: list[FrameReader] = []
    lock = threading.Lock()
    done = [0]

    def one(f: int) -> tuple[int, tuple[float, float, float] | None]:
        if cancel is not None and cancel():
            raise CancelledError("impact detection cancelled")
        rd = getattr(local, "reader", None)
        if rd is None:
            rd = local.reader = FrameReader(path, cache_size=4)
            with lock:
                readers.append(rd)
        res = vanished_ball(rd.read, f, n, zone_xy, zone_r, fps, ball_r)
        with lock:
            done[0] += 1
            if progress is not None:
                progress(done[0] / max(1, len(frames)))
        return f, res

    try:
        with ThreadPoolExecutor(max(1, min(6, (os.cpu_count() or 2) - 2))) as ex:
            out = dict(ex.map(one, frames))
    finally:
        for rd in readers:
            rd.close()
    return {f: v for f, v in out.items() if v is not None}


# ---------------------------------------------------------------- launch check
def launch_seen(reader: FrameReader, frame: int, ball_xy: tuple[float, float], ball_r: float,
                fps: float) -> int | None:
    """Does a ball really fly away from ``ball_xy`` around ``frame``? Returns the impact frame.

    The camera over the next 1.5 s is tracked with the phase-2 tracker (robust to
    the moving golfer; tripods are detected and skipped), then the ball tracker
    runs from ``frame - 1`` and ``frame``. A club head, a body part or a ball
    rolled into place may form a short launch hypothesis, but only a real ball
    yields a long, smooth, rising flight: >= 8 detections over >= 0.4 s and a
    clear rise. Large camera motion (or a cut) is never confirmed.
    """
    from kpmn_tracer.ball.candidates import ClassicDetector
    from kpmn_tracer.ball.tracker import BallTracker, BallTrackParams
    from kpmn_tracer.camera.homography import corner_displacement
    from kpmn_tracer.camera.tracker import CameraTracker

    n = len(reader)
    size = (reader.width, reader.height)
    # a ball must rest stably at the spot before the impact (the club head may
    # already touch it in the last frames): found in >= 60 % of the last 0.5 s,
    # always at the same place
    look = range(frame - 1, max(-1, frame - 1 - int(0.5 * fps)), -1)
    found = []
    for f in look:
        loc = locate_ball(reader.read(f), ball_xy, search_r=max(12.0, 4 * ball_r))
        if loc is not None and loc[2] >= 1.0:
            found.append(loc)
    if len(found) < 0.6 * len(look):
        return None
    arr = np.array(found)
    med = np.median(arr, axis=0)
    if np.median(np.hypot(arr[:, 0] - med[0], arr[:, 1] - med[1])) > max(1.5, 0.25 * med[2]):
        return None
    ball_xy, ball_r = (float(med[0]), float(med[1])), float(med[2])
    first, end = max(0, frame - 1), min(n - 1, frame + int(1.5 * fps))
    cam = CameraTracker(reader.gray, size).track(frame, first, end)
    if cam.mode == "tracked":
        moved = max(corner_displacement(cam.H(f), *size) for f in range(first, end + 1))
        if moved > 0.08 * max(size) or np.mean(cam.confidence < 0.5) > 0.2:
            return None

    def H(f: int) -> np.ndarray:
        return cam.H(min(max(f, first), end))

    det = ClassicDetector(reader.gray, H, size, end + 1)
    for f0 in (frame - 1, frame):
        if f0 < first:
            continue
        params = BallTrackParams(max_flight_s=1.5, max_gap_s=0.3)
        tr = BallTracker(det, size, fps, end + 1, params).track(f0, ball_xy, ball_r)
        if tr is None or len(tr.points) < 8 or tr.fit is None or tr.fit.rms > 1.5:
            continue
        span = (max(tr.points) - f0) / fps
        rise = ball_xy[1] - min(c.y for c in tr.points.values())
        if span >= 0.4 and rise > max(6 * ball_r, 0.02 * reader.height):
            return f0
    return None


# ---------------------------------------------------------------- fusion
def detect_impacts(
    session: ClipSession,
    ball_hint: tuple[float, float] | None = None,
    hint_frame: int | None = None,
    params: ImpactParams | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> list[ImpactCandidate]:
    """Find all impacts in the clip. ``ball_hint``: resting ball in source px at ``hint_frame``."""
    p = params or ImpactParams()
    proj = session.project
    fps = proj.fps
    times = session.frame_times()
    report = progress or (lambda _f: None)

    # --- audio
    audio: list[tuple[int, float, float]] = []  # (frame, time, strength)
    if proj.video.has_audio:
        wav = extract_audio(proj.video, session.cache_dir / "audio.wav")
        if wav is not None:
            x, sr = read_wav(wav)
            for o in detect_onsets(x, sr, p.onset):
                t = o.time + proj.video.audio_start_time
                audio.append((session.time_to_frame(t), t, o.strength))
    report(0.1)

    # --- video
    vid: list[int] = []
    launched: dict[int, int] = {}  # video impact -> impact frame confirmed by a take-off
    vanished: dict[int, tuple[float, float, float]] = {}  # sound frame -> ball (proxy px) that left
    ncc = None
    ball_src = None
    n = len(session.reader)
    if ball_hint is not None:
        hf = hint_frame if hint_frame is not None else 0
        hint_proxy = session.source_to_proxy(np.array([ball_hint]))[0]
        with FrameReader(session.reader.path, cache_size=4) as reader:
            g = reader.read(hf)
            zone_r = p.zone_frac * max(g.shape[:2])
            loc = locate_ball(g, (float(hint_proxy[0]), float(hint_proxy[1])),
                              search_r=max(12.0, 0.02 * max(g.shape)))
            br = p.ball_radius or (loc[2] if loc is not None else None)
            zone = (float(hint_proxy[0]), float(hint_proxy[1])) if loc is None else (loc[0], loc[1])
            # every sound: did a ball leave the hitting zone? (a few frames per sound)
            if audio:
                vanished = vanished_at_sounds(reader.path, [fa for fa, _t, _s in audio], n, zone, zone_r, fps,
                                              br, lambda f: report(0.1 + 0.2 * f), cancel)
            full_scan = not audio or n <= p.full_scan_max_s * fps
            if loc is None:
                log.warning("No ball found near the hint - frame-by-frame video detection skipped")
            elif full_scan:
                # short clips (or no sound): also scan every frame at the clicked spot, which
                # finds silent shots and recognises hits from the next bay with our ball resting
                bx, by, br = loc
                br = p.ball_radius or br
                ball_src = tuple(session.proxy_to_source(np.array([[bx, by]]))[0])
                ncc, centres = presence_signal(reader, (bx, by), br, hf, p,
                                               lambda f: report(0.3 + 0.6 * f), cancel)
                vid = video_impacts(ncc, fps, p)
                for v in vid:
                    f0 = launch_seen(reader, v, tuple(centres[v]), br, fps)
                    if f0 is not None:
                        launched[v] = f0
            else:
                log.info("Long clip (%.0f s): impacts from sounds only, no frame-by-frame scan", n / fps)
    report(0.95)

    # --- fusion
    win = max(1, int(round(p.match_window_s * fps)))
    out: list[ImpactCandidate] = []
    used_video: set[int] = set()
    # one-to-one: every video event pairs with its closest audio event only
    pair: dict[int, int] = {}  # audio index -> video frame
    for v in vid:
        close = [(abs(v - fa), i) for i, (fa, _t, _s) in enumerate(audio) if abs(v - fa) <= win]
        if close:
            d, i = min(close)
            if i not in pair or abs(pair[i] - audio[i][0]) > d:
                pair[i] = v

    def src_of(ball: tuple[float, float, float]) -> tuple[float, float]:
        return tuple(session.proxy_to_source(np.array([[ball[0], ball[1]]]))[0])

    for i, (fa, t, strength) in enumerate(audio):
        if i in pair:
            v = pair[i]
            used_video.add(v)
            # audio is sample accurate; trust video only if they disagree by > 2 frames
            frame = fa if abs(v - fa) <= 2 else v
            src = ["audio", "video"] + (["launch"] if v in launched else [])
            pos = src_of(vanished[fa]) if fa in vanished else ball_src
            out.append(ImpactCandidate(frame, float(times[frame]), min(1.0, 0.6 + 0.4 * strength), src, pos))
        elif fa in vanished:
            # a ball left the hitting zone at the sound (wherever it was teed)
            out.append(ImpactCandidate(fa, t, min(1.0, 0.6 + 0.4 * strength), ["audio", "video"],
                                       src_of(vanished[fa])))
        elif ncc is not None and _ball_stays(ncc, fa, win, p):
            log.info("Audio transient at %.2fs ignored: ball did not move", t)
        elif ncc is not None and not _spot_empty(ncc, fa, win, p):
            out.append(ImpactCandidate(fa, t, 0.25 + 0.35 * strength, ["audio"], ball_src))
        elif ball_hint is not None:
            # no ball left the zone: maybe another bay
            out.append(ImpactCandidate(fa, t, 0.15, ["audio"], None))
        else:
            out.append(ImpactCandidate(fa, t, 0.25 + 0.35 * strength, ["audio"], None))
    for v in vid:
        if v not in used_video:
            # without sound only a visible take-off makes a reliable impact
            if v in launched:
                f0 = launched[v]
                out.append(ImpactCandidate(f0, float(times[f0]), 0.55, ["video", "launch"], ball_src))
            else:
                out.append(ImpactCandidate(v, float(times[v]), 0.2, ["video"], ball_src))
    out.sort(key=lambda c: c.frame)
    report(1.0)
    log.info("Impacts: %s", [(c.frame, "+".join(c.sources)) for c in out])
    return out


def _spot_empty(ncc: np.ndarray, frame: int, win: int, p: ImpactParams) -> bool:
    a, b = max(0, frame - 2 * win), min(len(ncc), frame + 2 * win + 1)
    seg = ncc[a:b]
    return seg.size > 0 and bool(np.mean(seg >= p.presence_threshold) < 0.1)


def _ball_stays(ncc: np.ndarray, frame: int, win: int, p: ImpactParams) -> bool:
    """The ball rested at its spot before the sound and still does right after -> not our impact."""
    after = ncc[frame + 1:frame + 1 + max(3, win // 2)]
    before = ncc[max(0, frame - win):frame + 1]
    return (after.size > 0 and bool(np.mean(after >= p.presence_threshold) > 0.8)
            and bool(np.mean(before >= p.presence_threshold) > 0.5))
