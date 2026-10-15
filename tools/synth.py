"""Synthetic golf-range test videos with exact ground truth.

A static "world" image (sky gradient, textured ground, random features) is
viewed by a camera whose motion is a known homography per frame. Balls fly on
physically plausible 3-D trajectories (gravity, optional drag and side spin)
that are projected with a pinhole camera. Optional: a moving "person" blob,
audio clicks at impact, VFR timestamps, rotation metadata.

World coordinates == pixel coordinates of the camera at frame ``ref_frame``
(identity camera). Ground truth stored per frame:

* ``world_to_frame[f]``: 3x3 homography world -> frame f
* per shot: ball position in world and frame coordinates, visibility

Usage (CLI)::

    python tools/synth.py out_dir --handheld --shots 2 --audio
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg

log = logging.getLogger("synth")


@dataclass
class ShotSpec:
    impact_frame: int
    # 3-D launch (metres, m/s); camera at origin looking along +Z, Y points down.
    start_xyz: tuple[float, float, float] = (0.0, 1.3, 4.0)
    velocity: tuple[float, float, float] = (1.5, -22.0, 45.0)
    side_accel: float = 0.0  # lateral acceleration (m/s^2): draw/fade
    drag: float = 0.0  # linear drag coefficient (1/s)
    ball_visible_after_s: float | None = None  # ball becomes invisible after this flight time
    hidden_intervals: list[tuple[int, int]] = field(default_factory=list)  # frame ranges
    placed_frame: int | None = None  # frame where the ball appears at its start position


@dataclass
class SynthConfig:
    width: int = 640
    height: int = 360
    fps: float = 30.0
    n_frames: int = 90
    ref_frame: int = 0  # camera == identity in this frame
    focal: float | None = None  # pixels; default 0.55 * max(width, height)
    shots: list[ShotSpec] = field(default_factory=lambda: [ShotSpec(impact_frame=10)])
    # camera motion
    shake_px: float = 0.0  # amplitude of handheld shake (pixels)
    shake_rot_deg: float = 0.0
    zoom_end: float = 1.0  # scale factor reached at the last frame
    pan_px_per_s: tuple[float, float] = (0.0, 0.0)
    # person
    person: bool = False
    person_center: tuple[float, float] | None = None  # world coords; default left of ball
    person_motion_px: float = 25.0
    person_scale: float = 1.0
    # media
    noise_sigma: float = 1.5
    ball_radius_min: float = 1.0
    ball_gain: float = 1.0  # brightness of the ball (1 = white)
    audio: bool = False
    audio_distractors: list[float] = field(default_factory=list)  # times of foreign hits (s)
    club: bool = False  # dark club head sweeping through the ball at impact
    audio_rate: int = 48000
    vfr_jitter: bool = False  # write slightly irregular timestamps
    display_rotation: int = 0  # write rotation metadata (degrees, counter-clockwise)
    seed: int = 1
    crf: int = 8

    @property
    def f(self) -> float:
        return self.focal if self.focal else 0.55 * max(self.width, self.height)


# ---------------------------------------------------------------- world image
def make_world(cfg: SynthConfig, margin: int) -> np.ndarray:
    """World texture covering world coords [-margin, w+margin] x [-margin, h+margin]."""
    rng = np.random.default_rng(cfg.seed)
    W, H = cfg.width + 2 * margin, cfg.height + 2 * margin
    horizon = margin + int(cfg.height * 0.42)
    img = np.zeros((H, W, 3), np.float32)
    # sky gradient (BGR)
    t = np.linspace(0, 1, horizon)[:, None]
    top, low = np.array([200, 150, 90], np.float32), np.array([235, 215, 190], np.float32)
    img[:horizon] = (top * (1 - t) + low * t)[:, None, :]
    # faint clouds: low-frequency noise
    clouds = cv2.resize(rng.random((max(2, H // 40), max(2, W // 40))).astype(np.float32),
                        (W, H), interpolation=cv2.INTER_CUBIC)
    img[:horizon] += (clouds[:horizon, :, None] - 0.5) * 18
    # ground: green with texture at several scales (gives trackable features)
    ground = np.array([60, 120, 70], np.float32)
    tex = np.zeros((H, W), np.float32)
    for scale, amp in ((6, 30), (17, 25), (45, 20)):
        n = rng.random((H // scale + 2, W // scale + 2)).astype(np.float32)
        tex += (cv2.resize(n, (W, H), interpolation=cv2.INTER_LINEAR) - 0.5) * amp
    img[horizon:] = ground + tex[horizon:, :, None]
    # tree line / distant objects on horizon (strong corners)
    for _ in range(W // 25):
        x = int(rng.integers(0, W))
        w = int(rng.integers(6, 30))
        h = int(rng.integers(8, 40))
        c = float(rng.integers(20, 70))
        cv2.rectangle(img, (x, horizon - h), (x + w, horizon), (c, c + 20, c), -1)
    # distance markers / flags on ground
    for _ in range(W * H // 9000):
        x, y = int(rng.integers(0, W)), int(rng.integers(horizon + 5, H))
        s = int(rng.integers(3, 9))
        col = tuple(float(v) for v in rng.integers(0, 255, 3))
        cv2.rectangle(img, (x, y), (x + s, y + s), col, -1)
    return np.clip(img, 0, 255)


# ---------------------------------------------------------------- camera
def _sim(scale: float, rot_deg: float, tx: float, ty: float, cx: float, cy: float) -> np.ndarray:
    a = np.deg2rad(rot_deg)
    c, s = np.cos(a) * scale, np.sin(a) * scale
    T1 = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], float)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)
    T2 = np.array([[1, 0, cx + tx], [0, 1, cy + ty], [0, 0, 1]], float)
    return T2 @ R @ T1


def camera_path(cfg: SynthConfig) -> np.ndarray:
    """world->frame homographies (n,3,3); identity at ``ref_frame``."""
    rng = np.random.default_rng(cfg.seed + 7)
    n = cfg.n_frames
    t = np.arange(n) / cfg.fps
    cx, cy = cfg.width / 2, cfg.height / 2

    def tremor(amp: float) -> np.ndarray:
        out = np.zeros(n)
        for freq in (1.3, 2.9, 5.7):
            out += amp / 3 * np.sin(2 * np.pi * freq * t + rng.uniform(0, 2 * np.pi))
        return out

    tx = tremor(cfg.shake_px) + cfg.pan_px_per_s[0] * t
    ty = tremor(cfg.shake_px) + cfg.pan_px_per_s[1] * t
    rot = tremor(cfg.shake_rot_deg)
    scale = 1.0 + (cfg.zoom_end - 1.0) * (t / max(t[-1], 1e-9))
    raw = np.stack([_sim(scale[i], rot[i], tx[i], ty[i], cx, cy) for i in range(n)])
    # small projective component (hand tilt) when shaking
    if cfg.shake_px > 0:
        p = tremor(cfg.shake_px * 2e-6)
        raw[:, 2, 0] = p
        raw[:, 2, 1] = -p * 0.7
    ref_inv = np.linalg.inv(raw[cfg.ref_frame])
    return np.stack([h @ ref_inv for h in raw])


def apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, float).reshape(-1, 2)
    hom = np.c_[pts, np.ones(len(pts))] @ H.T
    return hom[:, :2] / hom[:, 2:3]


# ---------------------------------------------------------------- ball physics
def ball_world_track(cfg: SynthConfig, shot: ShotSpec) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (positions world px (n,2), radius px (n,), in_flight mask (n,)) for all frames."""
    n = cfg.n_frames
    pos = np.full((n, 2), np.nan)
    rad = np.zeros(n)
    flying = np.zeros(n, bool)
    f, cx, cy = cfg.f, cfg.width / 2, cfg.height / 2
    x0, y0, z0 = shot.start_xyz
    ground_y = y0
    g = 9.81
    dt = 1.0 / cfg.fps
    sub = 50
    p = np.array([x0, y0, z0], float)
    v = np.array(shot.velocity, float)
    landed = False
    placed = shot.placed_frame if shot.placed_frame is not None else 0
    for i in range(n):
        if i < placed:
            continue
        if i >= shot.impact_frame and not landed:
            # integrate from previous frame to this one
            if i > shot.impact_frame:
                h = dt / sub
                for _ in range(sub):
                    a = np.array([shot.side_accel, g, 0.0]) - shot.drag * v
                    v = v + a * h
                    p = p + v * h
                if p[1] >= ground_y:
                    landed = True
            flying[i] = not landed
        if landed:
            continue
        X, Y, Z = p
        pos[i] = (f * X / Z + cx, f * Y / Z + cy)
        rad[i] = max(cfg.ball_radius_min, f * 0.0214 / Z)
    return pos, rad, flying


