"""Download a static FFmpeg build (ffmpeg + ffprobe) into ``vendor/ffmpeg/bin``.

The app looks there first (see ``kpmn_tracer.io.ffmpeg_bin``), and the
PyInstaller build bundles that folder. Usage::

    python tools/fetch_ffmpeg.py
"""

from __future__ import annotations

import io
import logging
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("fetch_ffmpeg")

# GPL build: contains prores_ks, libx264, libx265, zscale (HDR tonemapping).
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-n8.1-latest-win64-gpl-8.1.zip"
)
TARGET = Path(__file__).resolve().parent.parent / "vendor" / "ffmpeg" / "bin"
WANTED = ("ffmpeg.exe", "ffprobe.exe")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if all((TARGET / name).exists() for name in WANTED):
        log.info("FFmpeg already present in %s", TARGET)
        return 0
    if sys.platform != "win32":
        log.error("This helper only fetches Windows builds; install ffmpeg via your package manager.")
        return 1
    log.info("Downloading %s ...", FFMPEG_URL)
    with urllib.request.urlopen(FFMPEG_URL) as resp:  # noqa: S310 - fixed https URL
        data = resp.read()
    TARGET.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            name = Path(member).name
            if name in WANTED:
                with zf.open(member) as src, open(TARGET / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                log.info("Extracted %s", name)
            elif name == "LICENSE.txt":
                with zf.open(member) as src, open(TARGET.parent / "LICENSE.txt", "wb") as dst:
                    shutil.copyfileobj(src, dst)
    missing = [n for n in WANTED if not (TARGET / n).exists()]
    if missing:
        log.error("Missing after extraction: %s", missing)
        return 1
    log.info("Done: %s", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
