"""High-level analysis pipeline used by the GUI and the batch/CLI mode.

``analyze_shot``: person mask -> camera path -> ball tracking -> anchors.
``analyze_clip``: impact detection -> one shot per impact -> ``analyze_shot``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from kpmn_tracer.ball.auto import MAX_FLIGHT_S, AutoResult, apply_to_shot, auto_track, prefill_without_track
from kpmn_tracer.camera.shot_camera import analyze_shot_camera
from kpmn_tracer.camera.tracker import track_range_for_shot
from kpmn_tracer.io.decode import CancelFn, ProgressFn
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot

log = logging.getLogger(__name__)


@dataclass
class AnalysisOptions:
    use_person_mask: bool = True
    track_camera: bool = True
    max_flight_s: float = MAX_FLIGHT_S
    detector: str = "classic"  # "classic" | "yolo" | "both"
    yolo_model: str | None = None


def detector_factory(o: AnalysisOptions):
    """Build the ball detector factory for the chosen mode (YOLO only if configured)."""
    from kpmn_tracer.ball.auto import classic_factory

    if o.detector == "classic" or not o.yolo_model:
        if o.detector != "classic":
            log.warning("No YOLO model configured - using the classic detector")
        return classic_factory
    from kpmn_tracer.ball.ml_detector import CombinedDetector, YoloDetector, load_yolo

    model = load_yolo(o.yolo_model)

    def factory(reader, H, size, n, mask):
        yolo = YoloDetector(reader.read, H, size, n, model)
        if o.detector == "yolo":
            return yolo
        return CombinedDetector([classic_factory(reader, H, size, n, mask), yolo])

    return factory


def _sub(progress: ProgressFn | None, a: float, b: float) -> ProgressFn:
    return lambda f: progress(a + (b - a) * f) if progress else None


def analyze_shot(
    session: ClipSession,
    shot: Shot,
    options: AnalysisOptions | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> AutoResult | None:
    """Fully automatic analysis of one shot (needs impact frame + ball start or start hint)."""
    o = options or AnalysisOptions()
    p = session.project
    masks = None
    # provisional landing so the camera/mask range covers the longest possible flight
    saved_land, saved_anchors = shot.land_frame, list(shot.anchors)
    shot.land_frame = shot.impact_frame + o.max_flight_s * p.fps
    for a in shot.anchors:
        a.t = None
    try:
        if o.use_person_mask:
            from kpmn_tracer.segmentation.provider import compute_masks

            a_, b_ = track_range_for_shot(shot.impact_frame, shot.flight_frames(p.fps), p.fps, p.frame_count)
            try:
                masks = compute_masks(session, a_, b_, progress=_sub(progress, 0.0, 0.3), cancel=cancel)
            except (FileNotFoundError, ImportError, RuntimeError) as exc:
                log.warning("Person mask unavailable: %s", exc)
        mfn = None
        if masks is not None:
            from kpmn_tracer.segmentation.provider import tracking_mask_fn

            mfn = tracking_mask_fn(masks, (session.reader.width, session.reader.height))
        if o.track_camera:
            shot.camera = analyze_shot_camera(session, shot, mfn, progress=_sub(progress, 0.3, 0.7), cancel=cancel)
        result = auto_track(session, shot, detector_factory(o), mask=mfn,
                            progress=_sub(progress, 0.7, 1.0), cancel=cancel)
    except BaseException:
        shot.land_frame, shot.anchors = saved_land, saved_anchors
        raise
    if result is None:
        shot.land_frame, shot.anchors = saved_land, saved_anchors
        if shot.anchor(AnchorKind.LAND) is None:
            prefill_without_track(shot, session)
        log.info("Shot @%d: ball not found - prefilled for manual editing", shot.impact_frame)
        return None
    apply_to_shot(result, shot, session)
    start = shot.anchor(AnchorKind.START)
    if start is not None:
        p.ball_start_hint = (start.x, start.y)
    return result


def analyze_clip(
    session: ClipSession,
    ball_hint: tuple[float, float] | None = None,
    hint_frame: int | None = None,
    options: AnalysisOptions | None = None,
    min_confidence: float = 0.5,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> list[Shot]:
    """Find all impacts and analyse every shot. Existing shots at the same frame are kept."""
    from kpmn_tracer.ball.impact import detect_impacts

    p = session.project
    hint = ball_hint or p.ball_start_hint
    cands = detect_impacts(session, hint, hint_frame if hint_frame is not None else 0,
                           progress=_sub(progress, 0.0, 0.2), cancel=cancel)
    p.settings["impact_candidates"] = [c.to_dict() for c in cands]
    todo = [c for c in cands if c.confidence >= min_confidence
            and not any(abs(s.impact_frame - c.frame) <= 2 for s in p.shots)]
    new: list[Shot] = []
    for i, c in enumerate(todo):
        shot = Shot(impact_frame=c.frame)
        pos = c.ball_pos or hint
        if pos is not None:
            shot.set_anchor(AnchorKind.START, *pos)
        a, b = 0.2 + 0.8 * i / len(todo), 0.2 + 0.8 * (i + 1) / len(todo)
        res = analyze_shot(session, shot, options, _sub(progress, a, b), cancel)
        shot.confidence = (res.confidence if res else 0.0) * c.confidence
        new.append(shot)
        p.shots.append(shot)
    p.shots.sort(key=lambda s: s.impact_frame)
    if progress:
        progress(1.0)
    log.info("Clip analysed: %d new shots (%s)", len(new),
             ", ".join(f"{s.impact_frame}:{s.confidence:.0%}" for s in new))
    return new


def shot_error_px(shot: Shot, truth_world: dict[int, np.ndarray], fps: float) -> float:
    """Mean distance (source px) between the shot's ball position and ground truth (testing aid)."""
    path = shot.path()
    errs = []
    for f, xy in truth_world.items():
        u = shot.head_u(f, fps)
        if u is None or path is None:
            continue
        errs.append(np.linalg.norm(path.evaluate(u)[0] - xy))
    return float(np.mean(errs)) if errs else float("inf")
