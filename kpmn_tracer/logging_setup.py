"""Central logging configuration."""

from __future__ import annotations

import logging
import os
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: int | str | None = None, log_file: Path | None = None) -> None:
    """Configure the root logger once. Level defaults to ``$KPMN_LOG_LEVEL`` or INFO."""
    if level is None:
        level = os.environ.get("KPMN_LOG_LEVEL", "INFO")
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, format=_FORMAT, handlers=handlers, force=True)
