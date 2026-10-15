"""Locate the ffmpeg / ffprobe executables.

Search order:
1. ``$KPMN_FFMPEG_DIR``
2. ``ffmpeg/`` next to the frozen executable (PyInstaller build)
3. ``vendor/ffmpeg/bin`` in the repository (``tools/fetch_ffmpeg.py``)
4. ``PATH``
5. ``imageio-ffmpeg`` (only provides ffmpeg, not ffprobe)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_EXE = ".exe" if os.name == "nt" else ""
_REPO_VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "ffmpeg" / "bin"

# Hide console windows of child processes when running as a GUI app on Windows.
SUBPROCESS_FLAGS: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegNotFoundError(RuntimeError):
    pass


def _candidate_dirs() -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("KPMN_FFMPEG_DIR")
    if env:
        dirs.append(Path(env))
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        dirs.append(base / "ffmpeg")
    dirs.append(_REPO_VENDOR)
    return dirs


@lru_cache(maxsize=None)
def find_tool(name: str) -> str:
    """Return the path of ``ffmpeg`` or ``ffprobe``."""
    for d in _candidate_dirs():
        p = d / f"{name}{_EXE}"
        if p.is_file():
            log.debug("Using %s from %s", name, p)
            return str(p)
    on_path = shutil.which(name)
    if on_path:
        return on_path
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # pragma: no cover - depends on environment
            pass
    raise FFmpegNotFoundError(
        f"{name} not found. Run 'python tools/fetch_ffmpeg.py' or set KPMN_FFMPEG_DIR."
    )


def ffmpeg() -> str:
    return find_tool("ffmpeg")


def ffprobe() -> str:
    return find_tool("ffprobe")