# ---------------------------------------------------------------- rendering
def draw_ball(img: np.ndarray, x: float, y: float, r: float, gain: float) -> None:
    """Anti-aliased bright blob centred exactly at (x, y) (sub-pixel)."""
    R = int(np.ceil(r * 2 + 2))
    xi, yi = int(round(x)), int(round(y))
    x0, x1 = max(0, xi - R), min(img.shape[1], xi + R + 1)
    y0, y1 = max(0, yi - R), min(img.shape[0], yi + R + 1)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
    alpha = np.clip(r + 0.5 - d, 0, 1) * gain
    patch = img[y0:y1, x0:x1]
    patch[:] = patch * (1 - alpha[..., None]) + 250 * alpha[..., None]


def person_mask(cfg: SynthConfig, frame: int, H: np.ndarray) -> np.ndarray:
    """Binary mask (uint8 0/255) of the synthetic person in frame coordinates."""
    m = np.zeros((cfg.height, cfg.width), np.uint8)
    pc = cfg.person_center or (cfg.width * 0.40, cfg.height * 0.62)
    t = frame / cfg.fps
    swing = cfg.person_motion_px * np.sin(2 * np.pi * 0.7 * t)
    sway = cfg.person_motion_px * 0.4 * np.sin(2 * np.pi * 0.3 * t + 1)
    s = cfg.height / 360 * cfg.person_scale
    parts = [  # (dx, dy, ax, ay) in world px, relative to centre
        (sway, -95 * s, 14 * s, 16 * s),  # head
        (sway, -30 * s, 30 * s, 55 * s),  # torso
        (sway - 12 * s, 55 * s, 10 * s, 40 * s),  # legs
        (sway + 12 * s, 55 * s, 10 * s, 40 * s),
        (sway + swing, -10 * s, 40 * s, 10 * s),  # arms/club area
    ]
    for dx, dy, ax, ay in parts:
        c = apply_h(H, [(pc[0] + dx, pc[1] + dy)])[0]
        cv2.ellipse(m, (int(c[0]), int(c[1])), (max(1, int(ax)), max(1, int(ay))), 0, 0, 360, 255, -1)
    return m


