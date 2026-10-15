"""Phase 3: person mask - caching, tracking exclusion, occlusion."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from kpmn_tracer.camera.homography import apply_h
from kpmn_tracer.camera.tracker import CameraTracker
from kpmn_tracer.segmentation.mask_cache import MaskTrack, soft_occlusion, tracking_exclusion
from kpmn_tracer.segmentation.provider import compute_masks, load_masks, occlusion_for_session, tracking_mask_fn
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot


class FakeSegmenter:
    """Returns a fixed rectangle as 'person' (lets us test caching without MediaPipe)."""

    calls = 0

    def segment(self, bgr: np.ndarray) -> np.ndarray:
        FakeSegmenter.calls += 1
        m = np.zeros(bgr.shape[:2], np.float32)
        h, w = m.shape
        m[h // 4: 3 * h // 4, w // 4: w // 2] = 1.0
        return m


def test_mask_track_interpolates_and_roundtrips(tmp_path: Path) -> None:
    a = np.zeros((10, 20), np.uint8)
    b = np.full((10, 20), 200, np.uint8)
    t = MaskTrack(20, (20, 10), 4, {0: a, 4: b})
    assert t.get(2)[0, 0] == pytest.approx(100 / 255)
    assert t.get(4, (40, 20)).shape == (20, 40)
    assert t.get(9) is None  # not analysed
    t.save(tmp_path / "m.npz")
    t2 = MaskTrack.load(tmp_path / "m.npz")
    assert t2.stride == 4 and t2.size == (20, 10) and sorted(t2.keys) == [0, 4]
    assert MaskTrack.key_frames(20, 4, 3, 13) == [0, 4, 8, 12, 13]


def test_exclusion_and_soft_occlusion() -> None:
    p = np.zeros((50, 50), np.float32)
    p[20:30, 20:30] = 1
    ex = tracking_exclusion(p, dilate_px=3)
    assert ex[18, 25] == 255 and ex[5, 5] == 0
    occ = soft_occlusion(p, 2.0)
    assert occ[25, 25] > 0.95 and occ[5, 5] < 0.01 and 0.1 < occ[25, 20] < 0.9  # soft edge


def test_mask_improves_camera_tracking(person_clip, tmp_path: Path) -> None:
    """Abnahme Phase 3: tracking error is measurably better with the person mask."""
    clip, truth, masks = person_clip
    sess = ClipSession.open(clip, cache_root=tmp_path)
    track = MaskTrack(80, (640, 360), 1, {i: m for i, m in enumerate(masks)})
    grid = np.stack(np.meshgrid(np.linspace(40, 600, 8), np.linspace(40, 320, 6)), -1).reshape(-1, 2)

    def err(mask_fn) -> float:
        res = CameraTracker(sess.reader.gray, (640, 360), mask_fn).track(20, 0, 79, detect_tripod=False)
        return float(np.mean([np.linalg.norm(
            apply_h(np.linalg.inv(res.H(f)), grid) - apply_h(np.array(truth["frames"][f]["world_to_frame"]), grid),
            axis=1).mean() for f in range(80)]))

    e_without = err(None)
    e_with = err(tracking_mask_fn(track, (640, 360)))
    assert e_with < 0.5 * e_without
    assert e_with < 0.5


def test_occlusion_in_export(person_clip, tmp_path: Path) -> None:
    from kpmn_tracer.io.export import ExportSettings, export
    from verify_overlay import iter_frames

    clip, truth, masks = person_clip
    sess = ClipSession.open(clip, cache_root=tmp_path)
    shot = Shot(impact_frame=20, land_frame=70, occlude=True)
    shot.set_anchor(AnchorKind.START, 100, 330)  # path crosses the person on the left
    shot.set_anchor(AnchorKind.APEX, 420, 40)
    shot.set_anchor(AnchorKind.LAND, 600, 200)
    sess.project.shots = [shot]
    sess.project.style.glow_strength = 0
    # inject ground-truth masks as the cached track
    from kpmn_tracer.segmentation.provider import mask_file, settings

    track = MaskTrack(80, (640, 360), 1, {i: m for i, m in enumerate(masks)})
    track.save(mask_file(sess, *settings(sess)))
    occ = occlusion_for_session(sess)
    out = export(sess.project, ExportSettings("prores", tmp_path / "occ.mov"), occ)
    for i, ov in enumerate(iter_frames(["-i", str(out)], 640, 360, 4, "rgba")):
        if i in (40, 60):
            inner = masks[i] > 0
            import cv2

            inner = cv2.erode(inner.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
            assert ov[..., 3][inner].max() <= 3  # cut where the person is
            assert ov[..., 3][~(cv2.dilate(masks[i], np.ones((9, 9), np.uint8)) > 0)].max() == 255


def test_compute_masks_is_cached_and_incremental(tripod_clip, tmp_path: Path) -> None:
    sess = ClipSession.open(tripod_clip[0], cache_root=tmp_path)
    FakeSegmenter.calls = 0
    t = compute_masks(sess, 10, 30, FakeSegmenter())
    n1 = FakeSegmenter.calls
    assert n1 == len(MaskTrack.key_frames(sess.project.frame_count, t.stride, 10, 30))
    compute_masks(sess, 10, 40, FakeSegmenter())
    assert FakeSegmenter.calls - n1 <= 6  # only the new frames
    loaded = load_masks(sess)
    assert loaded is not None and loaded.get(20) is not None and loaded.get(20).max() == 1.0


def test_mediapipe_segmenter_runs() -> None:
    from kpmn_tracer.segmentation.segmenter import MediaPipeSegmenter, ModelNotFoundError

    try:
        seg = MediaPipeSegmenter()
    except ModelNotFoundError:
        pytest.skip("models not downloaded")
    img = np.full((288, 512, 3), (90, 140, 80), np.uint8)
    p = seg.segment(img)
    seg.close()
    assert p.shape == (288, 512) and p.dtype == np.float32
    assert p.max() <= 1.0 and (p > 0.5).mean() < 0.05  # no person in an empty field
