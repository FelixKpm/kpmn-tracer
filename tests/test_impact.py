"""Phase 4: automatic impact detection (audio + video)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from kpmn_tracer.ball.audio_onsets import detect_onsets
from kpmn_tracer.ball.impact import ImpactParams, detect_impacts, locate_ball, video_impacts
from kpmn_tracer.session import ClipSession


def click(sr: int, amp: float, rng: np.random.Generator) -> np.ndarray:
    k = np.arange(int(0.08 * sr))
    return rng.normal(0, 1, k.size) * np.exp(-k / (0.006 * sr)) * amp


def test_onsets_are_sample_accurate_and_ignore_hum_and_voice() -> None:
    sr = 48000
    rng = np.random.default_rng(1)
    t = np.arange(6 * sr) / sr
    x = 0.02 * rng.normal(size=t.size) + 0.3 * np.sin(2 * np.pi * 50 * t)  # noise + mains hum
    x[int(2.5 * sr):int(3.5 * sr)] += 0.4 * np.sin(2 * np.pi * 180 * t[:sr])  # voice-ish tone
    truth = [0.731, 2.0004, 4.9]
    for tt in truth:
        c = click(sr, 0.8, rng)
        i = int(round(tt * sr))
        x[i:i + c.size] += c
    on = detect_onsets(x, sr)
    assert len(on) == 3
    for o, tt in zip(on, truth):
        assert abs(o.time - tt) < 0.0015
        assert o.strength > 0.5


def test_onsets_min_distance_keeps_one_per_swing() -> None:
    sr = 48000
    rng = np.random.default_rng(2)
    x = 0.01 * rng.normal(size=3 * sr)
    for tt, a in ((1.0, 0.8), (1.15, 0.3)):  # impact + echo
        c = click(sr, a, rng)
        x[int(tt * sr):int(tt * sr) + c.size] += c
    on = detect_onsets(x, sr)
    assert len(on) == 1 and abs(on[0].time - 1.0) < 0.002


def test_video_impacts_from_presence_signal() -> None:
    p = ImpactParams()
    ncc = np.r_[np.full(20, 0.9), [0.3], np.full(30, 0.1), np.full(25, 0.92), np.full(15, 0.05)]
    ncc[10] = 0.2  # single-frame occlusion (club in backswing) -> no impact
    assert video_impacts(ncc, 30.0, p) == [19, 75]


def test_locate_ball() -> None:
    g = np.full((200, 300), 90, np.uint8)
    import cv2

    cv2.circle(g, (150, 120), 4, 245, -1, cv2.LINE_AA)
    cv2.circle(g, (40, 40), 4, 245, -1)  # other ball far away
    loc = locate_ball(g, (145, 118), search_r=20)
    assert loc is not None and abs(loc[0] - 150) < 0.6 and abs(loc[1] - 120) < 0.6
    assert 2.5 < loc[2] < 6
    assert locate_ball(np.full((100, 100), 90, np.uint8), (50, 50)) is None


@pytest.fixture(scope="module")
def range_session(media_dir: Path, tmp_path_factory: pytest.TempPathFactory):
    from synth import ShotSpec, SynthConfig, generate

    fps = 30
    shots = [ShotSpec(impact_frame=30), ShotSpec(impact_frame=120, placed_frame=90),
             ShotSpec(impact_frame=216, placed_frame=195)]
    # foreign hits: 2.2 s and 5.5 s (spot empty), 6.7 s (our ball is resting there)
    cfg = SynthConfig(width=640, height=360, fps=fps, n_frames=270, shots=shots, ref_frame=0, audio=True,
                      club=True, audio_distractors=[2.2, 5.5, 6.7], shake_px=3, shake_rot_deg=0.2)
    truth = generate(cfg, media_dir, "range")
    sess = ClipSession.open(media_dir / "range.mp4", cache_root=tmp_path_factory.mktemp("c"))
    return sess, truth


def test_all_impacts_found_within_one_frame(range_session) -> None:
    """Abnahme Phase 4: ±1 frame, each shot found individually."""
    sess, truth = range_session
    ball = truth["frames"][0]["balls"][0]["frame"]
    cands = detect_impacts(sess, tuple(ball), 0)
    good = [c for c in cands if c.confidence >= 0.5]
    assert len(good) == 3
    for c, f in zip(good, truth["impact_frames"]):
        assert abs(c.frame - f) <= 1, (c.frame, f)
        assert c.sources[:2] == ["audio", "video"]
    # the foreign hit while our ball was resting (6.7 s = frame 201) is not reported at all
    assert not any(abs(c.frame - 201) <= 3 for c in cands)


def test_audio_only_without_ball_hint(range_session) -> None:
    sess, truth = range_session
    cands = detect_impacts(sess)
    frames = [c.frame for c in cands]
    for f in truth["impact_frames"]:
        assert any(abs(x - f) <= 1 for x in frames)
    assert all(c.sources == ["audio"] for c in cands)


def test_video_only_clip_without_audio(media_dir: Path, tmp_path: Path) -> None:
    from synth import ShotSpec, SynthConfig, generate

    shots = [ShotSpec(impact_frame=40), ShotSpec(impact_frame=150, placed_frame=110)]
    cfg = SynthConfig(width=640, height=360, fps=60, n_frames=220, shots=shots, ref_frame=0, club=True)
    truth = generate(cfg, media_dir, "silent")
    sess = ClipSession.open(media_dir / "silent.mp4", cache_root=tmp_path)
    cands = detect_impacts(sess, tuple(truth["frames"][0]["balls"][0]["frame"]), 0)
    assert [c.sources for c in cands] == [["video", "launch"], ["video", "launch"]]
    for c, f in zip(cands, truth["impact_frames"]):
        assert abs(c.frame - f) <= 1


def test_time_to_frame_uses_real_timestamps_for_vfr(tmp_path: Path) -> None:
    from conftest import write_index_video

    src = write_index_video(tmp_path / "vfr.mp4", 60, extra=[
        "-vf", "settb=1/90000,setpts='(N+0.45*eq(mod(N,4),2))/(30*TB)'",
        "-fps_mode", "passthrough", "-enc_time_base", "1/90000"])
    sess = ClipSession.open(src, cache_root=tmp_path / "c")
    ft = sess.frame_times()
    assert len(ft) == 60 and sess.project.video.is_vfr
    assert sess.time_to_frame(ft[10] + 0.001) == 10
    assert sess.time_to_frame(ft[10] - 0.001) == 9
    assert abs(ft[2] - ft[1] - 1.45 / 30) < 0.002  # irregular interval preserved
