import numpy as np
import pytest

from kpmn_tracer.render.style import TracerStyle, hex_to_rgb
from kpmn_tracer.render.tracer import TracerRenderer, composite_over, draw_stroke_mask, shot_geometry
from kpmn_tracer.trace.model import AnchorKind, Shot

W, H, FPS = 640, 360, 30.0


def shot() -> Shot:
    s = Shot(impact_frame=10, land_frame=70)
    s.set_anchor(AnchorKind.START, 100, 330)
    s.set_anchor(AnchorKind.APEX, 400, 60)
    s.set_anchor(AnchorKind.LAND, 560, 200)
    return s


def plain_style(**kw) -> TracerStyle:
    base = dict(glow_strength=0, core_highlight=0, head_dot=False, taper=0, width=6)
    base.update(kw)
    return TracerStyle(**base)


def test_hex_to_rgb() -> None:
    assert hex_to_rgb("#ff0000") == (1.0, 0.0, 0.0)
    assert hex_to_rgb("0f0") == (0.0, 1.0, 0.0)


def test_nothing_before_impact() -> None:
    r = TracerRenderer(W, H, FPS, TracerStyle())
    assert r.render([shot()], 9)[..., 3].max() == 0


def test_line_is_drawn_on_path_with_colour() -> None:
    s = shot()
    r = TracerRenderer(W, H, FPS, plain_style(color="#00ff00"))
    img = r.render([s], 40)
    geo = shot_geometry(s, 40, FPS, r.style, r.scale)
    assert geo is not None
    for x, y in geo.points[5:-5:10]:
        px = img[int(round(y)), int(round(x))]
        assert px[3] > 200
        assert px[1] > 200 and px[0] < 30 and px[2] < 30
    # far away from the path: fully transparent
    assert img[5, 5, 3] == 0 and img[350, 630, 3] == 0


def test_glow_extends_alpha_beyond_core() -> None:
    s = shot()
    core = TracerRenderer(W, H, FPS, plain_style()).render([s], 70)
    glow = TracerRenderer(W, H, FPS, plain_style(glow_strength=1.5, glow_radius=10)).render([s], 70)
    assert (glow[..., 3] > 10).sum() > 2 * (core[..., 3] > 10).sum()


def test_taper_makes_line_thinner_at_the_end() -> None:
    m = np.zeros((200, 400), np.float32)
    pts = np.c_[np.linspace(20, 380, 100), np.full(100, 100.0)]
    widths = np.linspace(20, 4, 100)
    draw_stroke_mask(m, pts, widths)
    left = (m[:, 60] > 0.5).sum()
    right = (m[:, 340] > 0.5).sum()
    assert left > 2.5 * right


def test_fade_out_after_landing() -> None:
    st = plain_style(hold_seconds=0.5, fade_out_seconds=1.0)
    r = TracerRenderer(W, H, FPS, st)
    s = shot()
    a_land = r.render([s], 70)[..., 3].max()
    a_hold = r.render([s], 70 + 10)[..., 3].max()
    a_mid = r.render([s], 70 + 15 + 15)[..., 3].max()  # half way through the fade
    a_gone = r.render([s], 70 + 15 + 31)[..., 3].max()
    assert a_land == a_hold == 255
    assert 100 < a_mid < 160
    assert a_gone == 0


def test_tail_mode_draws_only_recent_part() -> None:
    s = shot()
    full = TracerRenderer(W, H, FPS, plain_style(mode="full")).render([s], 60)
    tail = TracerRenderer(W, H, FPS, plain_style(mode="tail", tail_seconds=0.3)).render([s], 60)
    assert full[320, 105, 3] > 200  # beginning of the path is still visible
    assert tail[320, 105, 3] == 0
    assert 0 < (tail[..., 3] > 0).sum() < (full[..., 3] > 0).sum()


def test_occlusion_cuts_tracer() -> None:
    s = shot()
    s.occlude = True
    occ = np.zeros((H, W), np.float32)
    occ[:, :250] = 1.0
    img = TracerRenderer(W, H, FPS, plain_style()).render([s], 70, occlusion=occ)
    assert img[:, :250, 3].max() == 0
    assert img[:, 260:, 3].max() == 255


def test_style_roundtrip_and_scaling() -> None:
    st = TracerStyle(color="#123456", shadow=True, shadow_offset=(1.0, 2.0))
    assert TracerStyle.from_dict(st.to_dict()) == st
    assert st.scale_for(3840, 2160) == pytest.approx(2.0)
    assert st.scale_for(1080, 1920) == pytest.approx(1.0)


def test_composite_over() -> None:
    bg = np.full((2, 2, 3), 100, np.uint8)
    ov = np.zeros((2, 2, 4), np.uint8)
    ov[0, 0] = (255, 0, 0, 255)
    ov[1, 1] = (255, 0, 0, 128)
    out = composite_over(bg, ov)
    assert tuple(out[0, 0]) == (0, 0, 255)
    assert tuple(out[0, 1]) == (100, 100, 100)
    assert out[1, 1, 2] == pytest.approx(178, abs=1)
