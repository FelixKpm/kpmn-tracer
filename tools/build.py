"""Build the distribution for the current platform and package it.

    python tools/build.py

Windows -> dist/KPMN-Tracer/                 + dist/KPMN-Tracer-<ver>-windows-x64.zip
macOS   -> dist/KPMN Tracer.app             + dist/KPMN-Tracer-<ver>-macos-<arm64|x64>.dmg
Linux   -> dist/KPMN-Tracer/                 + dist/KPMN-Tracer-<ver>-linux-<x64|arm64>.tar.gz

Steps: fetch FFmpeg + models if missing, draw the icon if missing, run PyInstaller
with packaging/kpmn_tracer.spec, (Windows) copy FFmpeg into the bundle, run the self
test with the built CLI and a GUI smoke test, package.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"


def run(cmd: list[str], **kw) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(m, m)


def layout() -> tuple[Path, Path, Path]:
    """(distributed folder/app, CLI executable, GUI executable)."""
    if IS_MAC:
        app = DIST / "KPMN Tracer.app"
        return app, app / "Contents" / "MacOS" / "kpmn-tracer", app / "Contents" / "MacOS" / "KPMN Tracer"
    app = DIST / "KPMN-Tracer"
    if IS_WIN:
        return app, app / "kpmn-tracer.exe", app / "KPMN Tracer.exe"
    return app, app / "kpmn-tracer", app / "kpmn-tracer-gui"


def package(app: Path, version: str) -> Path:
    if IS_WIN:
        return Path(shutil.make_archive(str(DIST / f"KPMN-Tracer-{version}-windows-{arch()}"), "zip",
                                        DIST, app.name))
    if IS_MAC:
        stage = DIST / "dmg"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        run(["ditto", str(app), str(stage / app.name)])  # keeps symlinks, permissions and signatures
        (stage / "Applications").symlink_to("/Applications")
        shutil.copy2(ROOT / "packaging" / "macos" / "LIESMICH.txt", stage / "LIESMICH.txt")
        out = DIST / f"KPMN-Tracer-{version}-macos-{arch()}.dmg"
        out.unlink(missing_ok=True)
        run(["hdiutil", "create", "-volname", "KPMN Tracer", "-srcfolder", str(stage), "-ov",
             "-format", "UDZO", str(out)])
        shutil.rmtree(stage, ignore_errors=True)
        return out
    for f in ("install.sh", "kpmn-tracer.desktop"):
        shutil.copy2(ROOT / "packaging" / "linux" / f, app / f)
    (app / "install.sh").chmod(0o755)
    shutil.copy2(ROOT / "assets" / "kpmn_tracer.png", app / "kpmn-tracer.png")
    return Path(shutil.make_archive(str(DIST / f"KPMN-Tracer-{version}-linux-{arch()}"), "gztar",
                                    DIST, app.name))


def main() -> int:
    py = sys.executable
    exe = ".exe" if IS_WIN else ""
    if not (ROOT / "vendor" / "ffmpeg" / "bin" / f"ffprobe{exe}").exists():
        run([py, "tools/fetch_ffmpeg.py"])
    if not (ROOT / "vendor" / "models" / "selfie_multiclass_256x256.tflite").exists():
        run([py, "tools/fetch_models.py"])
    if not (ROOT / "assets" / "kpmn_tracer.ico").exists() or not (ROOT / "assets" / "kpmn_tracer.png").exists():
        run([py, "tools/make_icon.py"])
    run([py, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST),
         "--workpath", str(ROOT / "build"), "packaging/kpmn_tracer.spec"])
    app, cli, gui = layout()
    if IS_WIN:
        ff = app / "_internal" / "ffmpeg"
        ff.mkdir(parents=True, exist_ok=True)
        for f in (ROOT / "vendor" / "ffmpeg" / "bin").iterdir():
            shutil.copy2(f, ff / f.name)
        shutil.copy2(ROOT / "vendor" / "ffmpeg" / "LICENSE.txt", ff / "LICENSE.txt")
    run([str(cli), "selftest"])
    print("+ GUI smoke test", flush=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    subprocess.run([str(gui), "--smoke-test"], check=True, cwd=ROOT, env=env, timeout=180)
    from kpmn_tracer import __version__

    archive = package(app, __version__)
    size = sum(f.stat().st_size for f in app.rglob("*") if f.is_file() and not f.is_symlink()) / 1e6
    print(f"Build OK: {app} ({size:.0f} MB) -> {archive}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:  # CI: tell the workflow which file to upload
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"archive={archive}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
