"""Run camera tracking for a shot and store the result (in source pixels) in the shot."""

from __future__ import annotations

import logging

from kpmn_tracer.camera.tracker import (
    CameraTracker,
    MaskFn,
    TrackParams,
    result_to_source,
    track_range_for_shot,
)
from kpmn_tracer.io.decode import CancelFn, ProgressFn
from kpmn_tracer.io.reader import FrameReader
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import CameraTrack, Shot

log = logging.getLogger(__name__)


def analyze_shot_camera(
    session: ClipSession,
    shot: Shot,
    mask: MaskFn | None = None,
    params: TrackParams | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
    force_tracking: bool = False,
) -> CameraTrack:
    """Track the camera around ``shot`` and return the new :class:`CameraTrack`.

    Uses its own reader so the GUI preview can keep seeking meanwhile.
    ``mask(frame)`` returns a proxy-sized uint8 mask of pixels to ignore (person).
    """
    p = session.project
    first, last = track_range_for_shot(shot.impact_frame, shot.flight_frames(p.fps), p.fps, p.frame_count)
    with FrameReader(session.reader.path, cache_size=4) as reader:
        tracker = CameraTracker(reader.gray, (reader.width, reader.height), mask, params)
        res = tracker.track(shot.impact_frame, first, last, progress, cancel,
                            detect_tripod=not force_tracking)
    if res.mode == "tripod":
        cam = CameraTrack(mode="tripod", analyzed=True)
    else:
        Hs, conf = result_to_source(res, session.sx, session.sy)
        cam = CameraTrack(first_frame=res.first, homographies=Hs, confidence=conf, mode="tracked",
                          analyzed=True)
        bad = sum(c < 0.5 for c in conf)
        log.info("Camera tracked frames %d..%d (%d low-confidence)", first, last, bad)
    return cam