def person_texture(cfg: SynthConfig, frame: int) -> np.ndarray:
    """Strongly textured clothing pattern that moves with the person (bad features)."""
    rng = np.random.default_rng(cfg.seed + 100)
    base = rng.integers(0, 255, (cfg.height // 4 + 2, cfg.width // 4 + 2, 3)).astype(np.float32)
    tex = cv2.resize(base, (cfg.width + 8, cfg.height + 8), interpolation=cv2.INTER_NEAREST)
    t = frame / cfg.fps
    shift = int(round(cfg.person_motion_px * np.sin(2 * np.pi * 0.7 * t)))
    tex = np.roll(tex, shift, axis=1)
    return tex[: cfg.height, : cfg.width]


# ---------------------------------------------------------------- audio
def make_audio(cfg: SynthConfig, path: Path) -> list[float]:
    rng = np.random.default_rng(cfg.seed + 3)
    sr = cfg.audio_rate
    n = int(round(cfg.n_frames / cfg.fps * sr))
    sig = rng.normal(0, 0.01, n)  # ambient noise
    times = []
    for shot in cfg.shots:
        # contact happens between the impact frame (ball still at rest) and the next frame
        t0 = (shot.impact_frame + 0.5) / cfg.fps
        i0 = int(round(t0 * sr))
        L = int(0.08 * sr)
        k = np.arange(L)
        click = rng.normal(0, 1, L) * np.exp(-k / (0.006 * sr)) * 0.8
        end = min(n, i0 + L)
        if i0 < n:
            sig[i0:end] += click[: end - i0]
        times.append(t0)
    for td in cfg.audio_distractors:  # hits from the neighbouring bay (somewhat quieter)
        i0 = int(round(td * sr))
        L = int(0.08 * sr)
        k = np.arange(L)
        click = rng.normal(0, 1, L) * np.exp(-k / (0.006 * sr)) * 0.45
        end = min(n, i0 + L)
        if 0 <= i0 < n:
            sig[i0:end] += click[: end - i0]
    # a few quieter distractor sounds (voices)
    for _ in range(2):
        i0 = int(rng.integers(0, max(1, n - sr // 5)))
        L = int(0.15 * sr)
        sig[i0:i0 + L] += np.sin(np.arange(L) * 2 * np.pi * 220 / sr) * 0.05
    pcm = (np.clip(sig, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return times


# ---------------------------------------------------------------- main entry
def generate(cfg: SynthConfig, out_dir: str | Path, name: str = "synthetic") -> dict:
    """Render the video ``<out_dir>/<name>.mp4`` and ``<name>.truth.json``. Returns truth."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(cfg.seed + 11)
    Hs = camera_path(cfg)
    margin = int(0.35 * max(cfg.width, cfg.height) * max(1.0, cfg.zoom_end)) + int(cfg.shake_px * 3) + 20
    margin += int(max(abs(cfg.pan_px_per_s[0]), abs(cfg.pan_px_per_s[1])) * cfg.n_frames / cfg.fps)
    world = make_world(cfg, margin)
    T = np.array([[1, 0, margin], [0, 1, margin], [0, 0, 1]], float)  # world -> world image
    tracks = [ball_world_track(cfg, s) for s in cfg.shots]

    video_path = out_dir / f"{name}.mp4"
    tmp_video = out_dir / f"{name}.noaudio.mp4"
    fps_str = f"{cfg.fps:.6f}"
    vf = []
    if cfg.vfr_jitter:
        # irregular timestamps: every 3rd frame delayed by 40 % of a frame interval
        vf = ["-vf", f"settb=1/90000,setpts='(N + 0.4*eq(mod(N,3),1))/({fps_str}*TB)'", "-fps_mode", "passthrough",
              "-enc_time_base", "1/90000", "-video_track_timescale", "90000"]
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{cfg.width}x{cfg.height}",
           "-r", fps_str, "-i", "-", *vf,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg.crf), "-pix_fmt", "yuv420p",
           "-g", "15", str(tmp_video)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=SUBPROCESS_FLAGS)
    assert proc.stdin is not None

    truth_frames = []
    masks = []
    for fidx in range(cfg.n_frames):
        H = Hs[fidx]
        frame = cv2.warpPerspective(world, H @ np.linalg.inv(T), (cfg.width, cfg.height),
                                    flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        balls = []
        for si, (shot, (pos, rad, flying)) in enumerate(zip(cfg.shots, tracks)):
            p = pos[fidx]
            if np.isnan(p).any():
                balls.append(None)
                continue
            fp = apply_h(H, p)[0]
            scale = np.sqrt(abs(np.linalg.det(H[:2, :2])))
            visible = True
            flight_t = (fidx - shot.impact_frame) / cfg.fps
            if shot.ball_visible_after_s is not None and flight_t > shot.ball_visible_after_s:
                visible = False
            if any(a <= fidx <= b for a, b in shot.hidden_intervals):
                visible = False
            if visible:
                draw_ball(frame, fp[0], fp[1], rad[fidx] * scale, cfg.ball_gain)
            balls.append({"shot": si, "world": p.tolist(), "frame": fp.tolist(),
                          "radius": float(rad[fidx] * scale), "visible": visible,
                          "flying": bool(flying[fidx])})
        if cfg.club:
            for shot, (pos, rad, _fl) in zip(cfg.shots, tracks):
                dtf = fidx - (shot.impact_frame + 0.5)  # frames relative to contact
                if abs(dtf) <= 3 and not np.isnan(pos[shot.impact_frame]).any():
                    b = apply_h(H, pos[shot.impact_frame])[0]
                    r0 = rad[shot.impact_frame] * np.sqrt(abs(np.linalg.det(H[:2, :2])))
                    cxy = (int(round(b[0] + dtf * 5 * r0)), int(round(b[1] + r0 * 0.3)))
                    cv2.ellipse(frame, cxy, (max(2, int(2.2 * r0)), max(2, int(1.3 * r0))), 0, 0, 360,
                                (45, 45, 50), -1)
        if cfg.person:
            m = person_mask(cfg, fidx, H)
            tex = person_texture(cfg, fidx)
            sel = m > 0
            frame[sel] = tex[sel] * 0.7 + 30
            masks.append(m)
        if cfg.noise_sigma > 0:
            frame = frame + rng.normal(0, cfg.noise_sigma, frame.shape).astype(np.float32)
        proc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
        truth_frames.append({"world_to_frame": H.tolist(), "balls": balls})
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed while writing synthetic video")

    audio_times: list[float] = []
    mux = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if cfg.display_rotation:
        mux += ["-display_rotation", str(cfg.display_rotation)]
    mux += ["-i", str(tmp_video)]
    if cfg.audio:
        wav = out_dir / f"{name}.wav"
        audio_times = make_audio(cfg, wav)
        mux += ["-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k"]
    mux += ["-c:v", "copy", str(video_path)]
    subprocess.run(mux, check=True, creationflags=SUBPROCESS_FLAGS)
    tmp_video.unlink()

    truth = {
        "config": {**asdict(cfg), "shots": [asdict(s) for s in cfg.shots]},
        "focal": cfg.f,
        "impact_frames": [s.impact_frame for s in cfg.shots],
        "audio_click_times": audio_times,
        "frames": truth_frames,
    }
    (out_dir / f"{name}.truth.json").write_text(json.dumps(truth))
    if masks:
        np.savez_compressed(out_dir / f"{name}.masks.npz", masks=np.stack(masks))
    log.info("Synthetic video written: %s", video_path)
    return truth


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir")
    ap.add_argument("--name", default="synthetic")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--shots", type=int, default=1)
    ap.add_argument("--handheld", action="store_true")
    ap.add_argument("--person", action="store_true")
    ap.add_argument("--audio", action="store_true")
    a = ap.parse_args()
    n = int(a.seconds * a.fps)
    gap = n // a.shots
    shots = [ShotSpec(impact_frame=int(gap * i + 0.3 * a.fps), placed_frame=gap * i) for i in range(a.shots)]
    cfg = SynthConfig(width=a.width, height=a.height, fps=a.fps, n_frames=n, shots=shots,
                      ref_frame=shots[0].impact_frame, shake_px=6.0 if a.handheld else 0.0,
                      shake_rot_deg=0.4 if a.handheld else 0.0, person=a.person, audio=a.audio)
    logging.basicConfig(level=logging.INFO)
    generate(cfg, a.out_dir, a.name)


if __name__ == "__main__":
    main()
