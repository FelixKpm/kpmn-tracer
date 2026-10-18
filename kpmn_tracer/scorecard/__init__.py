"""Scorecard Studio: scorecards for social media posts (separate from the shot tracer).

The studio is a self-contained HTML page (``studio.html`` + ``themes.js``) that runs
in the default browser, so it can also be used on its own (or hosted as a static
page). Designs are data: the built-in ones live in ``themes.js``, own designs are
made in the studio and exported/imported as JSON.
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path

log = logging.getLogger(__name__)


def studio_path() -> Path:
    """Location of ``studio.html`` (source tree or PyInstaller bundle)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / "scorecard" / "studio.html"
        if p.exists():
            return p
    return Path(__file__).with_name("studio.html")


def open_studio() -> bool:
    p = studio_path()
    if not p.exists():
        log.error("Scorecard Studio not found: %s", p)
        return False
    log.info("Opening Scorecard Studio: %s", p)
    return webbrowser.open(p.resolve().as_uri())
