"""Read clip metadata with ffprobe (resolution, rotation, fps, VFR, colour, bit depth)."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field, fields
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffprobe

log = logging.getLogger(__name__)

HDR_TRANSFERS = {"arib-std-b67": "HLG", "smpte2084": "PQ"}

# Frame rates we snap to when normalising VFR material.
STANDARD_RATES: tuple[Fraction, ...] = (
    Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
    Fraction(50), Fraction(60000, 1001), Fraction(60), Fraction(100), Fraction(120000, 1001),
    Fraction(120), Fraction(240000, 1001), Fraction(240),
)


class ProbeError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    path: str
    codec: str
    coded_width: int
    coded_height: int
    rotation: int  # clockwise degrees the player must rotate (0, 90, 180, 270)
    avg_fps: Fraction
    r_fps: Fraction
    target_fps: Fraction  # constant rate used for analysis and overlay export
    is_vfr: bool
    frame_count_src: int  # packets in the source stream
    duration: float  # seconds (video stream)
    start_time: float
    pix_fmt: str
    bit_depth: int
    color_transfer: str
    color_primaries: str
    color_space: str
    hdr_format: str | None  # "HLG", "PQ", optionally "+DolbyVision"
    has_audio: bool
    audio_sample_rate: int | None
    frame_intervals_ms: dict[str, float] = field(default_factory=dict)
    audio_start_time: float = 0.0  # absolute start of the audio stream (seconds)

    @property
    def width(self) -> int:
        """Display width (rotation applied)."""
        return self.coded_height if self.rotation in (90, 270) else self.coded_width

    @property
    def height(self) -> int:
        return self.coded_width if self.rotation in (90, 270) else self.coded_height

    @property
    def is_hdr(self) -> bool:
        return self.hdr_format is not None

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def target_frame_count(self) -> int:
        """Frames after normalisation to ``target_fps`` (what the overlay must contain)."""
        if not self.is_vfr:
            return self.frame_count_src
        return max(1, int(round(self.duration * float(self.target_fps))))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("avg_fps", "r_fps", "target_fps"):
            d[k] = f"{d[k].numerator}/{d[k].denominator}"
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VideoInfo:
        names = {f.name for f in fields(cls)}
        d = {k: v for k, v in d.items() if k in names}
        for k in ("avg_fps", "r_fps", "target_fps"):
            d[k] = Fraction(d[k])
        return cls(**d)

    def summary(self) -> str:
        parts = [
            f"{self.width}x{self.height}",
            f"{float(self.target_fps):.3f} fps" + (" (VFR->CFR)" if self.is_vfr else ""),
            f"{self.target_frame_count} frames",
            f"{self.codec} {self.bit_depth}-bit",
        ]
        if self.rotation:
            parts.append(f"rot {self.rotation}°")
        if self.hdr_format:
            parts.append(f"HDR {self.hdr_format}")
        return ", ".join(parts)


def _run_json(args: list[str]) -> dict[str, Any]:
    cmd = [ffprobe(), "-v", "error", "-of", "json", *args]
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
    if res.returncode != 0:
        raise ProbeError(res.stderr.strip() or f"ffprobe failed for {args[-1]}")
    return json.loads(res.stdout or "{}")


def _parse_rate(s: str | None) -> Fraction:
    if not s or s in ("0/0", "N/A"):
        return Fraction(0)
    return Fraction(s)


def _rotation(stream: dict[str, Any]) -> int:
    rot = 0.0
    for sd in stream.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = float(sd["rotation"])
    if rot == 0.0 and "rotate" in stream.get("tags", {}):
        # Old-style tag is clockwise already; side data is counter-clockwise.
        return int(stream["tags"]["rotate"]) % 360
    # Display matrix rotation is counter-clockwise; convert to clockwise.
    return int(round(-rot)) % 360


def _bit_depth(stream: dict[str, Any]) -> int:
    raw = stream.get("bits_per_raw_sample")
    if raw and str(raw).isdigit():
        return int(raw)
    pix = stream.get("pix_fmt", "")
    for depth in (16, 12, 10):
        if f"p{depth}" in pix:
            return depth
    return 8


def snap_rate(fps: float) -> Fraction:
    """Snap a measured rate to the nearest standard rate (within 1.5 %)."""
    if fps <= 0:
        return Fraction(30)
    best = min(STANDARD_RATES, key=lambda r: abs(float(r) - fps))
    if abs(float(best) - fps) / fps < 0.015:
        return best
    return Fraction(round(fps * 1000), 1000).limit_denominator(1001)


def analyse_intervals(pts: np.ndarray) -> tuple[bool, dict[str, float]]:
    """Decide VFR from presentation timestamps (seconds). Returns (is_vfr, stats in ms)."""
    if pts.size < 3:
        return False, {}
    d = np.diff(np.sort(pts)) * 1000.0
    d = d[d > 0]
    if d.size == 0:
        return False, {}
    med = float(np.median(d))
    stats = {"median": med, "min": float(d.min()), "max": float(d.max()), "std": float(d.std())}
    # Timestamps are quantised by the container timebase (e.g. 1/600 s on iPhones);
    # real VFR changes are much larger (30 -> 24 fps = 25 %).
    is_vfr = bool(np.any(np.abs(d - med) > max(0.6, 0.1 * med)))
    return is_vfr, stats


def frame_times(path: str | Path) -> np.ndarray:
    """Sorted absolute presentation times (s) of all video frames (cheap: no decoding)."""
    pk = _run_json(["-select_streams", "v:0", "-show_entries", "packet=pts_time", str(path)])
    return np.sort(np.array([float(p["pts_time"]) for p in pk.get("packets", [])
                             if p.get("pts_time") not in (None, "N/A")]))


def probe(path: str | Path) -> VideoInfo:
    path = Path(path)
    if not path.is_file():
        raise ProbeError(f"File not found: {path}")
    meta = _run_json(["-show_streams", "-show_format", str(path)])
    streams = meta.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if video is None:
        raise ProbeError(f"No video stream in {path}")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    pk = _run_json(["-select_streams", "v:0", "-show_entries", "packet=pts_time", str(path)])
    pts = np.array([float(p["pts_time"]) for p in pk.get("packets", [])
                    if p.get("pts_time") not in (None, "N/A")])
    is_vfr, stats = analyse_intervals(pts)

    avg = _parse_rate(video.get("avg_frame_rate"))
    rfr = _parse_rate(video.get("r_frame_rate"))
    duration = float(video.get("duration") or meta.get("format", {}).get("duration") or 0.0)
    count = int(pts.size) if pts.size else int(video.get("nb_frames") or 0)
    if is_vfr:
        measured = (count / duration) if duration > 0 else float(avg)
        target = snap_rate(measured)
    else:
        target = avg if avg > 0 else rfr
        if stats:
            target = snap_rate(1000.0 / stats["median"]) if target == 0 else target

    transfer = video.get("color_transfer", "") or ""
    hdr = HDR_TRANSFERS.get(transfer)
    if any("DOVI" in sd.get("side_data_type", "") or "Dolby" in sd.get("side_data_type", "")
           for sd in video.get("side_data_list", []) or []):
        hdr = (hdr or "PQ") + "+DolbyVision"

    info = VideoInfo(
        path=str(path),
        codec=video.get("codec_name", "?"),
        coded_width=int(video["width"]),
        coded_height=int(video["height"]),
        rotation=_rotation(video),
        avg_fps=avg,
        r_fps=rfr,
        target_fps=target,
        is_vfr=is_vfr,
        frame_count_src=count,
        duration=duration,
        start_time=float(video.get("start_time") or 0.0),
        pix_fmt=video.get("pix_fmt", ""),
        bit_depth=_bit_depth(video),
        color_transfer=transfer,
        color_primaries=video.get("color_primaries", "") or "",
        color_space=video.get("color_space", "") or "",
        hdr_format=hdr,
        has_audio=audio is not None,
        audio_sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        frame_intervals_ms=stats,
        audio_start_time=float(audio.get("start_time") or 0.0) if audio else 0.0,
    )
    log.info("Probed %s: %s", path.name, info.summary())
    if info.is_vfr:
        log.warning("%s has variable frame rate; normalising to %.3f fps (%d frames)",
                    path.name, float(info.target_fps), info.target_frame_count)
    return info
