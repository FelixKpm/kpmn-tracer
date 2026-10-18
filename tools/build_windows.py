"""Kept for old instructions: the build script is now ``tools/build.py`` (all platforms)."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("build.py")), run_name="__main__")
