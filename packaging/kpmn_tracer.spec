# PyInstaller spec: one folder, two executables (GUI without console, CLI with console).
# Windows: KPMN-Tracer/"KPMN Tracer.exe" + kpmn-tracer.exe
# macOS:   "KPMN Tracer.app" (GUI; the CLI is Contents/MacOS/kpmn-tracer)
# Linux:   KPMN-Tracer/kpmn-tracer-gui + kpmn-tracer
# Build with:  python tools/build.py
# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
VENDOR = ROOT / "vendor"
IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
sys.path.insert(0, str(ROOT))
from kpmn_tracer import __version__  # noqa: E402

datas = [
    (str(ROOT / "assets" / "kpmn_tracer.png"), "assets"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "kpmn_tracer" / "scorecard" / "studio.html"), "scorecard"),
    (str(ROOT / "kpmn_tracer" / "scorecard" / "themes.js"), "scorecard"),
]
datas += [(str(p), "models") for p in (VENDOR / "models").glob("*") if p.is_file()]
binaries = []
if not IS_WIN:
    # static ffmpeg/ffprobe: bundled as binaries (macOS: signed together with the app)
    binaries += [(str(VENDOR / "ffmpeg" / "bin" / n), "ffmpeg") for n in ("ffmpeg", "ffprobe")]
    datas += [(str(VENDOR / "ffmpeg" / "LICENSE.txt"), "ffmpeg")]
# Windows: FFmpeg (shared build) is copied into _internal/ffmpeg by tools/build.py after this step -
# as PyInstaller binaries its DLLs would be analysed and duplicated into the top folder.
mp_datas, mp_bins, mp_hidden = collect_all("mediapipe")

EXCLUDES = ["jax", "jaxlib", "torch", "torchvision",  # jax: pulled in by MediaPipe 0.10.21 (Intel Macs), unused
             "ultralytics", "imageio_ffmpeg", "tensorflow", "tkinter", "IPython", "jupyter",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth"]


def analysis(script: str):
    return Analysis(  # noqa: F821
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT)],
        binaries=mp_bins + binaries,
        datas=datas + mp_datas,
        hiddenimports=mp_hidden + ["kpmn_tracer.gui.main_window", "kpmn_tracer.segmentation.provider",
                                   "scipy.interpolate", "scipy.signal", "scipy.ndimage", "scipy.optimize"],
        excludes=EXCLUDES,
        noarchive=False,
    )


a_gui = analysis("gui_entry.py")
a_cli = analysis("cli_entry.py")
pyz_gui = PYZ(a_gui.pure)  # noqa: F821
pyz_cli = PYZ(a_cli.pure)  # noqa: F821
icon = str(ROOT / "assets" / ("kpmn_tracer.ico" if IS_WIN else "kpmn_tracer.png"))  # PNG -> .icns via Pillow
gui_name = "kpmn-tracer-gui" if not (IS_WIN or IS_MAC) else "KPMN Tracer"

exe_gui = EXE(  # noqa: F821
    pyz_gui, a_gui.scripts, [], exclude_binaries=True, name=gui_name, console=False,
    icon=icon, upx=False, argv_emulation=False,
)
exe_cli = EXE(  # noqa: F821
    pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="kpmn-tracer", console=True,
    icon=icon, upx=False,
)
coll = COLLECT(  # noqa: F821
    exe_gui, a_gui.binaries, a_gui.datas,
    exe_cli, a_cli.binaries, a_cli.datas,
    strip=False, upx=False, name="KPMN-Tracer",
)
if IS_MAC:
    app = BUNDLE(  # noqa: F821
        coll,
        name="KPMN Tracer.app",
        icon=icon,
        bundle_identifier="io.github.felixkpm.kpmn-tracer",
        version=__version__,
        info_plist={
            "CFBundleName": "KPMN Tracer",
            "CFBundleDisplayName": "KPMN Tracer",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "12.0",
            "NSRequiresAquaSystemAppearance": False,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Video",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["public.movie", "com.apple.quicktime-movie", "public.mpeg-4"],
            }],
        },
    )
