"""Tracer rendering into an RGBA (straight alpha) overlay frame.

Work happens only inside the bounding box of the tracer (+ glow margin), so
4K overlays stay cheap. Layers, back to front: shadow, glow, core, highlight.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from kpmn_tracer.render.style import TracerStyle, hex_to_rgb
from kpmn_tracer.render.text import TextStyle, draw_text
from kpmn_tracer.trace.model import Shot

log = logging.getLogger(__name__)

_SHIFT = 4  # sub-pixel bits for cv2 drawing
_SCALE = 1 << _SHIFT
_TAIL_CHUNKS = 12


@dataclass
class StrokeGeometry:
    points: np.ndarray  # (n, 2) frame coordinates
    widths: np.ndarray  # (n,) pixels
    ramp: np.ndarray  # (n,) 0..1 alpha along the stroke (tail fade)
    alpha: float  # global alpha (fade-out)
    head: np.ndarray | None  # ball position while in flight
    occlude: bool


def shot_geometry(shot: Shot, frame: int, fps: float, style: TracerStyle, scale: float) -> StrokeGeometry | None:
    """What to draw for ``shot`` at ``frame`` (None = nothing visible)."""
    path = shot.path()
    if path is None or frame < shot.impact_frame:
        return None
    dur = shot.flight_frames(fps)
    tau = (frame - shot.impact_frame) / dur
    after = (frame - shot.impact_frame - dur) / fps  # seconds after landing
    alpha = style.opacity
    if after > 0:
        if after > style.hold_seconds + style.fade_out_seconds:
            return None
        if after > style.hold_seconds:
            alpha *= 1.0 - (after - style.hold_seconds) / max(style.fade_out_seconds, 1e-6)
    if alpha <= 0:
        return None
    u_head = float(shot.u_at_tau(min(tau, 1.0), path, dur)[0])
    u_tail = 0.0
    if style.mode == "tail":
        tail_tau = tau - style.tail_seconds * fps / dur
        if tail_tau >= 1.0:
            return None
        u_tail = float(shot.u_at_tau(max(tail_tau, 0.0), path, dur)[0])
    if u_head - u_tail < 1e-4:
        if tau >= 1.0:
            return None
        u_head = min(1.0, u_tail + 1e-4)
    count = max(8, int(500 * (u_head - u_tail)))
    us = np.linspace(u_tail, u_head, count)
    pts = shot.to_frame(path.evaluate(us), frame)
    w0 = style.width * scale
    widths = w0 * (1.0 - style.taper * us)
    widths = np.maximum(widths, 0.6)
    if style.mode == "tail":
        ramp = np.linspace(0.0, 1.0, count) ** 0.8
    else:
        ramp = np.ones(count)
    head = pts[-1] if (style.head_dot and tau < 1.0) else None
    return StrokeGeometry(pts, widths, ramp, alpha, head, shot.occlude)


def _stroke_polygon(pts: np.ndarray, widths: np.ndarray) -> np.ndarray:
    d = np.gradient(pts, axis=0)
    norm = np.linalg.norm(d, axis=1, keepdims=True)
    d = d / np.maximum(norm, 1e-9)
    n = np.c_[-d[:, 1], d[:, 0]]
    left = pts + n * (widths[:, None] / 2)
    right = pts - n * (widths[:, None] / 2)
    return np.vstack([left, right[::-1]])


def draw_stroke_mask(mask: np.ndarray, pts: np.ndarray, widths: np.ndarray, value: float = 1.0) -> None:
    """Rasterise a variable-width anti-aliased stroke into float ``mask`` (max-blend)."""
    if len(pts) < 2:
        return
    tmp = np.zeros(mask.shape, np.uint8)
    poly = np.round(_stroke_polygon(pts, widths) * _SCALE).astype(np.int32)
    cv2.fillPoly(tmp, [poly], 255, cv2.LINE_AA, _SHIFT)
    for p, w in ((pts[0], widths[0]), (pts[-1], widths[-1])):
        c = tuple(int(v) for v in np.round(p * _SCALE))
        cv2.circle(tmp, c, max(1, int(round(w / 2 * _SCALE))), 255, -1, cv2.LINE_AA, _SHIFT)
    np.maximum(mask, tmp.astype(np.float32) * (value / 255.0), out=mask)


def _draw_dot(mask: np.ndarray, p: np.ndarray, r: float) -> None:
    tmp = np.zeros(mask.shape, np.uint8)
    c = tuple(int(v) for v in np.round(p * _SCALE))
    cv2.circle(tmp, c, max(1, int(round(r * _SCALE))), 255, -1, cv2.LINE_AA, _SHIFT)
    np.maximum(mask, tmp.astype(np.float32) / 255.0, out=mask)


class TracerRenderer:
    def __init__(self, width: int, height: int, fps: float, style: TracerStyle,
                 text_style: TextStyle | None = None) -> None:
        self.width, self.height, self.fps = width, height, fps
        self.style = style
        self.text_style = text_style
        self.scale = style.scale_for(width, height)

    def margin(self) -> int:
        s = self.style
        m = s.width * self.scale + 3.5 * s.glow_radius * self.scale + 4
        if s.shadow:
            m += max(abs(s.shadow_offset[0]), abs(s.shadow_offset[1])) * self.scale + 3 * s.shadow_blur * self.scale
        return int(np.ceil(m))

    def render(
        self,
        shots: list[Shot],
        frame: int,
        occlusion: np.ndarray | None = None,
        out: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return RGBA uint8 (h, w, 4), straight alpha. ``occlusion``: float person mask 0..1."""
        if out is None:
            out = np.zeros((self.height, self.width, 4), np.uint8)
        else:
            out[:] = 0
        for shot in shots:
            geo = shot_geometry(shot, frame, self.fps, self.style, self.scale)
            if geo is not None:
                self._draw(out, geo, occlusion)
        if self.text_style is not None:
            for shot in shots:
                if shot.text:
                    draw_text(out, shot, frame, self.fps, self.text_style, self.style)
        return out

    # ------------------------------------------------------------------ internals
    def _draw(self, out: np.ndarray, geo: StrokeGeometry, occlusion: np.ndarray | None) -> None:
        s, k = self.style, self.scale
        m = self.margin()
        x0 = int(np.floor(geo.points[:, 0].min())) - m
        y0 = int(np.floor(geo.points[:, 1].min())) - m
        x1 = int(np.ceil(geo.points[:, 0].max())) + m + 1
        y1 = int(np.ceil(geo.points[:, 1].max())) + m + 1
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, self.width), min(y1, self.height)
        if x0 >= x1 or y0 >= y1:
            return
        shape = (y1 - y0, x1 - x0)
        pts = geo.points - np.array([x0, y0], float)

        core = np.zeros(shape, np.float32)
        if np.all(geo.ramp >= 0.999):
            draw_stroke_mask(core, pts, geo.widths)
        else:
            bounds = np.linspace(0, len(pts) - 1, _TAIL_CHUNKS + 1).astype(int)
            for a, b in zip(bounds[:-1], bounds[1:]):
                if b > a:
                    draw_stroke_mask(core, pts[a:b + 1], geo.widths[a:b + 1], float(geo.ramp[b]))
        hi = np.zeros(shape, np.float32)
        if s.core_highlight > 0:
            draw_stroke_mask(hi, pts, geo.widths * 0.38)
            hi *= core * s.core_highlight
        if geo.head is not None:
            hp = geo.head - np.array([x0, y0], float)
            _draw_dot(core, hp, geo.widths[-1] * 0.9 + 1.0 * k)
            _draw_dot(hi, hp, geo.widths[-1] * 0.5 + 0.5 * k)

        glow = np.zeros(shape, np.float32)
        if s.glow_strength > 0 and s.glow_radius > 0:
            sig = s.glow_radius * k
            glow = cv2.GaussianBlur(core, (0, 0), sig) * s.glow_strength
            glow += cv2.GaussianBlur(core, (0, 0), sig * 0.35) * s.glow_strength * 0.5
            np.clip(glow, 0, 1, out=glow)
        shadow = np.zeros(shape, np.float32)
        if s.shadow:
            M = np.float32([[1, 0, s.shadow_offset[0] * k], [0, 1, s.shadow_offset[1] * k]])
            shadow = cv2.warpAffine(core, M, (shape[1], shape[0]))
            if s.shadow_blur > 0:
                shadow = cv2.GaussianBlur(shadow, (0, 0), s.shadow_blur * k)
            shadow *= s.shadow_opacity

        vis = geo.alpha
        if geo.occlude and occlusion is not None:
            vis = vis * (1.0 - occlusion[y0:y1, x0:x1].astype(np.float32))
        core_c = np.array(hex_to_rgb(s.color), np.float32)
        glow_c = np.array(hex_to_rgb(s.glow_color or s.color), np.float32)
        white = np.ones(3, np.float32)

        # premultiplied "over" compositing: shadow < glow < core < highlight
        a_s, a_g, a_c, a_h = shadow * vis, glow * vis, core * vis, hi * vis
        A = a_s
        C = np.zeros(shape + (3,), np.float32)
        for a, col in ((a_g, glow_c), (a_c, core_c), (a_h, white)):
            C = a[..., None] * col + (1 - a[..., None]) * C
            A = a + (1 - a) * A

        # composite over what is already in ``out`` (other shots)
        dst = out[y0:y1, x0:x1].astype(np.float32) / 255.0
        dA = dst[..., 3]
        dC = dst[..., :3] * dA[..., None]
        oA = A + (1 - A) * dA
        oC = C + (1 - A)[..., None] * dC
        rgb = np.where(oA[..., None] > 1e-6, oC / np.maximum(oA[..., None], 1e-6), 0)
        res = np.dstack([rgb, oA])
        out[y0:y1, x0:x1] = np.clip(res * 255.0 + 0.5, 0, 255).astype(np.uint8)


def composite_over(bgr: np.ndarray, rgba: np.ndarray) -> np.ndarray:
    """Blend an RGBA (straight) overlay over a BGR uint8 frame of the same size."""
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    fg = rgba[..., 2::-1].astype(np.float32)  # RGB -> BGR
    out = bgr.astype(np.float32) * (1 - a) + fg * a
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)
