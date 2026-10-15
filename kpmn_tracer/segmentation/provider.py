"""Glue between a :class:`ClipSession` and the person mask track (compute, cache, query)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import numpy as np

from kpmn_tracer.io.decode import CancelFn, ProgressFn
from kpmn_tracer.io.reader import FrameReader
from kpmn_tracer.segmentation.mask_cache import MaskTrack, analysis_size, soft_occlusion, tracking_exclusion
from kpmn_tracer.segmentation.segmenter import DEFAULT_MODEL, MediaPipeSegmenter, PersonSegmenter
from kpmn_tracer.session import ClipSession

log = logging.getLogger(__name__)

DEFAULT_STRIDE = 2


def mask_file(session: ClipSession, model: str, stride: int) -> Path:
    return session.cache_dir / f"masks_{model}_s{stride}.npz"


def settings(session: ClipSession) -> tuple[str, int]:
    s = session.project.settings
    return s.get("mask_model", DEFAULT_MODEL), int(s.get("mask_stride", DEFAULT_STRIDE))


def load_masks(session: ClipSession) -> MaskTrack | None:
    model, stride = settings(session)
    path = mask_file(session, model, stride)
    if path.exists():
        try:
            return MaskTrack.load(path)
        except Exception:
            log.exception("Mask cache %s unreadable", path)
    return None


def compute_masks(
    session: ClipSession,
    first: int = 0,
    last: int | None = None,
    segmenter: PersonSegmenter | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> MaskTrack:
    """Compute (incrementally) the masks for ``first..last`` and store them in the cache."""
    model, stride = settings(session)
    track = load_masks(session) or MaskTrack(
        session.project.frame_count, analysis_size(session.reader.width, session.reader.height), stride)
    own = segmenter is None
    seg = segmenter or MediaPipeSegmenter(model)
    try:
        with FrameReader(session.reader.path, cache_size=2) as reader:
            track.compute(reader.read, seg, first, last, progress, cancel)
    finally:
        if own:
            seg.close()  # type: ignore[union-attr]
    track.save(mask_file(session, model, stride))
    session.project.settings["masks_cached"] = True
    return track


def tracking_mask_fn(track: MaskTrack | None, proxy_size: tuple[int, int]) -> Callable[[int], np.ndarray | None]:
    """Per-frame uint8 exclusion mask at proxy resolution (for the camera tracker)."""
    def fn(frame: int) -> np.ndarray | None:
        return tracking_exclusion(track.get(frame, proxy_size)) if track else None
    return fn


def occlusion_fn(track: MaskTrack | None, size: tuple[int, int], feather_px: float = 2.0
                 ) -> Callable[[int], np.ndarray | None]:
    """Per-frame soft occlusion matte at ``size`` (w, h)."""
    def fn(frame: int) -> np.ndarray | None:
        return soft_occlusion(track.get(frame, size), feather_px) if track else None
    return fn


def shot_mask_range(session: ClipSession, shot) -> tuple[int, int]:
    """Frames where a shot's tracer can be visible (impact .. landing + hold + fade)."""
    p = session.project
    st = p.style
    last = shot.impact_frame + shot.flight_frames(p.fps) + (st.hold_seconds + st.fade_out_seconds) * p.fps
    return shot.impact_frame, int(min(p.frame_count - 1, np.ceil(last) + 1))


def _has_masks(track: MaskTrack | None, first: int, last: int) -> bool:
    if track is None:
        return False
    return all(k in track.keys for k in MaskTrack.key_frames(track.frame_count, track.stride, first, last))


def occlusion_for_session(
    session: ClipSession, segmenter: PersonSegmenter | None = None,
    progress: ProgressFn | None = None, cancel: CancelFn | None = None,
) -> Callable[[int], np.ndarray | None]:
    """Occlusion at source resolution for export; computes missing masks of occluding shots first."""
    p = session.project
    track = load_masks(session)
    for shot in p.shots:
        if shot.occlude:
            a, b = shot_mask_range(session, shot)
            if not _has_masks(track, a, b):
                track = compute_masks(session, a, b, segmenter, progress, cancel)
    scale = min(p.width, p.height) / 1080
    return occlusion_fn(track, (p.width, p.height), 2.0 * max(scale, 0.5))
