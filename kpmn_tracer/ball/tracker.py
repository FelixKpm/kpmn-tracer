"""Physics-guided association of ball candidates into one flight.

1. **Init**: candidates of the first frames after impact inside a cone above
   the start point; RANSAC on the perspective flight model through the start
   yields up to six distinct launch hypotheses (support counted in *frames*,
   so a club head producing a bright and a dark blob per frame is not favoured).
   Each hypothesis is followed; the longest, densest, smoothest track wins.
2. **Follow**: predict the next position from the current fit (perspective
   model once enough points exist), search a gate around it; the gate grows
   with every missed frame. Misses are bridged by prediction instead of
   stopping, up to ``max_gap_s``.
3. **Global fit + re-search**: robust fit on all detections, outliers removed,
   then frames without a detection are searched again in a tight window
   around the fitted curve (recovers faint detections).

Everything is in reference-frame proxy pixels and frames since impact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

from kpmn_tracer.ball.candidates import BallDetector, Candidate
from kpmn_tracer.ball.flightfit import FitResult, FlightModel, fit_linear, ransac_fit
from kpmn_tracer.io.decode import CancelFn, CancelledError, ProgressFn

log = logging.getLogger(__name__)


@dataclass
class BallTrackParams:
    init_frames_s: float = 0.35
    init_min_frames: int = 6
    init_radius_frac: float = 0.45  # of the image diagonal
    gate_base: float = 5.0
    gate_per_miss: float = 3.0
    gate_speed_frac: float = 0.25
    max_gap_s: float = 0.7
    max_flight_s: float = 9.0
    fit_tol: float = 2.5
    research_tol: float = 3.0


@dataclass
class BallTrack:
    impact: int
    start: tuple[float, float]
    points: dict[int, Candidate] = field(default_factory=dict)  # frame -> accepted detection
    fit: FitResult | None = None
    last_frame: int = 0  # last frame the follower looked at

    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        fs = sorted(self.points)
        t = np.array([f - self.impact for f in fs], float)
        xy = np.array([[self.points[f].x, self.points[f].y] for f in fs], float).reshape(-1, 2)
        return t, xy


class BallTracker:
    def __init__(self, detector: BallDetector, size: tuple[int, int], fps: float, frame_count: int,
                 params: BallTrackParams | None = None) -> None:
        self.det = detector
        self.w, self.h = size
        self.fps = fps
        self.n = frame_count
        self.p = params or BallTrackParams()

    # ------------------------------------------------------------ helpers
    def _gap(self, speed: float, r: float) -> int:
        """Neighbour distance for the difference images: ball must have moved > ~2 radii."""
        return int(np.clip(np.ceil(3.0 * max(r, 1.0) / max(speed, 0.3)), 1, 6))

    def _roi(self, c: np.ndarray, rad: float) -> tuple[int, int, int, int]:
        return (int(c[0] - rad), int(c[1] - rad), int(c[0] + rad + 1), int(c[1] + rad + 1))

    # ------------------------------------------------------------ init
    def _init_candidates(self, impact: int, start: tuple[float, float], ball_r: float) -> list[Candidate]:
        n_init = max(self.p.init_min_frames, int(round(self.p.init_frames_s * self.fps)))
        diag = float(np.hypot(self.w, self.h))
        R = self.p.init_radius_frac * diag
        roi = (int(start[0] - R), int(start[1] - R), int(start[0] + R), int(start[1] + 0.15 * R))
        cands: list[Candidate] = []
        for f in range(impact + 1, min(self.n, impact + 1 + n_init)):
            dt = f - impact
            for c in self.det.detect(f, roi, ball_r, gap=1 if dt <= 2 else 2):
                d = np.hypot(c.x - start[0], c.y - start[1])
                # must have left the start point, move upwards / sideways, and not too far per frame
                if d < 1.5 * ball_r or c.y > start[1] + 2 * ball_r or d > R * dt / 2 + 10:
                    continue
                cands.append(c)
        return cands

    def _assign(self, model: FlightModel, cands: list[Candidate], impact: int) -> dict[int, Candidate]:
        """Per frame the candidate closest to the model (within tolerance)."""
        out: dict[int, Candidate] = {}
        best_d: dict[int, float] = {}
        for c in cands:
            d = float(np.hypot(*(model(c.frame - impact)[0] - (c.x, c.y))))
            if d < self.p.fit_tol and d < best_d.get(c.frame, np.inf):
                out[c.frame], best_d[c.frame] = c, d
        return out

    def _hypotheses(self, impact: int, start: tuple[float, float], ball_r: float,
                    max_hyp: int = 6, iters: int = 3000) -> list[BallTrack]:
        """Distinct launch hypotheses, ranked by the number of supporting *frames*.

        Several moving things leave the ball spot at impact (ball, club head, divot);
        all plausible ones are kept and the follower decides.
        """
        cands = self._init_candidates(impact, start, ball_r)
        frames = sorted({c.frame for c in cands})
        if len(frames) < 3:
            return []
        rng = np.random.default_rng(0)
        by_frame = {f: [c for c in cands if c.frame == f] for f in frames}
        expected_area = np.pi * max(ball_r, 1.0) ** 2

        def weight(c: Candidate) -> float:
            # contrast, and similarity to the resting ball's size (club heads/limbs differ)
            size_sim = float(np.exp(-abs(np.log(max(c.area, 1.0) / expected_area)) / 1.5))
            return min(c.score, 10.0) ** 1.5 * size_sim

        cw = {id(c): weight(c) for c in cands}
        w = np.array([sum(cw[id(c)] for c in by_frame[f]) for f in frames])
        prob = w / w.sum()
        found: list[tuple[int, float, dict[int, Candidate]]] = []
        seen: set[frozenset] = set()
        for _ in range(iters):
            fs = rng.choice(len(frames), 3, replace=False, p=prob)
            pick = []
            for i in fs:
                cs = by_frame[frames[i]]
                pw = np.array([cw[id(c)] for c in cs])
                pick.append(cs[rng.choice(len(cs), p=pw / pw.sum())])
            t = np.array([c.frame - impact for c in pick], float)
            xy = np.array([[c.x, c.y] for c in pick])
            m = fit_linear(t, xy, start, perspective=True)
            if m is None or m.c < -0.9 / max(t.max() * 3, 1):
                continue
            sup = self._assign(m, cands, impact)
            if len(sup) < 3:
                continue
            key = frozenset(id(c) for c in sup.values())
            if key in seen:
                continue
            seen.add(key)
            err = sum(float(np.hypot(*(m(f - impact)[0] - (c.x, c.y)))) for f, c in sup.items())
            found.append((len(sup), err, sup))
        found.sort(key=lambda h: (-h[0], h[1]))
        out: list[BallTrack] = []
        for _n, _e, sup in found:
            ids = {id(c) for c in sup.values()}
            if any(len(ids & {id(c) for c in h.points.values()}) > 0.5 * len(ids) for h in out):
                continue  # essentially the same hypothesis
            tr = BallTrack(impact, start, dict(sup))
            tr.fit = ransac_fit(*tr.arrays(), start, tol=self.p.fit_tol, perspective=True)
            if tr.fit is None:
                continue
            out.append(tr)
            if len(out) >= max_hyp:
                break
        return out

    # ------------------------------------------------------------ follow
    def _predict_model(self, track: BallTrack) -> FlightModel | None:
        t, xy = track.arrays()
        if len(t) >= 6:
            recent = t >= t.max() - 1.2 * self.fps  # local fit adapts to drag/lift
            w = np.where(recent, 1.0, 0.3)
            m = fit_linear(t, xy, track.start, perspective=True, w=w)
            if m is not None and m.c > -0.9 / max(t.max() + 30, 1):
                return m
        return fit_linear(t, xy, track.start, perspective=False)

    def _follow(self, track: BallTrack, ball_r: float, progress: ProgressFn | None,
                cancel: CancelFn | None) -> None:
        max_gap = int(round(self.p.max_gap_s * self.fps))
        end = min(self.n - 1, track.impact + int(self.p.max_flight_s * self.fps))
        f = max(track.points) + 1
        misses = 0
        model = self._predict_model(track)
        while f <= end and model is not None:
            if cancel is not None and cancel():
                raise CancelledError("ball tracking cancelled")
            t = f - track.impact
            pred = model(t)[0]
            vel = model(t)[0] - model(t - 1)[0]
            speed = float(np.hypot(*vel))
            if not (-50 < pred[0] < self.w + 50 and -50 < pred[1] < self.h + 50):
                break
            gate = self.p.gate_base + self.p.gate_per_miss * misses + self.p.gate_speed_frac * speed
            r_exp = max(1.0, ball_r * (1.0 / (1.0 + max(model.c, 0) * t)))
            cands = self.det.detect(f, self._roi(pred, gate + 3), r_exp, self._gap(speed, r_exp))
            best, best_d = None, gate
            for c in cands:
                d = np.hypot(c.x - pred[0], c.y - pred[1]) / (0.6 + 0.4 * min(c.score, 3.0) / 3.0)
                if d < best_d:
                    best, best_d = c, d
            if best is not None:
                track.points[f] = best
                misses = 0
                model = self._predict_model(track)
            else:
                misses += 1
                if misses > max_gap:
                    break
            track.last_frame = f
            if progress is not None and f % 5 == 0:
                progress(min(0.99, (f - track.impact) / max(1, end - track.impact)))
            f += 1

    # ------------------------------------------------------------ global fit
    def _finalise(self, track: BallTrack, ball_r: float) -> None:
        t, xy = track.arrays()
        fit = ransac_fit(t, xy, track.start, tol=self.p.fit_tol, perspective=True)
        if fit is None:
            fit = ransac_fit(t, xy, track.start, tol=self.p.fit_tol, perspective=False)
        if fit is None:
            return
        fs = sorted(track.points)
        for f, ok in zip(fs, fit.inliers):
            if not ok:
                del track.points[f]
        # re-search frames without detection along the fitted curve
        first, last = track.impact + 1, max(track.points) if track.points else track.impact
        added = 0
        for f in range(first, last + 1):
            if f in track.points:
                continue
            tt = f - track.impact
            pred = fit.model(tt)[0]
            speed = float(np.hypot(*(fit.model(tt)[0] - fit.model(tt - 1)[0])))
            r_exp = max(1.0, ball_r / (1.0 + max(fit.model.c, 0) * tt))
            cands = self.det.detect(f, self._roi(pred, self.p.research_tol + 4), r_exp, self._gap(speed, r_exp))
            near = [c for c in cands if np.hypot(c.x - pred[0], c.y - pred[1]) < self.p.research_tol]
            if near:
                track.points[f] = min(near, key=lambda c: np.hypot(c.x - pred[0], c.y - pred[1]))
                added += 1
        if added:
            t, xy = track.arrays()
            fit2 = ransac_fit(t, xy, track.start, tol=self.p.fit_tol, perspective=True)
            fit = fit2 or fit
        track.fit = fit

    # ------------------------------------------------------------ public
    def track(self, impact: int, start: tuple[float, float], ball_r: float = 2.0,
              progress: ProgressFn | None = None, cancel: CancelFn | None = None) -> BallTrack | None:
        hyps = self._hypotheses(impact, start, ball_r)
        if not hyps:
            log.info("Ball tracking: no consistent launch found")
            return None
        best: BallTrack | None = None
        best_score = -np.inf
        for i, tr in enumerate(hyps):
            sub = (lambda f, i=i: progress((i + f) / len(hyps))) if progress else None
            self._follow(tr, ball_r, sub, cancel)
            self._finalise(tr, ball_r)
            if not tr.points or tr.fit is None:
                continue
            span = max(tr.points) - impact
            # long, dense and smooth beats short: the club head leaves the model quickly
            score = len(tr.points) + 0.5 * span - 4.0 * tr.fit.rms
            log.debug("hypothesis %d: %d points over %d frames, rms %.2f -> %.1f",
                      i, len(tr.points), span, tr.fit.rms, score)
            if score > best_score:
                best, best_score = tr, score
        if best is None:
            return None
        log.info("Ball tracking: %d detections over %d frames, rms %.2f px (%d hypotheses)",
                 len(best.points), max(best.points) - impact, best.fit.rms if best.fit else -1, len(hyps))
        return best
