import numpy as np
import pytest

from kpmn_tracer.trace.model import AnchorKind, CameraTrack, OffsetKeyframe, Shot


def manual_shot() -> Shot:
    s = Shot(impact_frame=10)
    s.set_anchor(AnchorKind.LAND, 500, 300)
    s.set_anchor(AnchorKind.START, 100, 500)
    s.set_anchor(AnchorKind.APEX, 350, 100)
    s.land_frame = 70
    return s


def test_anchor_order_is_kept() -> None:
    s = manual_shot()
    assert [a.kind for a in s.anchors] == [AnchorKind.START, AnchorKind.APEX, AnchorKind.LAND]
    s.set_anchor(AnchorKind.APEX, 360, 90)
    assert len(s.anchors) == 3 and s.anchors[1].x == 360


def test_head_u_timeline() -> None:
    s = manual_shot()
    assert s.head_u(5, 30) is None
    assert s.head_u(10, 30) == pytest.approx(0)
    assert s.head_u(70, 30) == pytest.approx(1)
    assert s.head_u(200, 30) == 1.0
    assert 0 < s.head_u(30, 30) < s.head_u(40, 30) < 1


def test_default_flight_duration_uses_fps() -> None:
    s = manual_shot()
    s.land_frame = None
    assert s.flight_frames(60) == pytest.approx(240)


def test_anchor_times_override_easing() -> None:
    s = manual_shot()
    for a, t in zip(s.anchors, (0.0, 20.0, 50.0)):
        a.t = t
    s.source = "auto"
    assert s.uses_anchor_times()
    assert s.flight_frames(30) == 50
    path = s.path()
    assert s.head_u(30, 30) == pytest.approx(path.knots[1])


def test_offsets_interpolate() -> None:
    s = manual_shot()
    s.offsets = [OffsetKeyframe(20, 0, 0), OffsetKeyframe(40, 10, -4)]
    assert np.allclose(s.offset_at(30), (5, -2))
    assert np.allclose(s.offset_at(100), (10, -4))
    assert np.allclose(s.offset_at(0), (0, 0))


def test_camera_projection_roundtrip() -> None:
    s = manual_shot()
    H = np.array([[1.02, 0.01, 5.0], [-0.01, 0.99, -3.0], [1e-5, 0, 1]])
    s.camera = CameraTrack(first_frame=10, homographies=[H.tolist()] * 5, confidence=[1] * 5, mode="tracked")
    s.offsets = [OffsetKeyframe(12, 2, 1)]
    p = np.array([[120.0, 340.0], [400, 200]])
    assert np.allclose(s.to_ref(s.to_frame(p, 12), 12), p)


def test_serialisation_roundtrip() -> None:
    s = manual_shot()
    s.offsets = [OffsetKeyframe(3, 1.5, 2)]
    s.camera = CameraTrack(first_frame=2, homographies=[np.eye(3).tolist()], confidence=[0.9], mode="tracked")
    d = s.to_dict()
    s2 = Shot.from_dict(d)
    assert s2.to_dict() == d


def test_ball_here_pins_pull_the_head_onto_the_ball() -> None:
    """Ball flying away from the camera: screen speed drops ~50x after impact (user report)."""
    s = Shot(impact_frame=0, land_frame=90)
    s.set_anchor(AnchorKind.START, 560, 2340)
    s.set_anchor(AnchorKind.APEX, 770, 1070)
    s.set_anchor(AnchorKind.LAND, 682, 1922)
    pins = {1: (648, 1898), 2: (696, 1552), 4: (732, 1300), 8: (764, 1124), 15: (770, 1070), 52: (726, 1450)}
    for f, xy in pins.items():
        assert s.pin_ball(*xy, f, 30) is not None
    path = s.path()
    for f, xy in pins.items():
        assert np.allclose(path.evaluate(s.head_u(f, 30))[0], xy, atol=1e-6), f
    assert s.anchor(AnchorKind.APEX).t == 15  # clicking on the apex marker times the apex itself
    us = [s.head_u(f, 30) for f in range(0, 91)]
    assert np.all(np.diff(us) >= -1e-12)
    assert s.flight_frames(30) == 90  # landing time unchanged
    assert s.pin_ball(700, 1500, 95, 30) is None  # after landing: ignored


def test_easing_reaches_extreme_launch_profiles() -> None:
    from kpmn_tracer.trace.timing import EasingTiming

    e = EasingTiming(launch_boost=60, launch_decay=0.02, late_boost=0.8)
    assert e.u_at(1 / 90)[0] > 0.2  # a fifth of the path in the first frame (was < 0.1 with the old limits)
