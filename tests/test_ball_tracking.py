"""Phase 5: automatic ball tracking (classical, physics-guided)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from kpmn_tracer.analysis import AnalysisOptions, analyze_shot, shot_error_px
from kpmn_tracer.ball.auto import anchor_times
from kpmn_tracer.ball.candidates import ClassicDetector
from kpmn_tracer.ball.flightfit import FlightModel, ransac_fit
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot

# ------------------------------------------------------------------ model / fit


def test_ransac_recovers_model_with_outliers() -> None:
    true = FlightModel((500.0, 600.0), 3.0, 0.01, -40.0, 0.35, 0.03)
    t = np.arange(1, 80, dtype=float)
    rng = np.random.default_rng(0)
    xy = true(t) + rng.normal(0, 0.3, (t.size, 2))
    bad = rng.random(t.size) < 0.25
    xy[bad] += rng.uniform(-60, 60, (bad.sum(), 2))
    r = ransac_fit(t, xy, true.start)
    assert r is not None
    assert r.inliers[~bad].mean() > 0.95 and r.inliers[bad].mean() < 0.1
    tt = np.linspace(0, 150, 300)
    assert np.abs(r.model(tt) - true(tt)).max() < 1.5  # extrapolates well beyond the data


def test_landing_time_matches_ground_return() -> None:
    import sys

    sys.path.insert(0, "tools")
    from synth import ShotSpec, SynthConfig, ball_world_track

    cfg = SynthConfig(width=1920, height=1080, fps=30, n_frames=300, shots=[ShotSpec(impact_frame=0)])
    pos, _, fl = ball_world_track(cfg, cfg.shots[0])
    idx = np.flatnonzero(fl)[1:60]
    r = ransac_fit(idx.astype(float), pos[idx], tuple(pos[0]))
    t_true = np.flatnonzero(fl)[-1]
    assert abs(r.model.landing_time(540) - t_true) < 2.0


def test_anchor_times_dense_then_sparse() -> None:
    ts = anchor_times(100.0, 30.0)
    assert list(ts[:6]) == [0, 1, 2, 3, 4, 5] and ts[-1] == 100.0
    assert np.all(np.diff(ts) > 0) and np.diff(ts)[6:-1].min() >= 2


# ------------------------------------------------------------------ detector


def test_detector_finds_bright_and_dark_movers_but_not_static_edges() -> None:
    rng = np.random.default_rng(0)
    bg = np.full((120, 200), 120, np.uint8)
    bg[:, 100:] = 200  # strong static edge
    bg = cv2.add(bg, rng.integers(0, 3, bg.shape, dtype=np.uint8))
    frames = []
    for i in range(5):
        f = bg.copy()
        cv2.circle(f, (30 + 10 * i, 60), 2, 250, -1)  # bright ball over the dark half
        cv2.circle(f, (190 - 15 * i, 30), 2, 60, -1)  # dark ball over the bright half
        frames.append(f)
    det = ClassicDetector(lambda f: frames[f], lambda f: np.eye(3), (200, 120), 5)
    c = det.detect(2, (0, 0, 200, 120), 2.0, gap=1)
    pos = sorted((round(x.x), round(x.y), x.polarity) for x in c)
    assert (50, 60, 1) in pos and (160, 30, -1) in pos
    assert len(c) == 2


# ------------------------------------------------------------------ end to end


def _clip(media_dir: Path, name: str, **kw):
    from synth import ShotSpec, SynthConfig, generate

    spec_keys = ("hidden_intervals", "ball_visible_after_s", "drag", "side_accel", "start_xyz")
    spec_kw = {k: kw.pop(k) for k in spec_keys if k in kw}
    spec = ShotSpec(impact_frame=15, velocity=(3, -22, 48), drag=spec_kw.pop("drag", 0.05),
                    side_accel=spec_kw.pop("side_accel", 0.8), **spec_kw)
    cfg = SynthConfig(width=960, height=540, fps=30, n_frames=150, shots=[spec], ref_frame=15,
                      club=True, crf=14, **kw)
    path = media_dir / f"{name}.mp4"
    truth = generate(cfg, media_dir, name)
    return path, truth


def _run(path: Path, truth: dict, tmp_path: Path, start_offset=(1.5, -1.0)) -> tuple[Shot, ClipSession]:
    sess = ClipSession.open(path, cache_root=tmp_path)
    imp = truth["impact_frames"][0]
    b0 = truth["frames"][imp]["balls"][0]["frame"]
    shot = Shot(impact_frame=imp)
    shot.set_anchor(AnchorKind.START, b0[0] + start_offset[0], b0[1] + start_offset[1])  # sloppy click
    analyze_shot(sess, shot, AnalysisOptions(use_person_mask=False))
    return shot, sess


def _truth(truth: dict, visible_only: bool) -> dict[int, np.ndarray]:
    imp = truth["impact_frames"][0]
    return {i: np.array(f["balls"][0]["world"]) for i, f in enumerate(truth["frames"])
            if i > imp and f["balls"][0] and f["balls"][0]["flying"] and (f["balls"][0]["visible"] or not visible_only)}


CASES = {
    "tripod": {},
    "handheld": {"shake_px": 6.0, "shake_rot_deg": 0.4},
    "handheld_gap": {"shake_px": 5.0, "shake_rot_deg": 0.3, "hidden_intervals": [(45, 60)]},
    "handheld_vanishes": {"shake_px": 4.0, "shake_rot_deg": 0.3, "ball_visible_after_s": 2.0},
    "faint_ball": {"shake_px": 4.0, "ball_gain": 0.4},
}


@pytest.mark.parametrize("case", list(CASES))
def test_auto_tracking_accuracy(case: str, media_dir: Path, tmp_path: Path) -> None:
    """Abnahme Phase 5: mean trajectory error <= 3 px (tripod + handheld, tiny/faint/hidden ball)."""
    path, truth = _clip(media_dir, f"auto_{case}", **dict(CASES[case]))
    shot, sess = _run(path, truth, tmp_path)
    assert shot.source == "auto" and shot.confidence >= 0.5, shot.confidence
    assert shot.uses_anchor_times()
    err_vis = shot_error_px(shot, _truth(truth, True), sess.project.fps)
    err_all = shot_error_px(shot, _truth(truth, False), sess.project.fps)
    assert err_vis <= 3.0, err_vis
    assert err_all <= 3.0, err_all
    land_true = max(_truth(truth, False)) - truth["impact_frames"][0]
    assert abs(shot.flight_frames(sess.project.fps) - land_true) <= 0.06 * land_true
    if "shake_px" in CASES[case]:
        assert shot.camera.mode == "tracked"


def test_result_is_editable_like_manual(media_dir: Path, tmp_path: Path) -> None:
    path, truth = _clip(media_dir, "auto_tripod", **CASES["tripod"])
    shot, sess = _run(path, truth, tmp_path)
    kinds = [a.kind for a in shot.anchors]
    assert kinds[0] == AnchorKind.START and kinds[-1] == AnchorKind.LAND and AnchorKind.APEX in kinds
    apex = shot.anchor(AnchorKind.APEX)
    assert apex.y == min(a.y for a in shot.anchors)
    # roundtrip through the project file keeps everything
    d = shot.to_dict()
    assert Shot.from_dict(d).to_dict() == d
    # user drags the landing point: still a valid, renderable shot
    shot.set_anchor(AnchorKind.LAND, apex.x + 50, apex.y + 100)
    assert shot.path() is not None and shot.head_u(shot.impact_frame + 10, 30.0) is not None


def test_no_ball_falls_back_to_prefilled_manual(media_dir: Path, tmp_path: Path) -> None:
    path, truth = _clip(media_dir, "auto_noball", ball_gain=0.0)
    shot, sess = _run(path, truth, tmp_path)
    assert shot.confidence is not None and shot.confidence < 0.5
    assert shot.is_complete() and not shot.uses_anchor_times()
    assert [a.kind for a in shot.anchors] == [AnchorKind.START, AnchorKind.APEX, AnchorKind.LAND]
    assert "prüfen" in shot.label or "nicht gefunden" in shot.label


def test_close_fast_launch_keeps_first_frames(media_dir: Path, tmp_path: Path) -> None:
    """Ball close to the camera: huge screen speed right after impact must not be dropped as outliers."""
    path, truth = _clip(media_dir, "auto_close", start_xyz=(0.0, 0.9, 2.0), drag=0.25)
    shot, sess = _run(path, truth, tmp_path)
    imp = truth["impact_frames"][0]
    tr = _truth(truth, True)
    first = [f for f in sorted(tr)[:3]]
    p = shot.path()
    for f in first:
        assert np.linalg.norm(p.evaluate(shot.head_u(f, 30.0))[0] - tr[f]) < 6.0, f
    assert shot_error_px(shot, tr, 30.0) <= 3.0
    assert imp + 1 in first


# ------------------------------------------------------------------ steep close launch (IMG_2366)

# Ball positions measured in the user's clip IMG_2366 (proxy 1080x1920, frames since impact):
# a wedge flying almost straight up, ~430 px in the first frame, ~70 px in the fifth.
STEEP_START = (670.2, 1546.4)
STEEP_BALL = {1: (706, 1127), 2: (718, 905), 3: (726, 768), 4: (734, 673), 5: (736, 602), 6: (741, 551),
              7: (743, 508), 8: (744, 473), 9: (743, 446), 10: (743, 423), 11: (743, 404), 12: (742, 388),
              13: (741, 375), 14: (739, 364), 15: (738, 354), 16: (736, 347), 17: (735, 340), 18: (733, 334)}
# the club/hands leave the ball spot too, much slower (the old tracker chose them)
STEEP_CLUB = {2: (691, 1182), 3: (694, 1096), 4: (692, 1037), 5: (691, 996), 6: (688, 967), 7: (684, 948),
              8: (680, 933), 9: (676, 925), 10: (672, 920)}


class _TableDetector:
    def __init__(self, impact: int, tables: list[dict[int, tuple[float, float]]]) -> None:
        self.impact, self.tables = impact, tables

    def detect(self, frame: int, roi, expected_radius: float = 2.0, gap: int = 2):
        from kpmn_tracer.ball.candidates import Candidate

        x0, y0, x1, y1 = roi
        out = []
        for tab in self.tables:
            p = tab.get(frame - self.impact)
            if p is not None and x0 <= p[0] < x1 and y0 <= p[1] < y1:
                out.append(Candidate(frame, float(p[0]), float(p[1]), 5.0, 60.0, 1))
        return out


def test_steep_close_launch_is_tracked_not_the_club() -> None:
    from kpmn_tracer.ball.tracker import BallTracker

    impact = 12
    det = _TableDetector(impact, [STEEP_BALL, STEEP_CLUB])
    tr = BallTracker(det, (1080, 1920), 30.0, 60).track(impact, STEEP_START, 8.9)
    assert tr is not None
    got = {f - impact for f in tr.points}
    assert set(range(1, 19)) <= got  # whole ascent incl. the first frames and the part high above
    assert all(np.hypot(*(np.array([tr.points[f + impact].x, tr.points[f + impact].y]) - STEEP_BALL[f])) < 1e-6
               for f in STEEP_BALL)
