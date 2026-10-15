from pathlib import Path

import numpy as np
from conftest import decode_index_frame, write_index_video

from kpmn_tracer.io.decode import make_proxy
from kpmn_tracer.io.probe import probe
from kpmn_tracer.io.reader import FrameReader


def test_proxy_seek_is_frame_exact(index_video: Path, tmp_path: Path) -> None:
    info = probe(index_video)
    proxy = make_proxy(info, tmp_path)
    assert proxy.frame_count == 150
    rng = np.random.default_rng(0)
    with FrameReader(proxy.path) as r:
        assert len(r) == 150
        order = list(rng.integers(0, 150, 60)) + [0, 149, 148, 1, 2, 3, 77, 78]
        for i in order:
            assert decode_index_frame(r.read(int(i))) == i


def test_vfr_frames_mode_keeps_every_frame(tmp_path: Path) -> None:
    src = write_index_video(
        tmp_path / "vfr.mp4", 90,
        extra=["-vf", "settb=1/90000,setpts='(N+0.45*eq(mod(N,4),2))/(30*TB)'",
               "-fps_mode", "passthrough", "-enc_time_base", "1/90000"])
    info = probe(src)
    assert info.is_vfr
    proxy = make_proxy(info, tmp_path / "c", vfr_mode="frames")
    assert proxy.frame_count == 90
    with FrameReader(proxy.path) as r:
        assert [decode_index_frame(r.read(i)) for i in range(90)] == list(range(90))


def test_rotated_clip_proxy_has_display_orientation(media_dir: Path, tmp_path: Path) -> None:
    from synth import SynthConfig, generate

    generate(SynthConfig(n_frames=10, display_rotation=90), media_dir, "rot_only")
    info = probe(media_dir / "rot_only.mp4")
    proxy = make_proxy(info, tmp_path)
    with FrameReader(proxy.path) as r:
        assert (r.width, r.height) == (360, 640)
        assert r.read(0).shape == (640, 360, 3)


def test_proxy_downscales_large_clips(tmp_path: Path) -> None:
    from kpmn_tracer.io.decode import proxy_size
    from kpmn_tracer.io.probe import VideoInfo

    vi = VideoInfo(path="x", codec="hevc", coded_width=3840, coded_height=2160, rotation=90,
                   avg_fps=30, r_fps=30, target_fps=30, is_vfr=False, frame_count_src=1,
                   duration=1, start_time=0, pix_fmt="yuv420p10le", bit_depth=10,
                   color_transfer="arib-std-b67", color_primaries="bt2020", color_space="bt2020nc",
                   hdr_format="HLG", has_audio=False, audio_sample_rate=None)
    assert proxy_size(vi) == (1080, 1920)
    assert proxy_size(vi, 960) == (540, 960)
