"""Single frame as image: right frame (also VFR/rotated), full resolution, tracer burned in."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from conftest import decode_index_frame, write_index_video

from kpmn_tracer.io.still import render_still, save_still, source_frame
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot


def test_still_is_the_right_frame(index_video: Path, tmp_path: Path) -> None:
    sess = ClipSession.open(index_video, cache_root=tmp_path / "c")
    try:
        for f in (0, 1, 29, 30, 77, 149):
            assert decode_index_frame(source_frame(sess.project, f)) == f
    finally:
        sess.close()


def test_still_is_the_right_frame_vfr(tmp_path: Path) -> None:
    src = write_index_video(tmp_path / "vfr.mp4", 60, extra=[
        "-vf", "settb=1/90000,setpts='(N+0.45*eq(mod(N,4),2))/(30*TB)'",
        "-fps_mode", "passthrough", "-enc_time_base", "1/90000"])
    sess = ClipSession.open(src, cache_root=tmp_path / "c")
    try:
        assert sess.project.video.is_vfr
        for f in (0, 2, 3, 6, 41, 59):  # frames with shifted timestamps included
            proxy = decode_index_frame(cv2.resize(sess.reader.read(f), (320, 180)))
            assert decode_index_frame(source_frame(sess.project, f)) == proxy == f
    finally:
        sess.close()


def test_still_rotated_has_display_orientation(tmp_path: Path) -> None:
    src = write_index_video(tmp_path / "rot.mp4", 20)
    rot = tmp_path / "rot90.mp4"
    import subprocess

    from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg

    subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-display_rotation", "90", "-i", str(src),
                    "-c", "copy", str(rot)], check=True, creationflags=SUBPROCESS_FLAGS)
    sess = ClipSession.open(rot, cache_root=tmp_path / "c")
    try:
        img = source_frame(sess.project, 5)
        assert (img.shape[1], img.shape[0]) == (sess.project.width, sess.project.height) == (180, 320)
        proxy = cv2.resize(sess.reader.read(5), (180, 320))
        assert np.abs(img.astype(int) - proxy.astype(int)).mean() < 6
    finally:
        sess.close()


def test_still_contains_tracer_and_is_saved(index_video: Path, tmp_path: Path) -> None:
    sess = ClipSession.open(index_video, cache_root=tmp_path / "c")
    try:
        p = sess.project
        shot = Shot(impact_frame=10)
        shot.set_anchor(AnchorKind.START, 60, 160)
        shot.set_anchor(AnchorKind.APEX, 160, 40)
        shot.set_anchor(AnchorKind.LAND, 260, 120)
        shot.land_frame = 70
        p.shots.append(shot)
        plain = source_frame(p, 60)
        traced = render_still(p, 60)
        assert traced.shape == plain.shape
        diff = np.abs(traced.astype(int) - plain.astype(int)).sum(axis=2) > 40
        assert diff[20:].sum() > 200  # the tracer line (below the index blocks)
        assert np.array_equal(render_still(p, 5), source_frame(p, 5))  # before impact: no tracer
        for name in ("still.png", "still ä.jpg"):
            out = save_still(p, 60, tmp_path / name)
            img = cv2.imdecode(np.fromfile(out, np.uint8), cv2.IMREAD_COLOR)
            assert img.shape == plain.shape
    finally:
        sess.close()
