"""iPhone-like input: 10-bit HEVC, HLG HDR, rotation metadata."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kpmn_tracer.io.decode import count_frames
from kpmn_tracer.io.export import ExportSettings, export
from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot


@pytest.fixture(scope="module")
def hlg_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    d = tmp_path_factory.mktemp("hdr")
    tmp, out = d / "tmp.mov", d / "hlg_portrait.mov"
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=1",
                    "-vf", "format=yuv420p10le", "-c:v", "libx265", "-x265-params",
                    "log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
                    "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
                    "-tag:v", "hvc1", str(tmp)], check=True, creationflags=SUBPROCESS_FLAGS)
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-display_rotation", "90", "-i", str(tmp), "-c", "copy",
                    str(out)], check=True, creationflags=SUBPROCESS_FLAGS)
    return out


def test_hlg_portrait_clip_end_to_end(hlg_clip: Path, tmp_path: Path) -> None:
    sess = ClipSession.open(hlg_clip, cache_root=tmp_path / "c")
    v = sess.project.video
    assert v.is_hdr and v.hdr_format == "HLG" and v.bit_depth == 10 and v.codec == "hevc"
    assert (v.width, v.height) == (360, 640) and v.is_portrait
    img = sess.reader.read(10)
    assert img.shape == (640, 360, 3) and 30 < img.mean() < 220  # tonemapped, not black/clipped
    shot = Shot(impact_frame=3, land_frame=25)
    shot.set_anchor(AnchorKind.START, 180, 600)
    shot.set_anchor(AnchorKind.APEX, 200, 100)
    shot.set_anchor(AnchorKind.LAND, 260, 300)
    sess.project.shots = [shot]
    for fmt, name in (("prores", "o.mov"), ("h264", "o.mp4")):
        out = export(sess.project, ExportSettings(fmt, tmp_path / name))
        assert count_frames(out) == 30
