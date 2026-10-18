"""GUI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from kpmn_tracer import __version__
from kpmn_tracer.logging_setup import setup_logging


def _asset(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "assets" / name


def _log_file() -> Path:
    from kpmn_tracer.project.presets import home

    return home() / "kpmn_tracer.log"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    smoke = "--smoke-test" in argv  # build check: open the window, quit after 1.5 s
    argv = [a for a in argv if a != "--smoke-test"]
    setup_logging(log_file=_log_file())
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("KPMN Tracer")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    from kpmn_tracer.gui.main_window import MainWindow
    from kpmn_tracer.gui.theme import apply_dark_palette

    apply_dark_palette(app)
    icon = _asset("kpmn_tracer.png")
    if icon.exists():
        from PySide6.QtGui import QIcon

        app.setWindowIcon(QIcon(str(icon)))
    win = MainWindow()
    win.show()
    if smoke:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(1500, app.quit)
    if len(argv) > 1 and Path(argv[1]).exists():
        win.open_path(Path(argv[1]))
    elif not smoke:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(500, win.maybe_start_tour)  # first start: guided tour
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
