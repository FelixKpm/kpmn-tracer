"""Dark Fusion palette (video tools read better on dark UI)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_dark_palette(app: QApplication) -> None:
    p = QPalette()
    base, alt, text = QColor(40, 40, 44), QColor(52, 52, 58), QColor(225, 225, 225)
    p.setColor(QPalette.ColorRole.Window, base)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, QColor(30, 30, 33))
    p.setColor(QPalette.ColorRole.AlternateBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipBase, alt)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, alt)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.Highlight, QColor(220, 60, 50))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ColorRole.Link, QColor(255, 120, 100))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(120, 120, 120))
    app.setPalette(p)
