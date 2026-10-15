"""Phase 1 acceptance: synthetic tripod clip -> overlay export -> laid back over the original."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from kpmn_tracer.io.decode import count_frames
from kpmn_tracer.io.export import ExportSettings, export
from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffprobe
from kpmn_tracer.render.tracer import TracerRenderer
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import Anchor, AnchorKind, Shot
from verify_overlay import iter_frames, verify


def shot_from_truth(truth: dict, step: int = 3) -> Shot:
    impact = truth["impact_frames"][0]
    flying = [(i, f["balls"][0]["world"]) for i, f in enumerate(truth["frames"])
              if i >= impact and f["balls"][0] and f["balls"][0]["flying"]]
    samples = flying[:6] + flying[6::step]  # dense right after impact (fast screen motion)
    if samples[-1] != flying[-1]:
        samples.append(flying[-1])
    apex_i = int(np.argmin([p[1] for _, p in samples]))
    anchors = []
    for k, (i, p) in enumerate(samples):
        kind = AnchorKind.POINT
        if k == 0:
            kind = AnchorKind.START
        elif k == len(samples) - 1:
            kind = AnchorKind.LAND
        elif k == apex_i:
            kind = AnchorKind.APEX
        anchors.append(Anchor(p[0], p[1], kind, float(i - impact)))
    s = Shot(impact_frame=impact, anchors=anchors, source="auto")
    s.shape.launch_steepness = 0.0
    s.shape.descent_steepness = 0.0
    return s


@pytest.fixture(scope="module")
def session(tripod_clip: tuple[Path, dict], tmp_path_factory: pytest.TempPathFactory) -> ClipSession:
    clip, truth = tripod_clip
    sess = ClipSession.open(clip, cache_root=tmp_path_factory.mktemp("cache"))
    sess.project.shots = [shot_from_truth(truth)]
    sess.project.style.glow_strength = 0.8
    return sess


def test_tracer_head_follows_ball(session: ClipSession, tripod_clip: tuple[Path, dict]) -> None:
    _, truth = tripod_clip
    s = session.project.shots[0]
    path = s.path()
    errs = []
    for i, f in enumerate(truth["frames"]):
        b = f["balls"][0]
        if not b or not b["flying"]:
            continue
        u = s.head_u(i, session.project.fps)
        errs.append(np.linalg.norm(path.evaluate(u)[0] - np.array(b["frame"])))
    assert np.mean(errs) < 1.0 and np.max(errs) < 3.0


def test_prores_overlay_acceptance(session: ClipSession, tmp_path: Path) -> None:
    proj = session.project
    out = export(proj, ExportSettings("prores", tmp_path / "overlay.mov"))
    meta = json.loads(subprocess.run(
        [ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,pix_fmt,width,height,r_frame_rate,profile", "-of", "json", str(out)],
        capture_output=True, text=True, check=True, creationflags=SUBPROCESS_FLAGS).stdout)["streams"][0]
    assert meta["codec_name"] == "prores" and meta["pix_fmt"].startswith("yuva444p")
    assert (meta["width"], meta["height"]) == (proj.width, proj.height)
    assert meta["r_frame_rate"] == "30/1"
    assert count_frames(out) == count_frames(Path(proj.source)) == proj.frame_count

    proj.save(tmp_path / "p.kpmntrace.json")
    rep = verify(proj, out, tmp_path / "composite.mp4")
    assert rep["ok"], rep
    assert rep["frames_compared"] == proj.frame_count

    # decoded overlay equals the direct render (up to 10-bit YUV rounding)
    r = TracerRenderer(proj.width, proj.height, proj.fps, proj.style)
    for i, ov in enumerate(iter_frames(["-i", str(out)], proj.width, proj.height, 4, "rgba")):
        if i in (20, 50, 100):
            ref = r.render(proj.shots, i)
            assert np.abs(ov[..., 3].astype(int) - ref[..., 3]).max() <= 2
            m = ref[..., 3] > 250
            assert np.abs(ov[m][:, :3].astype(int) - ref[m][:, :3]).mean() < 3


def test_png_sequence(session: ClipSession, tmp_path: Path) -> None:
    out = export(session.project, ExportSettings("png", tmp_path / "png"))
    files = sorted(out.glob("*.png"))
    assert len(files) == session.project.frame_count
    img = cv2.imread(str(files[60]), cv2.IMREAD_UNCHANGED)
    assert img.shape == (session.project.height, session.project.width, 4)
    assert img[..., 3].max() == 255 and img[0, 0, 3] == 0


@pytest.mark.parametrize("fmt", ["h264", "h265"])
def test_burned_in_export(session: ClipSession, tmp_path: Path, fmt: str) -> None:
    out = export(session.project, ExportSettings(fmt, tmp_path / f"burn_{fmt}.mp4", crf=12))
    assert count_frames(out) == session.project.frame_count
    proj = session.project
    s = proj.shots[0]
    p = s.path().evaluate(s.head_u(60, proj.fps) * 0.5)[0]
    frames = list(iter_frames(["-i", str(out)], proj.width, proj.height, 3, "bgr24"))
    b, g, r = frames[60][int(p[1]), int(p[0])].astype(int)
    assert r > 180 and r > g + 60


def test_project_roundtrip(session: ClipSession, tmp_path: Path) -> None:
    from kpmn_tracer.project.project_file import Project

    path = session.project.save(tmp_path / "x.kpmntrace.json")
    p2 = Project.load(path)
    assert p2.to_dict(tmp_path) == session.project.to_dict(tmp_path)
    assert Path(p2.source) == Path(session.project.source)
