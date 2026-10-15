"""GUI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from kpmn_tracer import __version__
from kpmn_tracer.logging_setup import setup_logging


def _log_file() -> Path:
    return Path.home() / ".kpmn_tracer" / "kpmn_tracer.log"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging(log_file=_log_file())
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("KPMN Tracer")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    from kpmn_tracer.gui.main_window import MainWindow
    from kpmn_tracer.gui.theme import apply_dark_palette

    apply_dark_palette(app)
    win = MainWindow()
    win.show()
    if len(argv) > 1 and Path(argv[1]).exists():
        win.open_path(Path(argv[1]))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
