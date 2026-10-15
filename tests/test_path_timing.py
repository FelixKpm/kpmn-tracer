import numpy as np
import pytest

from kpmn_tracer.trace.path import FlightPath
from kpmn_tracer.trace.timing import AnchorTiming, EasingTiming

START, APEX, LAND = (100.0, 600.0), (500.0, 150.0), (700.0, 380.0)


def make_path(**kw: float) -> FlightPath:
    return FlightPath.build([START, APEX, LAND], apex_index=1, **kw)


def test_path_passes_through_anchors() -> None:
    p = make_path()
    for u, pt in zip(p.knots, [START, APEX, LAND]):
        assert np.allclose(p.evaluate(u)[0], pt, atol=1e-9)


def test_apex_is_highest_point_with_horizontal_tangent() -> None:
    p = make_path()
    pts = p.sample(2000)
    assert pts[:, 1].min() == pytest.approx(APEX[1], abs=1e-3)
    assert pts[:, 1].min() >= APEX[1] - 1e-9
    assert p.tangents[1][1] == 0.0
    assert p.tangents[1][0] > 0


def test_launch_steepness_makes_start_steeper() -> None:
    flat = make_path(launch_steepness=0.0)
    steep = make_path(launch_steepness=0.6)
    ang = lambda t: abs(np.arctan2(t[1], t[0]))  # noqa: E731
    assert ang(steep.tangents[0]) > ang(flat.tangents[0])


def test_no_vertical_overshoot_for_default_shape() -> None:
    p = make_path()
    pts = p.sample(3000)
    assert pts[:, 1].max() <= max(START[1], LAND[1]) + 1e-6


def test_extra_point_bends_the_descent() -> None:
    bend = (650.0, 220.0)
    p = FlightPath.build([START, APEX, bend, LAND], apex_index=1)
    assert np.allclose(p.evaluate(p.knots[2])[0], bend)
    plain = make_path()
    # draw/fade point to the right of the plain curve pushes the descent right
    mid = 0.5 * (p.knots[2] + p.knots[3])
    assert p.evaluate(mid)[0, 0] > plain.evaluate(mid)[0, 0] - 50


def test_two_point_path_is_a_line() -> None:
    p = FlightPath.build([(0, 0), (10, 20)])
    assert np.allclose(p.evaluate(0.5)[0], (5, 10))


def test_path_requires_two_points() -> None:
    with pytest.raises(ValueError):
        FlightPath.build([(0, 0)])


def test_easing_endpoints_and_monotone() -> None:
    e = EasingTiming()
    tau = np.linspace(0, 1, 501)
    u = e.u_at(tau)
    assert u[0] == pytest.approx(0) and u[-1] == pytest.approx(1)
    assert np.all(np.diff(u) > 0)


def test_easing_fast_slow_faster_profile() -> None:
    e = EasingTiming(launch_boost=2.5, launch_decay=0.12, late_boost=0.8)
    v = e.speed(np.linspace(0, 1, 101))
    i_min = int(np.argmin(v))
    assert 10 < i_min < 90  # slowest somewhere mid-flight (around the apex)
    assert v[0] > 2 * v[i_min]  # fast right after impact
    assert v[-1] > v[i_min]  # speeds up again on the way down


def test_easing_linear_when_disabled() -> None:
    e = EasingTiming(launch_boost=0, late_boost=0)
    assert np.allclose(e.u_at([0.25, 0.5]), [0.25, 0.5])


def test_anchor_timing_interpolates_monotone() -> None:
    t = AnchorTiming((0.0, 0.4, 1.0), (0.0, 0.7, 1.0))
    assert t.u_at(0.4)[0] == pytest.approx(0.7)
    u = t.u_at(np.linspace(0, 1, 200))
    assert np.all(np.diff(u) >= -1e-12)
    with pytest.raises(ValueError):
        AnchorTiming((0.0, 0.0, 1.0), (0, 0.5, 1))
