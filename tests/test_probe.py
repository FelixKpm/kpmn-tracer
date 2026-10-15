from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from kpmn_tracer.io.probe import analyse_intervals, probe, snap_rate


def test_analyse_intervals_cfr_and_vfr() -> None:
    cfr = np.arange(100) / 30.0
    assert analyse_intervals(cfr)[0] is False
    vfr = np.cumsum(np.r_[0, np.tile([1 / 30, 1 / 24], 50)])
    assert analyse_intervals(vfr)[0] is True


def test_analyse_intervals_tolerates_timebase_jitter() -> None:
    pts = np.round(np.arange(200) / 29.97 * 600) / 600  # 1/600 timebase rounding (iPhone)
    assert analyse_intervals(pts)[0] is False


@pytest.mark.parametrize("fps,expected", [
    (29.97, Fraction(30000, 1001)), (30.02, Fraction(30)), (59.9, Fraction(60000, 1001)),
    (240.3, Fraction(240)), (119.88, Fraction(120000, 1001)), (17.0, Fraction(17)),
])
def test_snap_rate(fps: float, expected: Fraction) -> None:
    assert snap_rate(fps) == expected


def test_probe_cfr_with_audio(tripod_clip: tuple[Path, dict]) -> None:
    info = probe(tripod_clip[0])
    assert (info.width, info.height) == (640, 360)
    assert info.target_fps == 30
    assert not info.is_vfr
    assert info.frame_count_src == 120
    assert info.has_audio and info.audio_sample_rate == 48000
    assert info.bit_depth == 8 and not info.is_hdr


def test_probe_rotation_and_vfr(media_dir: Path) -> None:
    from synth import SynthConfig, generate

    generate(SynthConfig(n_frames=45, display_rotation=90, vfr_jitter=True), media_dir, "rotvfr")
    info = probe(media_dir / "rotvfr.mp4")
    assert info.rotation in (90, 270)
    assert (info.width, info.height) == (360, 640)
    assert info.is_portrait
    assert info.is_vfr
    assert info.target_fps == 30


def test_roundtrip_dict(tripod_clip: tuple[Path, dict]) -> None:
    from kpmn_tracer.io.probe import VideoInfo

    info = probe(tripod_clip[0])
    assert VideoInfo.from_dict(info.to_dict()) == info
