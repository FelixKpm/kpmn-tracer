"""Overlay export: ProRes 4444 with alpha, PNG sequence, burned-in H.264/H.265.

The overlay always has the clip's display resolution, its (normalised) frame
rate and exactly ``project.frame_count`` frames, so it sits frame-accurately
on the original in DaVinci Resolve.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from kpmn_tracer.io.decode import CancelFn, CancelledError, ProgressFn, sdr_cfr_filters
from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg
from kpmn_tracer.project.project_file import Project
from kpmn_tracer.render.tracer import TracerRenderer

log = logging.getLogger(__name__)

OcclusionFn = Callable[[int], "np.ndarray | None"]

FORMATS = ("prores", "png", "h264", "h265")


@dataclass
class ExportSettings:
    fmt: str = "prores"  # one of FORMATS
    out_path: Path | None = None  # file (prores/h264/h265) or directory (png)
    crf: int = 18
    png_compression: int = 1
    frame_range: tuple[int, int] | None = None  # only for PNG: inclusive range


def fps_string(project: Project) -> str:
    f = project.video.target_fps
    return f"{f.numerator}/{f.denominator}"


def default_output(project: Project, fmt: str) -> Path:
    src = Path(project.source)
    if fmt == "prores":
        return src.with_name(f"{src.stem}_tracer.mov")
    if fmt == "png":
        return src.with_name(f"{src.stem}_tracer_png")
    return src.with_name(f"{src.stem}_tracer_{fmt}.mp4")


class _PipeWriter:
    """Feed raw frames into ffmpeg's stdin; stderr goes to a temp file (no pipe deadlocks)."""

    def __init__(self, args: list[str]) -> None:
        self._err = tempfile.TemporaryFile()
        cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", *args]
        log.debug("ffmpeg %s", " ".join(args))
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                     stderr=self._err, creationflags=SUBPROCESS_FLAGS)

    def write(self, data: bytes | memoryview) -> None:
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(data)
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"ffmpeg stopped accepting frames: {self._stderr()}") from exc

    def _stderr(self) -> str:
        self._err.seek(0)
        return self._err.read().decode(errors="replace").strip()[-2000:]

    def finish(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        if self.proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {self._stderr()}")
        self._err.close()

    def abort(self) -> None:
        self.proc.kill()
        self.proc.wait()
        self._err.close()


def _overlay_input_args(project: Project) -> list[str]:
    return ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{project.width}x{project.height}",
            "-r", fps_string(project), "-i", "-"]


def export(
    project: Project,
    settings: ExportSettings,
    occlusion: OcclusionFn | None = None,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> Path:
    if settings.fmt not in FORMATS:
        raise ValueError(f"unknown export format {settings.fmt}")
    out = Path(settings.out_path) if settings.out_path else default_output(project, settings.fmt)
    renderer = TracerRenderer(project.width, project.height, project.fps, project.style)
    shots = [s for s in project.shots if s.is_complete()]
    n = project.frame_count
    log.info("Exporting %s (%d frames, %dx%d @ %s) -> %s", settings.fmt, n,
             project.width, project.height, fps_string(project), out)

    writer: _PipeWriter | None = None
    if settings.fmt == "png":
        out.mkdir(parents=True, exist_ok=True)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        writer = _PipeWriter(_writer_args(project, settings, out))

    buf = np.zeros((project.height, project.width, 4), np.uint8)
    frames = range(n)
    if settings.fmt == "png" and settings.frame_range:
        a, b = settings.frame_range
        frames = range(max(0, a), min(n - 1, b) + 1)
    try:
        for i in frames:
            if cancel is not None and cancel():
                raise CancelledError("export cancelled")
            needs_mask = occlusion is not None and any(s.occlude for s in shots)
            mask = occlusion(i) if needs_mask else None
            renderer.render(shots, i, mask, out=buf)
            if writer is not None:
                writer.write(memoryview(buf))
            else:
                bgra = cv2.cvtColor(buf, cv2.COLOR_RGBA2BGRA)
                ok = cv2.imwrite(str(out / f"{Path(project.source).stem}_{i:06d}.png"), bgra,
                                 [cv2.IMWRITE_PNG_COMPRESSION, settings.png_compression])
                if not ok:
                    raise OSError(f"could not write PNG frame {i}")
            if progress is not None and (i % 5 == 0 or i == n - 1):
                progress((i + 1) / n)
        if writer is not None:
            writer.finish()
    except BaseException:
        if writer is not None:
            writer.abort()
        raise
    log.info("Export finished: %s", out)
    return out


def _writer_args(project: Project, settings: ExportSettings, out: Path) -> list[str]:
    fps = fps_string(project)
    tags = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if settings.fmt == "prores":
        return [*_overlay_input_args(project),
                "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                "-alpha_bits", "16", "-vendor", "apl0", *tags, "-r", fps, str(out)]
    # burned-in: decode original (rotation, HDR->SDR, CFR mapping identical to the proxy)
    base = sdr_cfr_filters(project.video, None, project.vfr_mode)
    base_chain = ",".join(base + ["format=yuv420p"]) if base else "format=yuv420p"
    graph = (f"[0:v:0]{base_chain}[base];[1:v]format=rgba[ov];"
             f"[base][ov]overlay=0:0:format=auto:eof_action=pass,format=yuv420p[v]")
    codec = (["-c:v", "libx264", "-preset", "medium", "-crf", str(settings.crf)]
             if settings.fmt == "h264" else
             ["-c:v", "libx265", "-preset", "medium", "-crf", str(settings.crf), "-tag:v", "hvc1"])
    rate = ["-fps_mode", "cfr", "-r", fps]
    return ["-i", project.source, *_overlay_input_args(project),
            "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?",
            *codec, *tags, *rate, "-frames:v", str(project.frame_count),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
