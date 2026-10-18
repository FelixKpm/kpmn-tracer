"""Single frames as images (for social media posts): original resolution, tracer burned in.

The frame is decoded from the original clip, not from the preview proxy, so a
4K clip gives a 4K picture. Orientation and HDR->SDR conversion are the same
as for the burned-in video export. Frame ``i`` is the ``i``-th frame of the
normalised timeline (the one the editor and the overlay export use).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import cv2
import numpy as np

from kpmn_tracer.io.decode import tonemap_filter
from kpmn_tracer.io.export import OcclusionFn
from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg
from kpmn_tracer.io.probe import frame_times
from kpmn_tracer.project.project_file import Project
from kpmn_tracer.render.tracer import TracerRenderer, composite_over

log = logging.getLogger(__name__)

STILL_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG"}


def default_still_path(project: Project, frame: int, ext: str = ".jpg") -> Path:
    src = Path(project.source)
    return src.with_name(f"{src.stem}_frame{frame:05d}{ext}")


def source_time(project: Project, frame: int, pts: np.ndarray | None = None) -> float:
    """Presentation time (s, relative to the file start) of the source frame shown as ``frame``."""
    v = project.video
    if pts is None:
        pts = frame_times(project.source) if v.is_vfr else None
    if pts is None or len(pts) == 0:
        return frame / float(v.target_fps)
    if project.vfr_mode == "resample" and v.is_vfr:
        t = v.start_time + frame / float(v.target_fps)
        k = int(np.clip(np.searchsorted(pts, t + 1e-6, side="right") - 1, 0, len(pts) - 1))
    else:  # "frames": the i-th decoded frame
        k = int(np.clip(frame, 0, len(pts) - 1))
    return float(pts[k] - v.start_time)


def source_frame(project: Project, frame: int) -> np.ndarray:
    """Frame ``frame`` of the original clip (BGR, display orientation, SDR, full resolution)."""
    v = project.video
    t = source_time(project, frame)
    # accurate seek: ffmpeg decodes from the previous keyframe and drops frames before
    # the target; a quarter frame earlier is robust against rounding of the timestamps
    seek = max(0.0, t - 0.25 / float(v.target_fps))
    vf = tonemap_filter(v)
    cmd = [ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{seek:.6f}", "-i", v.path,
           "-map", "0:v:0", *(["-vf", vf] if vf else []), "-frames:v", "1",
           "-f", "image2pipe", "-c:v", "png", "-"]
    res = subprocess.run(cmd, capture_output=True, creationflags=SUBPROCESS_FLAGS)
    if res.returncode != 0 or not res.stdout:
        raise RuntimeError(f"ffmpeg could not decode frame {frame}: {res.stderr.decode(errors='replace')[-800:]}")
    img = cv2.imdecode(np.frombuffer(res.stdout, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"could not decode frame {frame}")
    if (img.shape[1], img.shape[0]) != (project.width, project.height):  # e.g. odd sizes / SAR
        img = cv2.resize(img, (project.width, project.height), interpolation=cv2.INTER_AREA)
    return img


def render_still(project: Project, frame: int, occlusion: OcclusionFn | None = None,
                 only_confirmed: bool = False) -> np.ndarray:
    """Original frame with the tracer (and text) of all complete shots burned in (BGR)."""
    img = source_frame(project, frame)
    shots = [s for s in project.shots if s.is_complete() and (s.confirmed or not only_confirmed)]
    if not shots:
        return img
    r = TracerRenderer(project.width, project.height, project.fps, project.style, project.text_style)
    mask = occlusion(frame) if occlusion is not None and any(s.occlude for s in shots) else None
    return composite_over(img, r.render(shots, frame, mask))


def save_still(project: Project, frame: int, out: str | Path | None = None,
               occlusion: OcclusionFn | None = None, jpeg_quality: int = 95) -> Path:
    out = Path(out) if out else default_still_path(project, frame)
    ext = out.suffix.lower()
    if ext not in STILL_FORMATS:
        raise ValueError(f"unsupported image format {ext} (png, jpg)")
    img = render_still(project, frame, occlusion)
    params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality] if STILL_FORMATS[ext] == "JPEG" else \
        [cv2.IMWRITE_PNG_COMPRESSION, 3]
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise OSError(f"could not encode {out.name}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buf.tobytes())  # cv2.imwrite cannot handle non-ASCII paths on Windows
    log.info("Still saved: %s (frame %d, %dx%d)", out, frame, img.shape[1], img.shape[0])
    return out
