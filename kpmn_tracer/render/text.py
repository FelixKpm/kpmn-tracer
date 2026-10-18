"""Animated text labels per shot (club, carry, ...), rendered with Qt into the RGBA overlay.

The label appears ``delay_s`` after its trigger (impact or landing), fades in
while sliding up a little, follows the camera (anchored to the apex/landing
point in the reference frame) or sits in a screen corner, and fades out
together with the tracer.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from typing import Any

import numpy as np

from kpmn_tracer.render.style import REFERENCE_SHORT_SIDE, TracerStyle
from kpmn_tracer.trace.model import AnchorKind, Shot

POSITIONS = ("apex", "land", "top_left", "top_right", "bottom_left", "bottom_right")


# a font every installation of the platform has (Qt substitutes a similar one otherwise)
DEFAULT_FONT = {"win32": "Segoe UI", "darwin": "Helvetica Neue"}.get(sys.platform, "DejaVu Sans")


@dataclass
class TextStyle:
    font_family: str = DEFAULT_FONT
    size: float = 44.0  # px @1080
    bold: bool = True
    color: str = "#ffffff"
    box: bool = True
    box_color: str = "#000000"
    box_opacity: float = 0.55
    position: str = "apex"  # one of POSITIONS
    offset: tuple[float, float] = (0.0, -60.0)  # px @1080, relative to the anchor point
    trigger: str = "impact"  # "impact" | "land"
    delay_s: float = 0.6
    anim_s: float = 0.4
    slide_px: float = 18.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["offset"] = list(self.offset)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TextStyle:
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in d.items() if k in names}
        if "offset" in kw:
            kw["offset"] = tuple(kw["offset"])
        return cls(**kw)


_qt_lock = threading.Lock()


def _font_dir_for_offscreen() -> None:
    """The offscreen Qt platform on Windows does not see system fonts unless told where they are.

    (macOS uses CoreText and Linux fontconfig in offscreen mode as well, no hint needed.)
    """
    if (sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") == "offscreen"
            and "QT_QPA_FONTDIR" not in os.environ):
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        if os.path.isdir(fonts):
            os.environ["QT_QPA_FONTDIR"] = fonts


def ensure_qt() -> None:
    """Text needs a Q(Gui)Application for fonts; create an offscreen one when running headless."""
    from PySide6.QtGui import QGuiApplication

    with _qt_lock:
        if QGuiApplication.instance() is None:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            _font_dir_for_offscreen()
            QGuiApplication.instance() or QGuiApplication(["kpmn-tracer"])  # noqa: B018


@lru_cache(maxsize=64)
def _label_image(text: str, family: str, size_px: int, bold: bool, color: str, box: bool,
                 box_color: str, box_opacity: float) -> np.ndarray:
    """Straight-alpha RGBA float32 image of the label."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath

    font = QFont(family)
    font.setPixelSize(max(6, size_px))
    font.setBold(bold)
    fm = QFontMetricsF(font)
    lines = text.split("\n")
    tw = max(fm.horizontalAdvance(line) for line in lines)
    th = fm.height() * len(lines)
    pad_x, pad_y = size_px * 0.45, size_px * 0.22
    W, H = int(np.ceil(tw + 2 * pad_x)) + 2, int(np.ceil(th + 2 * pad_y)) + 2
    img = QImage(W, H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if box:
        bc = QColor(box_color)
        bc.setAlphaF(box_opacity)
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, W - 2, H - 2), H * 0.3, H * 0.3)
        p.fillPath(path, bc)
    p.setFont(font)
    p.setPen(QColor(color))
    for i, line in enumerate(lines):
        r = QRectF(0, pad_y + i * fm.height(), W, fm.height())
        p.drawText(r, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter), line)
    p.end()
    ptr = img.constBits()
    arr = np.frombuffer(ptr, np.uint8, count=W * H * 4).reshape(H, W, 4).astype(np.float32) / 255.0
    bgra = arr.copy()
    a = bgra[..., 3:4]
    rgb = np.where(a > 1e-6, bgra[..., 2::-1] / np.maximum(a, 1e-6), 0.0)  # unpremultiply, BGRA -> RGB
    return np.dstack([np.clip(rgb, 0, 1), a[..., 0]]).astype(np.float32)


def blend_rgba(out: np.ndarray, src: np.ndarray, x: int, y: int, alpha: float) -> None:
    """Composite straight-alpha float RGBA ``src`` over uint8 RGBA ``out`` at (x, y)."""
    H, W = out.shape[:2]
    h, w = src.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1 or alpha <= 0:
        return
    s = src[y0 - y:y1 - y, x0 - x:x1 - x]
    d = out[y0:y1, x0:x1].astype(np.float32) / 255.0
    sa = s[..., 3:4] * alpha
    da = d[..., 3:4]
    oa = sa + da * (1 - sa)
    oc = (s[..., :3] * sa + d[..., :3] * da * (1 - sa)) / np.maximum(oa, 1e-6)
    out[y0:y1, x0:x1] = np.clip(np.dstack([oc, oa]) * 255 + 0.5, 0, 255).astype(np.uint8)


def text_alpha(shot: Shot, frame: int, fps: float, ts: TextStyle, tracer: TracerStyle) -> tuple[float, float]:
    """(opacity, animation progress 0..1) of the label at ``frame``."""
    dur = shot.flight_frames(fps)
    trig = shot.impact_frame + (dur if ts.trigger == "land" else 0)
    t = (frame - trig) / fps - ts.delay_s
    if t < 0:
        return 0.0, 0.0
    prog = min(1.0, t / max(ts.anim_s, 1e-6))
    after = (frame - shot.impact_frame - dur) / fps
    fade = 1.0
    if after > tracer.hold_seconds:
        fade = max(0.0, 1.0 - (after - tracer.hold_seconds) / max(tracer.fade_out_seconds, 1e-6))
    ease = 1 - (1 - prog) ** 3
    return ease * fade * tracer.opacity, ease


def draw_text(out: np.ndarray, shot: Shot, frame: int, fps: float, ts: TextStyle, tracer: TracerStyle) -> None:
    if not shot.text.strip() or not shot.is_complete():
        return
    alpha, prog = text_alpha(shot, frame, fps, ts, tracer)
    if alpha <= 0:
        return
    ensure_qt()
    H, W = out.shape[:2]
    k = min(W, H) / REFERENCE_SHORT_SIDE
    label = _label_image(shot.text, ts.font_family, int(round(ts.size * k)), ts.bold, ts.color,
                         ts.box, ts.box_color, ts.box_opacity)
    h, w = label.shape[:2]
    margin = 40 * k
    if ts.position in ("apex", "land"):
        a = shot.anchor(AnchorKind.APEX if ts.position == "apex" else AnchorKind.LAND) or shot.anchors[-1]
        p = shot.to_frame(np.array([[a.x, a.y]]), frame)[0]
        cx, cy = p[0] + ts.offset[0] * k, p[1] + ts.offset[1] * k
        x, y = cx - w / 2, cy - h / 2
    else:
        x = margin if ts.position.endswith("left") else W - w - margin
        y = margin if ts.position.startswith("top") else H - h - margin
    y += (1 - prog) * ts.slide_px * k
    x = float(np.clip(x, 0, max(0, W - w)))
    y = float(np.clip(y, 0, max(0, H - h)))
    blend_rgba(out, label, int(round(x)), int(round(y)), alpha)

