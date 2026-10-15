"""Timeline / scrubber with markers (impacts, landing, keyframes) and bad-tracking ranges."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QSizePolicy, QWidget


@dataclass
class Marker:
    frame: float
    color: QColor
    shape: str = "line"  # "line" | "diamond" | "triangle"
    tooltip: str = ""


class Timeline(QWidget):
    frameChanged = Signal(int)
    markerClicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(54)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.count = 1
        self.current = 0
        self.markers: list[Marker] = []
        self.bad_frames: set[int] = set()
        self.ranges: list[tuple[int, int, QColor]] = []  # shot spans
        self._dragging = False

    def set_count(self, n: int) -> None:
        self.count = max(1, n)
        self.update()

    def set_current(self, i: int) -> None:
        self.current = i
        self.update()

    def _x(self, frame: float) -> float:
        return 8 + (self.width() - 16) * frame / max(1, self.count - 1)

    def _frame(self, x: float) -> int:
        f = (x - 8) / max(1, self.width() - 16) * (self.count - 1)
        return int(round(min(max(f, 0), self.count - 1)))

    def paintEvent(self, _e: object) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        p.fillRect(self.rect(), QColor(36, 36, 40))
        bar = QRectF(8, 18, self.width() - 16, h - 30)
        p.fillRect(bar, QColor(55, 55, 62))
        for a, b, col in self.ranges:
            p.fillRect(QRectF(self._x(a), bar.top(), max(2.0, self._x(b) - self._x(a)), bar.height()), col)
        if self.bad_frames:
            red = QColor(220, 40, 40, 200)
            w = max(1.5, (self.width() - 16) / max(1, self.count))
            for f in self.bad_frames:
                p.fillRect(QRectF(self._x(f) - w / 2, bar.bottom() - 6, w, 6), red)
        # ticks every second-ish
        p.setPen(QColor(110, 110, 120))
        step = max(1, self.count // 20)
        for f in range(0, self.count, step):
            p.drawLine(QPointF(self._x(f), bar.bottom()), QPointF(self._x(f), bar.bottom() + 4))
        for m in self.markers:
            x = self._x(m.frame)
            p.setPen(QPen(m.color, 2))
            p.setBrush(m.color)
            if m.shape == "diamond":
                y = bar.center().y()
                p.drawPolygon(QPolygonF([QPointF(x, y - 5), QPointF(x + 5, y), QPointF(x, y + 5), QPointF(x - 5, y)]))
            elif m.shape == "triangle":
                p.drawPolygon(QPolygonF([QPointF(x - 5, 4), QPointF(x + 5, 4), QPointF(x, 13)]))
            else:
                p.drawLine(QPointF(x, bar.top()), QPointF(x, bar.bottom()))
        x = self._x(self.current)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(x, 2), QPointF(x, h - 2))
        p.setPen(QColor(220, 220, 220))
        p.drawText(QRectF(8, h - 13, self.width() - 16, 12), Qt.AlignmentFlag.AlignRight,
                   f"{self.current} / {self.count - 1}")

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            if e.position().y() < 16:
                for m in self.markers:
                    if m.shape == "triangle" and abs(self._x(m.frame) - e.position().x()) < 7:
                        self.markerClicked.emit(m)
                        return
            self._dragging = True
            self.frameChanged.emit(self._frame(e.position().x()))

    def mouseMoveEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        if self._dragging:
            self.frameChanged.emit(self._frame(e.position().x()))
        tip = ""
        for m in self.markers:
            if m.tooltip and abs(self._x(m.frame) - e.position().x()) < 6:
                tip = m.tooltip
        self.setToolTip(tip)

    def mouseReleaseEvent(self, _e: QMouseEvent) -> None:  # noqa: N802
        self._dragging = False

    def wheelEvent(self, e: QWheelEvent) -> None:  # noqa: N802
        step = 1 if e.angleDelta().y() < 0 else -1
        self.frameChanged.emit(int(min(max(self.current + step, 0), self.count - 1)))
