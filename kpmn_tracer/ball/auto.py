"""Automatic ball tracking for one shot -> the same editable anchors as the manual mode.

Steps: start point + ball size -> camera path (if not yet analysed) -> person
mask (optional) -> candidate detection + physics-guided tracking -> final
trajectory -> confidence -> anchors.

Final trajectory:
* observed part: smoothing spline through the detections (bridges gaps),
* afterwards: perspective flight model fitted with emphasis on the latest
  detections, shifted to join the spline continuously, extrapolated to the
  estimated landing.

High confidence: anchors carry measured times (``AnchorTiming``).
Low confidence: the shot gets prefilled manual anchors (start, estimated apex,
estimated landing) and the user only corrects them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.interpolate import make_smoothing_spline

from kpmn_tracer.ball.candidates import BallDetector, ClassicDetector
from kpmn_tracer.ball.flightfit import FlightModel, fit_linear
from kpmn_tracer.ball.impact import locate_ball
from kpmn_tracer.ball.tracker import BallTrack, BallTracker, BallTrackParams
from kpmn_tracer.io.decode import CancelFn, ProgressFn
from kpmn_tracer.io.reader import FrameReader
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import Anchor, AnchorKind, Shot

log = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.5
MAX_FLIGHT_S = 9.0


@dataclass
class Trajectory:
    """Ball position (reference proxy px) as a function of frames since impact."""

    spline_x: object | None
    spline_y: object | None
    t_obs: float  # last observed time (end of the spline part)
    tail: FlightModel
    tail_offset: np.ndarray
    t_land: float

    def __call__(self, t: float | np.ndarray) -> np.ndarray:
        t = np.atleast_1d(np.asarray(t, float))
        out = self.tail(t) + self.tail_offset
        if self.spline_x is not None:
            m = t <= self.t_obs
            out[m, 0] = self.spline_x(t[m])  # type: ignore[operator]
            out[m, 1] = self.spline_y(t[m])  # type: ignore[operator]
        return out

    def apex_time(self) -> float:
        ts = np.linspace(0, self.t_land, max(100, int(self.t_land * 4)))
        return float(ts[int(np.argmin(self(ts)[:, 1]))])


@dataclass
class AutoResult:
    track: BallTrack
    trajectory: Trajectory
    confidence: float
    n_detections: int
    t_obs: float
    rms: float


def build_trajectory(track: BallTrack, cy: float, fps: float, max_flight_frames: float) -> Trajectory:
    t, xy = track.arrays()
    t = np.r_[0.0, t]
    xy = np.vstack([track.start, xy])
    t_obs = float(t.max())
    sx = sy = None
    if len(t) >= 5:
        # smoothing strength chosen by generalised cross-validation (per coordinate):
        # removes detection jitter without flattening the real curve
        sx = make_smoothing_spline(t, xy[:, 0])
        sy = make_smoothing_spline(t, xy[:, 1])
    w = np.exp(-(t_obs - t) / max(0.6 * fps, 1.0))  # emphasise the latest part
    w[0] = 0.2
    tail = fit_linear(t, xy, track.start, perspective=True, w=w)
    if tail is None or tail.c < -0.9 / max(max_flight_frames, 1):
        tail = fit_linear(t, xy, track.start, perspective=False, w=w)
    assert tail is not None
    if sx is not None:
        end = np.array([float(sx(t_obs)), float(sy(t_obs))])
        offset = end - tail(t_obs)[0]
    else:
        offset = np.zeros(2)
    t_land = tail.landing_time(cy)
    if t_land is None or t_land < t_obs:
        global_land = track.fit.model.landing_time(cy) if track.fit else None
        t_land = global_land if (global_land and global_land >= t_obs) else None
    if t_land is None:
        t_land = max(t_obs, min(max_flight_frames, t_obs * 1.6))
    t_land = float(min(t_land, max_flight_frames))
    return Trajectory(sx, sy, t_obs, tail, offset, t_land)


def confidence(track: BallTrack, traj: Trajectory, fps: float) -> tuple[float, float]:
    """(confidence 0..1, rms px of detections against the final trajectory)."""
    t, xy = track.arrays()
    if len(t) == 0:
        return 0.0, np.inf
    rms = float(np.sqrt(np.mean(np.sum((traj(t) - xy) ** 2, axis=1))))
    coverage = len(t) / max(1.0, t.max())
    span = min(1.0, t.max() / (0.8 * fps))  # at least ~0.8 s observed for full confidence
    count = min(1.0, len(t) / 12.0)
    fit_q = float(np.exp(-max(rms - 0.5, 0.0) / 1.5))
    conf = count * span * np.sqrt(min(1.0, coverage)) * fit_q
    return float(np.clip(conf, 0.0, 1.0)), rms


def _start_point(session: ClipSession, shot: Shot) -> tuple[np.ndarray | None, float]:
    """Start (reference proxy px) and ball radius (proxy px) - located near the hint."""
    a = shot.anchor(AnchorKind.START)
    hint_src = (a.x, a.y) if a else session.project.ball_start_hint
    if hint_src is None:
        return None, 2.0
    hint = session.source_to_proxy(np.array([hint_src]))[0]
    g = session.reader.gray(shot.impact_frame)
    loc = locate_ball(g, (float(hint[0]), float(hint[1])), search_r=max(6.0, 0.01 * max(g.shape)))
    if loc is None:
        return hint, 2.0
    return np.array([loc[0], loc[1]]), float(loc[2])


def auto_track(
    session: ClipSession,
    shot: Shot,
    detector: BallDetector | None = None,
    mask=None,
    params: BallTrackParams | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> AutoResult | None:
    """Track the ball of ``shot``. The shot's camera track must cover the flight."""
    p = session.project
    report = progress or (lambda _f: None)
    start, ball_r = _start_point(session, shot)
    if start is None:
        raise ValueError("Ball-Startpunkt fehlt: im Impact-Frame mit „Start“ auf den Ball klicken.")
    S = np.diag([session.sx, session.sy, 1.0])
    Si = np.linalg.inv(S)

    def H_proxy(f: int) -> np.ndarray:
        return S @ shot.camera.H(f) @ Si

    last = p.frame_count
    if shot.camera.mode == "tracked":
        last = min(last, shot.camera.first_frame + len(shot.camera.homographies))
    with FrameReader(session.reader.path, cache_size=24) as reader:
        det = detector or ClassicDetector(reader.gray, H_proxy, (reader.width, reader.height), last, mask)
        tracker = BallTracker(det, (reader.width, reader.height), p.fps, last, params)
        track = tracker.track(shot.impact_frame, (float(start[0]), float(start[1])), ball_r,
                              lambda f: report(0.9 * f), cancel)
    if track is None or not track.points:
        return None
    traj = build_trajectory(track, session.reader.height / 2, p.fps, MAX_FLIGHT_S * p.fps)
    conf, rms = confidence(track, traj, p.fps)
    report(1.0)
    log.info("Auto tracking: confidence %.2f, %d detections, rms %.2f px, landing after %.0f frames",
             conf, len(track.points), rms, traj.t_land)
    return AutoResult(track, traj, conf, len(track.points), traj.t_obs, rms)


