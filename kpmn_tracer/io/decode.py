"""FFmpeg decode helpers: SDR/CFR/rotation-normalised analysis stream and proxy creation.

The original clip is never modified. All analysis happens on a *proxy*: an
8-bit SDR, constant-frame-rate, rotation-applied MJPEG file whose frame ``i``
corresponds exactly to overlay frame ``i``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg
from kpmn_tracer.io.probe import VideoInfo

log = logging.getLogger(__name__)

ProgressFn = Callable[[float], None]
CancelFn = Callable[[], bool]

DEFAULT_PROXY_LONG_SIDE = 1920


class CancelledError(RuntimeError):
    pass


def tonemap_filter(info: VideoInfo) -> str | None:
    """Filter that converts HLG/PQ HDR to 8-bit-ready BT.709 SDR, or None for SDR input."""
    if not info.is_hdr:
        return None
    return (
        "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
        "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
    )


def proxy_size(info: VideoInfo, long_side: int = DEFAULT_PROXY_LONG_SIDE) -> tuple[int, int]:
    """Proxy (width, height): display orientation, longest side <= ``long_side``, even dims."""
    w, h = info.width, info.height
    scale = min(1.0, long_side / max(w, h))
    pw = max(2, int(round(w * scale / 2)) * 2)
    ph = max(2, int(round(h * scale / 2)) * 2)
    return pw, ph


def sdr_cfr_filters(
    info: VideoInfo, size: tuple[int, int] | None = None, vfr_mode: str = "frames"
) -> list[str]:
    """Video filters producing the normalised analysis/composite base stream.

    ``vfr_mode="frames"`` keeps every source frame and re-times frame ``n`` to
    ``n / target_fps`` (this is how DaVinci Resolve conforms VFR clips, so the
    overlay lines up 1:1). ``"resample"`` resamples by timestamp to CFR.
    """
    filters: list[str] = []
    if vfr_mode == "frames":
        filters.append(f"setpts=N/({_fps_str(info)}*TB)")
    tm = tonemap_filter(info)
    if tm:
        filters.append(tm)
    if size is not None and size != (info.width, info.height):
        filters.append(f"scale={size[0]}:{size[1]}:flags=area")
    return filters


def _fps_str(info: VideoInfo) -> str:
    return f"{info.target_fps.numerator}/{info.target_fps.denominator}"


def rate_args(info: VideoInfo, vfr_mode: str = "frames") -> list[str]:
    """Output rate arguments matching :func:`sdr_cfr_filters`."""
    return ["-fps_mode", "cfr", "-r", _fps_str(info)]


def expected_frames(info: VideoInfo, vfr_mode: str = "frames") -> int:
    if info.is_vfr and vfr_mode == "resample":
        return info.target_frame_count
    return info.frame_count_src


def cache_dir_for(source: Path, root: Path | None = None) -> Path:
    st = source.stat()
    key = hashlib.sha1(f"{source.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:12]
    base = root if root is not None else source.parent / ".kpmn_cache"
    return base / f"{source.stem}_{key}"


@dataclass
class Proxy:
    path: Path
    width: int
    height: int
    frame_count: int


def run_ffmpeg(
    args: list[str],
    total_frames: int | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
    stdin: bytes | None = None,
) -> None:
    """Run ffmpeg with progress reporting (``-progress pipe:1``) and cancellation."""
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
           "-progress", "pipe:1", *args]
    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, creationflags=SUBPROCESS_FLAGS)
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if cancel is not None and cancel():
                proc.kill()
                raise CancelledError("cancelled")
            if line.startswith("frame=") and progress and total_frames:
                try:
                    progress(min(1.0, int(line.split("=", 1)[1]) / total_frames))
                except ValueError:
                    pass
        _, err = proc.communicate()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()[-2000:]}")


def count_frames(path: Path) -> int:
    """Exact decoded frame count of a file (decodes the stream)."""
    from kpmn_tracer.io.ffmpeg_bin import ffprobe

    res = subprocess.run(
        [ffprobe(), "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS, check=True,
    )
    return int(res.stdout.strip().split(",")[0])


def _rotate_filters(rotation: int) -> list[str]:
    """Explicit rotation (clockwise degrees) for pipelines that run with ``-noautorotate``."""
    return {90: ["transpose=clock"], 180: ["hflip", "vflip"], 270: ["transpose=cclock"]}.get(rotation, [])


@dataclass
class ProxyPipeline:
    name: str
    input_args: list[str]
    filters: list[str]


def proxy_pipelines(info: VideoInfo, size: tuple[int, int], vfr_mode: str = "frames") -> list[ProxyPipeline]:
    """Ways to build the proxy, fastest first.

    4K/120 fps HEVC HDR is far too slow on the CPU (software HEVC decode ~35 fps,
    float tonemapping of every frame ~9 fps). On NVIDIA GPUs the frames are decoded
    and scaled with CUDA and tonemapped with Vulkan; only the small proxy frames
    reach the CPU (~10x faster). Every other machine uses the CPU pipeline, which
    scales *before* tonemapping (2x faster than the export chain, the small
    colour difference does not matter for analysis).
    """
    out: list[ProxyPipeline] = []
    rate = [f"setpts=N/({_fps_str(info)}*TB)"] if vfr_mode == "frames" else []
    # scaling happens before the rotation, i.e. in coded orientation
    rot = info.rotation in (90, 270)
    cw, ch = (size[1], size[0]) if rot else size
    if not os.environ.get("KPMN_NO_GPU"):
        fmt = "p010le" if info.bit_depth > 8 else "nv12"
        gpu = [*rate, f"scale_cuda={cw}:{ch}:format={fmt}:interp_algo=lanczos", "hwdownload", f"format={fmt}"]
        args = ["-init_hw_device", "cuda=cu", "-hwaccel", "cuda", "-hwaccel_device", "cu",
                "-hwaccel_output_format", "cuda", "-noautorotate"]
        if info.is_hdr:
            # libplacebo (Vulkan) with a fixed curve; tonemap_opencl always adapts to the
            # scene brightness, so the proxy would brighten and darken over a session
            args = ["-init_hw_device", "vulkan=vk", "-filter_hw_device", "vk", *args]
            gpu += ["hwupload", "libplacebo=tonemapping=gamma:peak_detect=0:colorspace=bt709:color_primaries=bt709"
                    ":color_trc=bt709:range=tv:format=nv12", "hwdownload", "format=nv12"]
        out.append(ProxyPipeline("cuda", args, [*gpu, *_rotate_filters(info.rotation), "format=yuvj420p"]))
    cpu = [*rate]
    if size != (info.width, info.height):
        cpu.append(f"scale={size[0]}:{size[1]}:flags=area")
    tm = tonemap_filter(info)
    if tm:
        cpu.append(tm)
    out.append(ProxyPipeline("cpu", [], [*cpu, "format=yuvj420p"]))
    return out


_FAILED_PIPELINES: set[str] = set()  # not available on this machine - not retried in this process


def count_packets(path: Path) -> int:
    """Frame count of an intra-only file (MJPEG proxy: one packet per frame) without decoding it."""
    from kpmn_tracer.io.ffmpeg_bin import ffprobe

    res = subprocess.run(
        [ffprobe(), "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS, check=True,
    )
    return int(res.stdout.strip().split(",")[0])


def make_proxy(
    info: VideoInfo,
    out_dir: Path,
    long_side: int = DEFAULT_PROXY_LONG_SIDE,
    vfr_mode: str = "frames",
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
    pipelines: list[str] | None = None,
) -> Proxy:
    """Create (or reuse) the MJPEG analysis proxy for ``info``.

    ``pipelines`` restricts the tried :func:`proxy_pipelines` by name (tests).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    size = proxy_size(info, long_side)
    out = out_dir / f"proxy_{size[0]}x{size[1]}_{vfr_mode}.avi"
    marker = out.with_suffix(".frames")
    if out.exists() and marker.exists():
        return Proxy(out, size[0], size[1], int(marker.read_text()))
    expected = expected_frames(info, vfr_mode)
    tmp = out.with_name(out.stem + ".tmp.avi")
    todo = [pl for pl in proxy_pipelines(info, size, vfr_mode)
            if (pipelines is None or pl.name in pipelines) and pl.name not in _FAILED_PIPELINES]
    if not todo:
        raise RuntimeError(f"no proxy pipeline available ({pipelines})")
    for i, pl in enumerate(todo):
        last = i == len(todo) - 1
        try:
            run_ffmpeg(
                [*pl.input_args, "-i", info.path, "-map", "0:v:0", "-vf", ",".join(pl.filters),
                 *rate_args(info, vfr_mode), "-c:v", "mjpeg", "-q:v", "2", "-an", str(tmp)],
                total_frames=expected, progress=progress, cancel=cancel,
            )
            n = count_packets(tmp)
        except CancelledError:
            raise
        except RuntimeError as e:
            if last:
                raise
            log.info("Proxy pipeline %s not usable (%s) - falling back", pl.name, str(e).splitlines()[-1][:200])
            _FAILED_PIPELINES.add(pl.name)
            continue
        if n != expected and not last:
            log.warning("Proxy pipeline %s gave %d frames, expected %d - falling back", pl.name, n, expected)
            _FAILED_PIPELINES.add(pl.name)
            continue
        break
    tmp.replace(out)
    marker.write_text(str(n))
    if n != expected:
        log.warning("Proxy has %d frames, expected %d", n, expected)
    log.info("Proxy ready: %s (%d frames, %s)", out.name, n, pl.name)
    return Proxy(out, size[0], size[1], n)


def extract_audio(info: VideoInfo, out_path: Path, sample_rate: int = 48000) -> Path | None:
    """Extract mono PCM WAV for impact detection. Returns None if the clip has no audio."""
    if not info.has_audio:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-i", info.path, "-map", "0:a:0", "-ac", "1", "-ar", str(sample_rate),
                "-c:a", "pcm_s16le", str(out_path)])
    return out_path
