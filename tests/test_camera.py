"""Phase 2: camera motion compensation."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kpmn_tracer.camera.homography import apply_h, corner_displacement, estimate, from_params, to_params
from kpmn_tracer.camera.shot_camera import analyze_shot_camera
from kpmn_tracer.camera.smoothing import SmoothParams, smooth_path, spike_outliers
from kpmn_tracer.camera.tracker import CameraTracker, TrackParams
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot


def sim(s: float, rot: float, tx: float, ty: float) -> np.ndarray:
    a = np.deg2rad(rot)
    return np.array([[s * np.cos(a), -s * np.sin(a), tx], [s * np.sin(a), s * np.cos(a), ty], [0, 0, 1]])


def test_params_roundtrip() -> None:
    Hs = np.stack([sim(1.1, 2, 5, -3), np.eye(3), sim(0.9, -1, 0, 7)])
    Hs[0, 2, 0] = 1e-5
    back = from_params(to_params(Hs, 640, 360), 640, 360)
    assert np.allclose(back, Hs / Hs[:, 2:3, 2:3], atol=1e-8)


def test_estimate_recovers_homography_with_outliers() -> None:
    rng = np.random.default_rng(0)
    H = sim(1.05, 3, 12, -4)
    src = rng.uniform(0, 600, (200, 2))
    dst = apply_h(H, src) + rng.normal(0, 0.1, (200, 2))
    dst[:40] += rng.uniform(-50, 50, (40, 2))
    He, inl = estimate(src, dst)
    assert He is not None and inl[40:].mean() > 0.95
    assert corner_displacement(np.linalg.inv(H) @ He, 600, 600) < 0.2


def test_spike_outlier_is_bridged_but_shake_kept() -> None:
    n = 60
    t = np.arange(n)
    Hs = np.stack([sim(1.0, 0.3 * np.sin(t[i] * 1.2), 6 * np.sin(1.19 * i), 4 * np.cos(0.8 * i)) for i in range(n)])
    clean = Hs.copy()
    Hs[30] = sim(1.0, 0, 60, -40)  # broken registration
    conf = np.full(n, 0.8)
    x = to_params(Hs, 640, 360)
    out = spike_outliers(x, SmoothParams())
    assert out[30] and out.sum() == 1
    sm, c2 = smooth_path(Hs, conf, 640, 360, ref_index=0)
    assert c2[30] == 0
    err = [corner_displacement(np.linalg.inv(clean[i]) @ sm[i], 640, 360) for i in range(n)]
    assert err[30] < 4.0  # bridged from neighbours
    assert np.median(err) < 0.05  # real shake is not smoothed away


@pytest.fixture(scope="module")
def handheld(media_dir: Path) -> tuple[Path, dict]:
    from synth import ShotSpec, SynthConfig, generate

    cfg = SynthConfig(width=960, height=540, fps=30, n_frames=100, shots=[ShotSpec(impact_frame=20)],
                      ref_frame=20, shake_px=8, shake_rot_deg=0.6, zoom_end=1.2, pan_px_per_s=(30, -10),
                      crf=14)
    truth = generate(cfg, media_dir, "handheld")
    return media_dir / "handheld.mp4", truth


def test_tracker_accuracy_on_shaky_zooming_clip(handheld, tmp_path: Path) -> None:
    """Abnahme Phase 2: mean tracer position error <= 2 px vs ground truth."""
    clip, truth = handheld
    sess = ClipSession.open(clip, cache_root=tmp_path)
    shot = Shot(impact_frame=20, land_frame=95)
    flying = [f["balls"][0]["world"] for f in truth["frames"] if f["balls"][0] and f["balls"][0]["flying"]]
    shot.set_anchor(AnchorKind.START, *flying[0])
    shot.set_anchor(AnchorKind.APEX, *min(flying, key=lambda p: p[1]))
    shot.set_anchor(AnchorKind.LAND, *flying[-1])
    shot.camera = analyze_shot_camera(sess, shot)
    assert shot.camera.mode == "tracked"
    path_ref = shot.path().sample(60)
    errs = []
    for f in range(shot.impact_frame, sess.project.frame_count):  # tracer is visible from impact on
        W2F = np.array(truth["frames"][f]["world_to_frame"])  # world == impact frame coords
        expected = apply_h(W2F, path_ref)
        got = shot.to_frame(path_ref, f)
        errs.append(np.linalg.norm(got - expected, axis=1).mean())
    errs = np.array(errs)
    assert errs.mean() <= 2.0, errs.mean()
    assert errs.mean() < 0.3 and errs.max() < 1.5  # what we actually achieve
    assert min(shot.camera.confidence) > 0.5
    # without compensation the error would be large
    no_comp = np.mean([np.linalg.norm(apply_h(np.array(truth["frames"][f]["world_to_frame"]), path_ref) - path_ref,
                                      axis=1).mean() for f in range(100)])
    assert no_comp > 10


def test_tripod_detection_skips_tracking(tripod_clip, tmp_path: Path) -> None:
    sess = ClipSession.open(tripod_clip[0], cache_root=tmp_path)
    shot = Shot(impact_frame=15, land_frame=80)
    shot.set_anchor(AnchorKind.START, 300, 300)
    shot.set_anchor(AnchorKind.LAND, 400, 150)
    cam = analyze_shot_camera(sess, shot)
    assert cam.mode == "tripod"
    forced = analyze_shot_camera(sess, shot, force_tracking=True)
    assert forced.mode == "tracked"
    assert max(corner_displacement(np.array(H), 640, 360) for H in forced.homographies) < 0.5


def test_handheld_is_not_tripod(handheld, tmp_path: Path) -> None:
    sess = ClipSession.open(handheld[0], cache_root=tmp_path)
    tr = CameraTracker(sess.reader.gray, (sess.reader.width, sess.reader.height), params=TrackParams())
    assert not tr.is_tripod(20, 0, 99)


def test_unusable_frames_get_low_confidence_and_are_bridged(handheld, tmp_path: Path) -> None:
    clip, truth = handheld
    sess = ClipSession.open(clip, cache_root=tmp_path)
    broken = {50, 51, 52}
    rng = np.random.default_rng(3)

    def gray(f: int) -> np.ndarray:
        g = sess.reader.gray(f)
        if f in broken:  # e.g. motion blur / lens flare: no usable structure
            return (rng.random(g.shape) * 40 + 100).astype(np.uint8)
        return g

    tr = CameraTracker(gray, (sess.reader.width, sess.reader.height))
    res = tr.track(20, 10, 90)
    for f in broken:
        assert res.confidence[f - 10] < 0.5
    assert np.all(np.delete(res.confidence, [f - 10 for f in broken]) > 0.5)
    pts = np.array([[200.0, 150], [700, 300], [480, 400]])
    for f in (49, 51, 53, 70):
        W2F = np.array(truth["frames"][f]["world_to_frame"])
        err = np.linalg.norm(apply_h(np.linalg.inv(res.H(f)), pts) - apply_h(W2F, pts), axis=1).mean()
        assert err < (8.0 if f in broken else 0.5), (f, err)
