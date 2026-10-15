"""Minimal labelling tool for ball tiles (YOLO format, one class "ball").

    python tools/label_balls.py dataset_dir/images/train

Left click     set the ball centre (box keeps its size)
Mouse wheel    box size
Right click /  remove the label (tile without ball)
  Delete
N / Space      next tile          P / Backspace   previous tile
S              save (also automatic when changing tiles)

Labels live in the parallel ``labels`` folder (``images/x/a.jpg`` -> ``labels/x/a.txt``).
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QApplication, QWidget


def label_path(img: Path) -> Path:
    parts = list(img.parts)
    i = len(parts) - 1 - parts[::-1].index("images")
    parts[i] = "labels"
    return Path(*parts).with_suffix(".txt")


def read_label(p: Path) -> tuple[float, float, float] | None:
    """(cx, cy, size) normalised, or None."""
    if not p.exists():
        return None
    line = p.read_text().strip().splitlines()
    if not line:
        return None
    _, cx, cy, w, h = map(float, line[0].split())
    return cx, cy, (w + h) / 2


def write_label(p: Path, lab: tuple[float, float, float] | None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("" if lab is None else f"0 {lab[0]:.6f} {lab[1]:.6f} {lab[2]:.6f} {lab[2]:.6f}\n")


class Labeler(QWidget):
    def __init__(self, images: list[Path]) -> None:
        super().__init__()
        self.images = images
        self.i = 0
        self.label: tuple[float, float, float] | None = None
        self.img = QImage()
        self.resize(900, 900)
        self.load()

    def load(self) -> None:
        self.img = QImage(str(self.images[self.i]))
        self.label = read_label(label_path(self.images[self.i]))
        self.setWindowTitle(f"{self.i + 1}/{len(self.images)}  {self.images[self.i].name}")
        self.update()

    def save(self) -> None:
        write_label(label_path(self.images[self.i]), self.label)

    def go(self, d: int) -> None:
        self.save()
        self.i = max(0, min(len(self.images) - 1, self.i + d))
        self.load()

    def _rect(self) -> QRectF:
        s = min(self.width(), self.height())
        return QRectF((self.width() - s) / 2, (self.height() - s) / 2, s, s)

    def paintEvent(self, _e: object) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        r = self._rect()
        p.drawImage(r, self.img)
        if self.label is not None:
            cx, cy, s = self.label
            p.setPen(QPen(QColor(0, 255, 0), 2))
            p.drawRect(QRectF(r.x() + (cx - s / 2) * r.width(), r.y() + (cy - s / 2) * r.height(),
                              s * r.width(), s * r.height()))
        p.setPen(QColor(220, 220, 220))
        p.drawText(10, 20, "Klick=Ball  Rad=Größe  Rechtsklick/Entf=kein Ball  N/P=weiter/zurück")

    def mousePressEvent(self, e: QMouseEvent) -> None:  # noqa: N802
        r = self._rect()
        if e.button() == Qt.MouseButton.RightButton:
            self.label = None
        else:
            pos: QPointF = e.position()
            size = self.label[2] if self.label else 0.04
            self.label = ((pos.x() - r.x()) / r.width(), (pos.y() - r.y()) / r.height(), size)
        self.update()

    def wheelEvent(self, e: QWheelEvent) -> None:  # noqa: N802
        if self.label:
            f = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
            self.label = (self.label[0], self.label[1], min(0.9, max(0.005, self.label[2] * f)))
            self.update()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_N, Qt.Key.Key_Space, Qt.Key.Key_Right):
            self.go(1)
        elif k in (Qt.Key.Key_P, Qt.Key.Key_Backspace, Qt.Key.Key_Left):
            self.go(-1)
        elif k == Qt.Key.Key_Delete:
            self.label = None
            self.update()
        elif k == Qt.Key.Key_S:
            self.save()

    def closeEvent(self, e) -> None:  # noqa: N802
        self.save()
        e.accept()


def main() -> int:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    images = sorted(p for p in folder.rglob("*") if p.suffix.lower() in (".jpg", ".png"))
    if not images:
        print("no images found")
        return 1
    app = QApplication(sys.argv)
    w = Labeler(images)
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
