"""Video canvas: shows a frame, zoom/pan, draggable anchor handles."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from kpmn_tracer.gui.keys import native
from kpmn_tracer.i18n import tr

HANDLE_RADIUS = 7.0


@dataclass
class Handle:
    key: str
    x: float  # image (proxy) pixel coordinates
    y: float
    color: QColor
    label: str = ""


class VideoView(QWidget):
    clicked = Signal(float, float)  # image coordinates
    handleMoved = Signal(str, float, float)
    handleReleased = Signal(str)
    handleSelected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._img: QImage | None = None
        self._buf: np.ndarray | None = None
        self._zoom = 1.0
        self._pan = QPointF(0, 0)
        self._handles: list[Handle] = []
        self._drag_key: str | None = None
        self._pan_start: QPointF | None = None
        self._pan_origin = QPointF(0, 0)
        self.selected: str | None = None
        self.placing = False  # crosshair cursor when a point tool is active
        self.info_text = ""

    # ------------------------------------------------------------ content
    def set_frame(self, bgr: np.ndarray) -> None:
        rgb = np.ascontiguousarray(bgr[..., ::-1])
        self._buf = rgb  # keep memory alive for the QImage
        h, w = rgb.shape[:2]
        self._img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.update()

    def set_handles(self, handles: list[Handle]) -> None:
        self._handles = handles
        self.update()

    def image_size(self) -> tuple[int, int]:
        return (self._img.width(), self._img.height()) if self._img else (1, 1)

    def reset_view(self) -> None:
        self._zoom, self._pan = 1.0, QPointF(0, 0)
        self.update()

    def set_placing(self, on: bool) -> None:
        self.placing = on
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------ transforms
    def _base_scale(self) -> float:
        w, h = self.image_size()
        return min(self.width() / w, self.height() / h)

    def _scale(self) -> float:
        return self._base_scale() * self._zoom

    def _origin(self) -> QPointF:
        w, h = self.image_size()
        s = self._scale()
        return QPointF((self.width() - w * s) / 2, (self.height() - h * s) / 2) + self._pan

    def to_widget(self, x: float, y: float) -> QPointF:
        o, s = self._origin(), self._scale()
        return QPointF(o.x() + x * s, o.y() + y * s)

    def to_image(self, p: QPointF) -> tuple[float, float]:
        o, s = self._origin(), self._scale()
        return ((p.x() - o.x()) / s, (p.y() - o.y()) / s)

    # ------------------------------------------------------------ painting
    def paintEvent(self, _event: object) -> None:  # noqa: N802 - Qt API
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(24, 24, 24))
        if self._img is None:
            p.setPen(QColor(160, 160, 160))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       native(tr("Clip öffnen (Strg+O) oder Datei hierher ziehen")))
            return
        w, h = self.image_size()
        o, s = self._origin(), self._scale()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._zoom < 2.5)
        p.drawImage(QRectF(o.x(), o.y(), w * s, h * s), self._img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for hd in self._handles:
            c = self.to_widget(hd.x, hd.y)
            sel = hd.key == self.selected
            p.setPen(QPen(QColor(0, 0, 0, 200), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, HANDLE_RADIUS + 1, HANDLE_RADIUS + 1)
            p.setPen(QPen(hd.color, 3 if sel else 2))
            p.drawEllipse(c, HANDLE_RADIUS, HANDLE_RADIUS)
            p.drawLine(c + QPointF(-3, 0), c + QPointF(3, 0))
            p.drawLine(c + QPointF(0, -3), c + QPointF(0, 3))
            if hd.label:
                p.setPen(QColor(0, 0, 0))
                p.drawText(c + QPointF(HANDLE_RADIUS + 4, -HANDLE_RADIUS + 1), hd.label)
                p.setPen(hd.color)
                p.drawText(c + QPointF(HANDLE_RADIUS + 3, -HANDLE_RADIUS), hd.label)
        if self.info_text:
            p.setPen(QColor(230, 230, 230))
            p.drawText(QRectF(8, 6, self.width() - 16, 20), Qt.AlignmentFlag.AlignLeft, self.info_text)
        if self._zoom != 1.0:
            p.setPen(QColor(200, 200, 200))
            p.drawText(QRectF(0, 6, self.width() - 8, 20), Qt.AlignmentFlag.AlignRight,
                       tr("Zoom {z:.1f}×  (Doppelklick = einpassen)", z=self._zoom))

    # ------------------------------------------------------------ interaction
    def _handle_at(self, pos: QPointF) -> str | None:
        best, best_d = None, HANDLE_RADIUS + 5
        for hd in self._handles:
            c = self.to_widget(hd.x, hd.y)
            d = ((c.x() - pos.x()) ** 2 + (c.y() - pos.y()) ** 2) ** 0.5
            if d < best_d:
                best, best_d = hd.key, d
        return best

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        pos = e.position()
        if e.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._pan_start, self._pan_origin = pos, QPointF(self._pan)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if e.button() != Qt.MouseButton.LeftButton or self._img is None:
            return
        key = None if self.placing else self._handle_at(pos)
        if key is not None:
            self._drag_key = key
            self.selected = key
            self.handleSelected.emit(key)
            self.update()
        else:
            x, y = self.to_image(pos)
            self.clicked.emit(x, y)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        pos = e.position()
        if self._pan_start is not None:
            self._pan = self._pan_origin + (pos - self._pan_start)
            self.update()
            return
        if self._drag_key is not None:
            x, y = self.to_image(pos)
            self.handleMoved.emit(self._drag_key, x, y)
            return
        if not self.placing:
            over = self._handle_at(pos) is not None
            self.setCursor(Qt.CursorShape.SizeAllCursor if over else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._pan_start is not None:
            self._pan_start = None
            self.set_placing(self.placing)
            return
        if self._drag_key is not None:
            key, self._drag_key = self._drag_key, None
            self.handleReleased.emit(key)

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton:
            self.reset_view()

    def wheelEvent(self, e: QWheelEvent) -> None:  # noqa: N802
        if self._img is None:
            return
        pos = e.position()
        before = self.to_image(pos)
        factor = 1.25 if e.angleDelta().y() > 0 else 1 / 1.25
        self._zoom = float(np.clip(self._zoom * factor, 1.0, 24.0))
        if self._zoom == 1.0:
            self._pan = QPointF(0, 0)
        else:
            after = self.to_widget(*before)
            self._pan += pos - after
        self.update()
