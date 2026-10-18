"""Download FFmpeg (ffmpeg + ffprobe) for this platform into ``vendor/ffmpeg/bin``.

The app looks there first (see ``kpmn_tracer.io.ffmpeg_bin``), and the
PyInstaller build bundles that folder. Usage::

    python tools/fetch_ffmpeg.py

All builds are GPL builds with prores_ks, libx264, libx265 and zscale/zimg (HDR
tonemapping); ``kpmn-tracer selftest`` checks these features.

* Windows: BtbN "shared" build (ffmpeg.exe/ffprobe.exe share the libav* DLLs,
  about half the size of two static executables).
* macOS (Apple Silicon / Intel) and Linux (x86_64 / arm64): static release builds
  by Martin Riedl, pinned to one version and verified against their SHA-256.
"""

from __future__ import annotations

import hashlib
import io
import logging
import platform
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("fetch_ffmpeg")

TARGET = Path(__file__).resolve().parent.parent / "vendor" / "ffmpeg" / "bin"

WIN_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-n8.1-latest-win64-gpl-shared-8.1.zip"
)
RIEDL = "https://ffmpeg.martin-riedl.de/download"
RIEDL_BUILDS = {  # (system, machine) -> release folder (FFmpeg 9.0.2)
    ("darwin", "arm64"): "macos/arm64/1789931890_9.0.2",
    ("darwin", "x86_64"): "macos/amd64/1789931006_9.0.2",
    ("linux", "x86_64"): "linux/amd64/1789931100_9.0.2",
    ("linux", "aarch64"): "linux/arm64/1789931697_9.0.2",
}
LICENSE_NOTE = """FFmpeg {version} - static build by Martin Riedl ({url})
Configured with --enable-gpl --enable-version3: licensed under the GNU General Public License v3.
FFmpeg source code: https://ffmpeg.org/download.html  -  build scripts: https://git.martin-riedl.de/ffmpeg/build-script
"""


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "KPMN-Tracer-build"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - fixed https URLs
        return resp.read()


def _machine() -> str:
    m = platform.machine().lower()
    return {"amd64": "x86_64", "arm64": "arm64" if sys.platform == "darwin" else "aarch64"}.get(m, m)


def fetch_windows() -> None:
    log.info("Downloading %s ...", WIN_URL)
    data = _get(WIN_URL)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            name = Path(member).name
            if name in ("ffmpeg.exe", "ffprobe.exe") or (Path(member).parent.name == "bin"
                                                         and name.lower().endswith(".dll")):
                with zf.open(member) as src, open(TARGET / name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                log.info("Extracted %s", name)
            elif name == "LICENSE.txt":
                with zf.open(member) as src, open(TARGET.parent / "LICENSE.txt", "wb") as dst:
                    shutil.copyfileobj(src, dst)


def fetch_riedl(folder: str) -> None:
    for tool in ("ffmpeg", "ffprobe"):
        url = f"{RIEDL}/{folder}/{tool}.zip"
        log.info("Downloading %s ...", url)
        data = _get(url)
        want = _get(url + ".sha256").decode().split()[0].lower()
        got = hashlib.sha256(data).hexdigest()
        if got != want:
            raise RuntimeError(f"SHA-256 mismatch for {url}: {got} != {want}")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            member = next(m for m in zf.namelist() if Path(m).name == tool)
            out = TARGET / tool
            with zf.open(member) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)
        out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        log.info("Extracted %s", tool)
    version = folder.rsplit("_", 1)[-1]
    (TARGET.parent / "LICENSE.txt").write_text(
        LICENSE_NOTE.format(version=version, url=f"{RIEDL}/{folder}/"), encoding="utf-8")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    exe = ".exe" if sys.platform == "win32" else ""
    wanted = [f"ffmpeg{exe}", f"ffprobe{exe}"]
    if all((TARGET / n).exists() for n in wanted):
        log.info("FFmpeg already present in %s", TARGET)
        return 0
    TARGET.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        fetch_windows()
    else:
        key = (sys.platform if sys.platform == "darwin" else "linux", _machine())
        folder = RIEDL_BUILDS.get(key)
        if folder is None:
            log.error("No FFmpeg build known for %s/%s - install ffmpeg yourself or set KPMN_FFMPEG_DIR.", *key)
            return 1
        fetch_riedl(folder)
    missing = [n for n in wanted if not (TARGET / n).exists()]
    if missing:
        log.error("Missing after extraction: %s", missing)
        return 1
    log.info("Done: %s", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
