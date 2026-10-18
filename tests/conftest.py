"""Shared fixtures: synthetic clips are generated once per test session."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg
from kpmn_tracer.logging_setup import setup_logging

setup_logging("WARNING")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")):
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

INDEX_BITS = 10
BLOCK = 16


def encode_index_frame(i: int, w: int = 320, h: int = 180) -> np.ndarray:
    """Frame whose top row of blocks encodes ``i`` in binary (robust to compression)."""
    img = np.full((h, w, 3), 60, np.uint8)
    for b in range(INDEX_BITS):
        if (i >> b) & 1:
            img[0:BLOCK, b * BLOCK:(b + 1) * BLOCK] = 255
        else:
            img[0:BLOCK, b * BLOCK:(b + 1) * BLOCK] = 0
    return img


def decode_index_frame(img: np.ndarray) -> int:
    v = 0
    for b in range(INDEX_BITS):
        block = img[2:BLOCK - 2, b * BLOCK + 2:(b + 1) * BLOCK - 2]
        if block.mean() > 128:
            v |= 1 << b
    return v


def write_index_video(path: Path, n: int, fps: str = "30", extra: list[str] | None = None) -> Path:
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
           "-pix_fmt", "bgr24", "-s", "320x180", "-r", fps, "-i", "-", *(extra or []),
           "-c:v", "libx264", "-crf", "12", "-g", "30", "-pix_fmt", "yuv420p", str(path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=SUBPROCESS_FLAGS)
    assert proc.stdin is not None
    for i in range(n):
        proc.stdin.write(encode_index_frame(i).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    return path


@pytest.fixture(autouse=True)
def isolated_presets(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Presets/settings go to a temp dir, never to the user's ~/.kpmn_tracer."""
    home = tmp_path_factory.mktemp("kpmn_home")
    monkeypatch.setenv("KPMN_HOME", str(home))
    return home


@pytest.fixture(scope="session")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def index_video(media_dir: Path) -> Path:
    return write_index_video(media_dir / "index.mp4", 150)


@pytest.fixture(scope="session")
def tripod_clip(media_dir: Path) -> tuple[Path, dict]:
    from synth import ShotSpec, SynthConfig, generate

    cfg = SynthConfig(width=640, height=360, fps=30, n_frames=120,
                      shots=[ShotSpec(impact_frame=15)], ref_frame=15, audio=True)
    truth = generate(cfg, media_dir, "tripod")
    return media_dir / "tripod.mp4", truth


@pytest.fixture(scope="session")
def person_clip(media_dir: Path) -> tuple[Path, dict, np.ndarray]:
    from synth import ShotSpec, SynthConfig, generate

    cfg = SynthConfig(width=640, height=360, fps=30, n_frames=80, shots=[ShotSpec(impact_frame=20)],
                      ref_frame=20, shake_px=5, shake_rot_deg=0.4, person=True, person_scale=2.5,
                      person_motion_px=25, crf=14)
    truth = generate(cfg, media_dir, "person")
    masks = np.load(media_dir / "person.masks.npz")["masks"]
    return media_dir / "person.mp4", truth, masks


@pytest.fixture(scope="session")
def range_session_gui(media_dir: Path, tmp_path_factory: pytest.TempPathFactory):
    """Three-shot range clip with audio and club (shared by GUI tests)."""
    from synth import ShotSpec, SynthConfig, generate

    from kpmn_tracer.session import ClipSession

    shots = [ShotSpec(impact_frame=30), ShotSpec(impact_frame=120, placed_frame=90),
             ShotSpec(impact_frame=216, placed_frame=195)]
    cfg = SynthConfig(width=640, height=360, fps=30, n_frames=270, shots=shots, ref_frame=0, audio=True,
                      club=True, audio_distractors=[2.2])
    truth = generate(cfg, media_dir, "range_gui")
    sess = ClipSession.open(media_dir / "range_gui.mp4", cache_root=tmp_path_factory.mktemp("c"))
    return sess, truth


@pytest.fixture(autouse=True)
def no_modal_message_boxes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A modal QMessageBox would block a headless test run forever; record the text instead."""
    shown: list[str] = []
    try:
        from PySide6.QtWidgets import QMessageBox
    except ImportError:  # pragma: no cover
        return shown

    def fake(kind: str):
        def show(_parent, title, text, *a, **k):
            shown.append(f"{kind}: {title}: {text}")
            print(f"[QMessageBox.{kind}] {title}: {text}")
            return QMessageBox.StandardButton.Ok
        return show

    for kind in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, kind, fake(kind))
    return shown
