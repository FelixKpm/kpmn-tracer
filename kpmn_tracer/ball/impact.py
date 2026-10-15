"""Automatic impact detection from audio transients and the ball leaving its spot.

Definition: the *impact frame* is the last frame in which the ball still rests
at its start position (contact happens between it and the next frame). The
tracer starts there.

* Audio: every club-like transient at time ``t`` -> frame shown at ``t``.
* Video: the user clicks the ball once (or a preset supplies it). A small
  template of the resting ball is compared with the same spot in every frame
  (normalised cross-correlation, small search radius, ROI follows slow camera
  drift). A present -> absent transition that stays absent is an impact.
* Fusion: audio and video events within ``match_window_s`` are merged (audio
  frame wins, it is sample-accurate). Audio-only events are dropped when the
  video clearly saw the ball resting there before *and* after (a hit from the
  next bay) and get a very low confidence when the spot was empty; video-only
  events are kept with lower confidence.
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
    min_absent_s: float = 0.25
    match_window_s: float = 0.25
    search_px: int = 3  # template search radius around the expected position


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
def locate_ball(gray: np.ndarray, hint: tuple[float, float], search_r: float = 40,
                max_r: float = 30) -> tuple[float, float, float] | None:
    """Find a small bright compact blob near ``hint`` -> (x, y, radius) or None."""
    h, w = gray.shape
    x0, y0 = int(max(0, hint[0] - search_r - max_r)), int(max(0, hint[1] - search_r - max_r))
    x1, y1 = int(min(w, hint[0] + search_r + max_r + 1)), int(min(h, hint[1] + search_r + max_r + 1))
    roi = gray[y0:y1, x0:x1]
    if roi.size == 0:
        return None
    k = int(2 * max_r + 1)
    tophat = cv2.morphologyEx(roi, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    if tophat.max() < 25:
        return None
    _, bw = cv2.threshold(tophat, max(20, int(tophat.max() * 0.45)), 255, cv2.THRESH_BINARY)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(bw)
    best, best_score = None, -1.0
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
        score = bright * aspect * fill / (1.0 + dist / 10.0)
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
    """Per frame: (ball contrast relative to the template frame, ROI centre (n,2) in proxy px)."""
    r = max(2, int(np.ceil(ball_r * 1.5))) + p.search_px
    k = int(2 * np.ceil(ball_r * 2.5) + 1)  # top-hat kernel: larger than the ball
    pad = k
    g0 = reader.gray(template_frame)
    cx, cy = ball_xy

    def measure(g: np.ndarray, x: float, y: float) -> float | None:
        xi, yi = int(round(x)), int(round(y))
        win = g[yi - r - pad:yi + r + pad + 1, xi - r - pad:xi + r + pad + 1]
        if win.shape != (2 * (r + pad) + 1, 2 * (r + pad) + 1):
            return None
        th = cv2.morphologyEx(win, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        return float(th[pad:-pad, pad:-pad].max())

    ref = measure(g0, cx, cy)
    if ref is None:
        raise ValueError("ball too close to the image border")
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
        g = reader.gray(f)
        sm = small(g)
        if f != template_frame:
            nb = f - 1 if f > template_frame else f + 1
            pos[f] = pos[nb] + _shift(prev_small[nb], sm) / scale
        prev_small[f] = sm
        prev_small.pop(f - 2 if f > template_frame else f + 2, None)
        v = measure(g, *pos[f])
        score[f] = 0.0 if v is None else min(1.5, v / ref)
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
    ncc = None
    ball_src = None
    if ball_hint is not None:
        hf = hint_frame if hint_frame is not None else 0
        hint_proxy = session.source_to_proxy(np.array([ball_hint]))[0]
        with FrameReader(session.reader.path, cache_size=4) as reader:
            g = reader.gray(hf)
            loc = locate_ball(g, (float(hint_proxy[0]), float(hint_proxy[1])),
                              search_r=max(12.0, 0.02 * max(g.shape)))
            if loc is None:
                log.warning("No ball found near the hint - video detection skipped")
            else:
                bx, by, br = loc
                br = p.ball_radius or br
                ball_src = tuple(session.proxy_to_source(np.array([[bx, by]]))[0])
                ncc, _ = presence_signal(reader, (bx, by), br, hf, p,
                                         lambda f: report(0.1 + 0.85 * f), cancel)
                vid = video_impacts(ncc, fps, p)
    report(0.95)

    # --- fusion
    win = max(1, int(round(p.match_window_s * fps)))
    out: list[ImpactCandidate] = []
    used_video: set[int] = set()
    for fa, t, strength in audio:
        match = [v for v in vid if abs(v - fa) <= win]
        if match:
            v = min(match, key=lambda v: abs(v - fa))
            used_video.add(v)
            # audio is sample accurate; trust video only if they disagree by > 2 frames
            frame = fa if abs(v - fa) <= 2 else v
            out.append(ImpactCandidate(frame, float(times[frame]), min(1.0, 0.6 + 0.4 * strength),
                                       ["audio", "video"], ball_src))
        elif ncc is not None and _ball_stays(ncc, fa, win, p):
            log.info("Audio transient at %.2fs ignored: ball did not move", t)
        elif ncc is not None and _spot_empty(ncc, fa, win, p):
            # no ball at the usual spot: maybe another bay, maybe a different tee spot
            out.append(ImpactCandidate(fa, t, 0.15, ["audio"], None))
        else:
            out.append(ImpactCandidate(fa, t, 0.25 + 0.35 * strength, ["audio"], ball_src))
    for v in vid:
        if v not in used_video:
            out.append(ImpactCandidate(v, float(times[v]), 0.55, ["video"], ball_src))
    out.sort(key=lambda c: c.frame)
    report(1.0)
    log.info("Impacts: %s", [(c.frame, "+".join(c.sources)) for c in out])
    return out


def _spot_empty(ncc: np.ndarray, frame: int, win: int, p: ImpactParams) -> bool:
    a, b = max(0, frame - 2 * win), min(len(ncc), frame + 2 * win + 1)
    seg = ncc[a:b]
    return seg.size > 0 and bool(np.mean(seg >= p.presence_threshold) < 0.1)


def _ball_stays(ncc: np.ndarray, frame: int, win: int, p: ImpactParams) -> bool:
    a, b = max(0, frame - 2 * win), min(len(ncc), frame + 2 * win + 1)
    seg = ncc[a:b]
    return seg.size > 0 and bool(np.mean(seg >= p.presence_threshold) > 0.8)