def anchor_times(t_land: float, fps: float) -> np.ndarray:
    """Dense right after impact (fast screen motion), then every ~0.1 s."""
    step = max(2.0, round(fps / 10))
    early = np.arange(0.0, min(6.0, t_land))
    late = np.arange(6.0, t_land, step)
    ts = np.unique(np.r_[early, late, t_land])
    return ts[ts <= t_land]


def apply_to_shot(result: AutoResult, shot: Shot, session: ClipSession, threshold: float = CONFIDENCE_THRESHOLD) -> None:
    """Write the result into ``shot`` (same structure as manual tracing)."""
    fps = session.project.fps
    traj = result.trajectory
    inv = np.array([1.0 / session.sx, 1.0 / session.sy])
    t_apex = traj.apex_time()
    shot.source = "auto"
    shot.confidence = result.confidence
    shot.shape.launch_steepness = 0.0
    shot.shape.descent_steepness = 0.0
    if result.confidence >= threshold:
        ts = anchor_times(traj.t_land, fps)
        if 0 < t_apex < traj.t_land:
            ts = np.unique(np.r_[ts[np.abs(ts - t_apex) > 0.75], t_apex])
        pts = traj(ts) * inv
        anchors = []
        for i, (tt, (x, y)) in enumerate(zip(ts, pts)):
            kind = AnchorKind.POINT
            if i == 0:
                kind = AnchorKind.START
            elif i == len(ts) - 1:
                kind = AnchorKind.LAND
            elif abs(tt - t_apex) < 1e-9:
                kind = AnchorKind.APEX
            anchors.append(Anchor(float(x), float(y), kind, float(tt)))
        shot.anchors = anchors
        shot.land_frame = shot.impact_frame + traj.t_land
        shot.label = "auto"
    else:
        # prefilled manual mode: start, estimated apex, estimated landing - user corrects
        t_apex = t_apex if 0 < t_apex < traj.t_land else traj.t_land * 0.45
        pts = traj(np.array([0.0, t_apex, traj.t_land])) * inv
        shot.anchors = [Anchor(float(pts[0, 0]), float(pts[0, 1]), AnchorKind.START),
                        Anchor(float(pts[1, 0]), float(pts[1, 1]), AnchorKind.APEX),
                        Anchor(float(pts[2, 0]), float(pts[2, 1]), AnchorKind.LAND)]
        shot.land_frame = shot.impact_frame + traj.t_land
        shot.shape.launch_steepness = 0.5
        shot.shape.descent_steepness = 0.4
        shot.label = "auto – bitte prüfen"


def prefill_without_track(shot: Shot, session: ClipSession) -> None:
    """Nothing tracked: typical shape from the start point so the user can drag it into place."""
    start, _ = _start_point(session, shot)
    if start is None:
        return
    p = session.project
    w, h = p.width, p.height
    sx, sy = start / np.array([session.sx, session.sy])
    shot.anchors = [Anchor(float(sx), float(sy), AnchorKind.START),
                    Anchor(float(sx + 0.05 * w), float(max(0.05 * h, sy - 0.55 * h)), AnchorKind.APEX),
                    Anchor(float(sx + 0.08 * w), float(sy - 0.3 * h), AnchorKind.LAND)]
    shot.land_frame = None
    shot.source = "auto"
    shot.confidence = 0.0
    shot.label = "auto – nicht gefunden"
