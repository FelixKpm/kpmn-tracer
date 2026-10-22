"""Scorecard Studio: scorecards for social media posts (separate from the shot tracer).

The studio is a self-contained HTML page (``studio.html`` + ``themes.js``) that runs
in the default browser, so it can also be used on its own (or hosted as a static
page). Designs are data: the built-in ones live in ``themes.js``, own designs are
made in the studio and exported/imported as JSON.
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
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


def launcher(lang: str, folder: Path | None = None) -> Path:
    """Small page that forwards to the studio with ``#lang=..``.

    Windows opens file URLs through the shell, which drops the ``#...`` part, so the
    language is handed over by a redirect from a plain file instead.
    """
    target = studio_path().resolve().as_uri() + f"#lang={lang}"
    out = (folder or Path(tempfile.gettempdir())) / f"kpmn_scorecard_studio_{lang}.html"
    out.write_text(
        f'<!doctype html><meta charset="utf-8"><title>Scorecard Studio</title>'
        f'<meta http-equiv="refresh" content="0;url={target}">'
        f"<script>location.replace({json.dumps(target)});</script>",
        encoding="utf-8")
    return out


def open_studio(lang: str | None = None) -> bool:
    """Open the studio in the default browser, in ``lang`` (default: the UI language)."""
    from kpmn_tracer.i18n import language

    p = studio_path()
    if not p.exists():
        log.error("Scorecard Studio not found: %s", p)
        return False
    log.info("Opening Scorecard Studio: %s", p)
    try:
        url = launcher(lang or language()).as_uri()
    except OSError as exc:  # no writable temp folder: open it without the language hint
        log.warning("Scorecard Studio launcher not written: %s", exc)
        url = p.resolve().as_uri()
    return webbrowser.open(url)
