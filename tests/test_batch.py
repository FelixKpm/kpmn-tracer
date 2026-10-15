"""Phase 7: batch processing of a folder, presets, CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kpmn_tracer.batch import analyze_folder, export_confirmed, find_clips, set_confirmed, write_summary
from kpmn_tracer.io.decode import count_frames
from kpmn_tracer.project.presets import BUILTIN_STYLES, PositionPreset, PresetStore
from kpmn_tracer.project.project_file import Project, project_path_for


@pytest.fixture(scope="module")
def session_folder(media_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[dict]]:
    from synth import ShotSpec, SynthConfig, generate

    folder = tmp_path_factory.mktemp("range_session")
    truths = []
    for k in range(2):
        shots = [ShotSpec(impact_frame=25, velocity=(2 + k, -21, 46)),
                 ShotSpec(impact_frame=150, placed_frame=120, velocity=(-2, -22, 47))]
        cfg = SynthConfig(width=640, height=360, fps=30, n_frames=270, shots=shots, ref_frame=0, audio=True,
                          club=True, seed=40 + k, crf=14)
        truths.append(generate(cfg, folder, f"clip{k}"))
    for extra in folder.glob("*.wav"):
        extra.unlink()
    (folder / "notes.txt").write_text("not a clip")
    return folder, truths


def test_presets_roundtrip(tmp_path: Path) -> None:
    st = PresetStore(tmp_path)
    assert set(BUILTIN_STYLES) <= set(st.style_names())
    s = st.load_style("Gelb Schweif")
    s.width = 11
    st.save_style("Mein/Style", s)
    assert st.load_style("Mein/Style").width == 11
    assert st.delete_style("Mein/Style") and not st.delete_style("TV Rot")
    pre = PositionPreset((0.5, 0.8), (0.52, 0.3), (0.55, 0.45), 4.0)
    st.save_position(pre)
    assert st.load_position() == pre
    d = st.load_defaults()
    d.detector = "both"
    st.save_defaults(d)
    assert st.load_defaults().detector == "both"


def test_batch_analyse_review_export(session_folder, tmp_path: Path) -> None:
    folder, truths = session_folder
    assert [p.name for p in find_clips(folder)] == ["clip0.mp4", "clip1.mp4"]
    ball = truths[0]["frames"][0]["balls"][0]["frame"]
    preset = PositionPreset((ball[0] / 640, ball[1] / 360))
    from kpmn_tracer.analysis import AnalysisOptions

    seen = []
    results = analyze_folder(folder, preset, AnalysisOptions(use_person_mask=False), auto_confirm=0.8,
                             on_clip=seen.append)
    assert len(results) == 2 and len(seen) == 2 and not any(r.error for r in results)
    for r, t in zip(results, truths):
        assert [s.impact_frame for s in r.shots] == t["impact_frames"]
        assert all(s.confidence >= 0.8 and s.confirmed for s in r.shots)
        assert all(Path(s.thumbnail).exists() for s in r.shots)
        assert project_path_for(r.clip).exists()
    summary = write_summary(results, tmp_path / "summary.csv")
    assert len(summary.read_text(encoding="utf-8").splitlines()) == 5

    # un-confirm the second shot of clip1 -> its overlay must not contain it
    r1 = results[1]
    set_confirmed(r1.clip, r1.shots[1].shot_id, False)
    assert not Project.load(project_path_for(r1.clip)).shots[1].confirmed
    outs = export_confirmed(folder, "prores")
    assert len(outs) == 2
    for o, r in zip(sorted(outs), results):
        assert count_frames(o) == count_frames(Path(r.clip))
    # re-running skips clips that are already analysed (keeps the user's review)
    again = analyze_folder(folder, preset)
    assert not Project.load(project_path_for(r1.clip)).shots[1].confirmed
    assert [len(r.shots) for r in again] == [2, 2]


def test_cli_batch_and_analyze(session_folder, tmp_path: Path, capsys) -> None:
    from kpmn_tracer.cli import main

    folder, truths = session_folder
    work = tmp_path / "cli"
    work.mkdir()
    shutil.copy(folder / "clip0.mp4", work / "clip0.mp4")
    ball = truths[0]["frames"][0]["balls"][0]["frame"]
    assert main(["batch", str(work), "--ball-norm", str(ball[0] / 640), str(ball[1] / 360),
                 "--auto-confirm", "0.8", "--no-mask", "--export", "prores"]) == 0
    out = capsys.readouterr().out
    assert "clip0.mp4" in out and "kpmn_batch_summary.csv" in out
    assert (work / "clip0_tracer.mov").exists()
    assert main(["batch-export", str(work)]) == 0
    shutil.copy(folder / "clip1.mp4", work / "single.mp4")
    assert main(["analyze", str(work / "single.mp4"), "--ball", str(ball[0]), str(ball[1]), "--no-mask"]) == 0
    proj = Project.load(project_path_for(work / "single.mp4"))
    assert [s.impact_frame for s in proj.shots] == truths[1]["impact_frames"]
