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
