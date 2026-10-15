"""Draw the application icon (tracer arc over a green) and write assets/kpmn_tracer.ico + .png."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QRadialGradient  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "assets"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 256.0
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    grad = QRadialGradient(QPointF(128 * s, 70 * s), 220 * s)
    grad.setColorAt(0, QColor(40, 60, 90))
    grad.setColorAt(1, QColor(14, 18, 28))
    p.fillPath(bg, grad)
    p.setClipPath(bg)
    p.fillRect(QRectF(0, 178 * s, 256 * s, 80 * s), QColor(46, 120, 62))
    arc = QPainterPath(QPointF(62 * s, 192 * s))
    arc.cubicTo(QPointF(90 * s, 40 * s), QPointF(170 * s, 30 * s), QPointF(206 * s, 120 * s))
    for width, color in ((26, QColor(255, 60, 50, 70)), (14, QColor(255, 60, 50, 150)), (7, QColor(255, 70, 60)),
                         (2.5, QColor(255, 235, 230))):
        p.setPen(QPen(color, width * s, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawPath(arc)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    p.drawEllipse(QPointF(206 * s, 120 * s), 9 * s, 9 * s)
    p.end()
    return img


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    OUT.mkdir(exist_ok=True)
    draw(256).save(str(OUT / "kpmn_tracer.png"))
    draw(256).save(str(OUT / "kpmn_tracer.ico"))
    print(OUT / "kpmn_tracer.ico")


if __name__ == "__main__":
    main()
