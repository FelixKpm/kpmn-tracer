# PyInstaller spec: one folder, two executables (GUI without console, CLI with console).
# Build with:  python tools/build_windows.py
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent  # noqa: F821 - provided by PyInstaller
VENDOR = ROOT / "vendor"

# FFmpeg is copied into _internal/ffmpeg by tools/build_windows.py after this step: as PyInstaller
# data its DLLs would be analysed and duplicated into the top folder.
datas = [
    (str(ROOT / "assets" / "kpmn_tracer.png"), "assets"),
    (str(ROOT / "README.md"), "."),
]
datas += [(str(p), "models") for p in (VENDOR / "models").glob("*") if p.is_file()]
mp_datas, mp_bins, mp_hidden = collect_all("mediapipe")

EXCLUDES = ["torch", "torchvision", "ultralytics", "imageio_ffmpeg", "tensorflow", "tkinter", "IPython", "jupyter",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
            "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
            "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth"]


def analysis(script: str):
    return Analysis(  # noqa: F821
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT)],
        binaries=mp_bins,
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
icon = str(ROOT / "assets" / "kpmn_tracer.ico")

exe_gui = EXE(  # noqa: F821
    pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="KPMN Tracer", console=False,
    icon=icon, upx=False,
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
