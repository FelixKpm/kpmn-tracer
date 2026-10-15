"""Build the Windows folder distribution and zip it.

    python tools/build_windows.py            # -> dist/KPMN-Tracer/  and  dist/KPMN-Tracer-<version>-win64.zip

Steps: fetch FFmpeg + models if missing, draw the icon if missing, run PyInstaller
with packaging/kpmn_tracer.spec, copy FFmpeg into the bundle, run the self test
with the built CLI, zip.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> int:
    py = sys.executable
    if not (ROOT / "vendor" / "ffmpeg" / "bin" / "ffprobe.exe").exists():
        run([py, "tools/fetch_ffmpeg.py"])
    if not (ROOT / "vendor" / "models" / "selfie_multiclass_256x256.tflite").exists():
        run([py, "tools/fetch_models.py"])
    if not (ROOT / "assets" / "kpmn_tracer.ico").exists():
        run([py, "tools/make_icon.py"])
    run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
         "--workpath", str(ROOT / "build"), "packaging/kpmn_tracer.spec"])
    app = DIST / "KPMN-Tracer"
    ff = app / "_internal" / "ffmpeg"
    ff.mkdir(parents=True, exist_ok=True)
    for f in (ROOT / "vendor" / "ffmpeg" / "bin").iterdir():
        shutil.copy2(f, ff / f.name)
    shutil.copy2(ROOT / "vendor" / "ffmpeg" / "LICENSE.txt", ff / "LICENSE.txt")
    run([str(app / "kpmn-tracer.exe"), "selftest"])
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    print("+ GUI smoke test", flush=True)
    subprocess.run([str(app / "KPMN Tracer.exe"), "--smoke-test"], check=True, cwd=ROOT, env=env, timeout=120)
    from kpmn_tracer import __version__

    zip_base = DIST / f"KPMN-Tracer-{__version__}-win64"
    archive = shutil.make_archive(str(zip_base), "zip", DIST, "KPMN-Tracer")
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file()) / 1e6
    print(f"Build OK: {app} ({size:.0f} MB) -> {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
