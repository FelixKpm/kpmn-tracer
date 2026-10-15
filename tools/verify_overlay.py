"""Lay an exported overlay back over the original clip and check that it fits.

Checks:
* overlay frame count == normalised source frame count
* the overlay's alpha is high on the tracer path expected for every frame
  (path points come from the project file, projected per frame)
* optional: writes a composite MP4 for visual inspection

Usage::

    python tools/verify_overlay.py clip.mp4.kpmntrace.json clip_tracer.mov [--composite out.mp4]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from pathlib import Path

import numpy as np

from kpmn_tracer.io.decode import count_frames, sdr_cfr_filters
from kpmn_tracer.io.ffmpeg_bin import SUBPROCESS_FLAGS, ffmpeg
from kpmn_tracer.project.project_file import Project
from kpmn_tracer.render.tracer import composite_over, shot_geometry

log = logging.getLogger("verify_overlay")


def iter_frames(args: list[str], w: int, h: int, channels: int, pix_fmt: str):
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", *args,
           "-f", "rawvideo", "-pix_fmt", pix_fmt, "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, creationflags=SUBPROCESS_FLAGS)
    assert proc.stdout is not None
    size = w * h * channels
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield np.frombuffer(buf, np.uint8).reshape(h, w, channels)
    proc.wait()


def verify(project: Project, overlay: Path, composite: Path | None = None) -> dict:
    w, h = project.width, project.height
    n_overlay = count_frames(overlay)
    report: dict = {"frames_source": project.frame_count, "frames_overlay": n_overlay}
    base = sdr_cfr_filters(project.video, None, project.vfr_mode)
    src_args = ["-i", project.source] + (["-vf", ",".join(base)] if base else []) + [
        "-fps_mode", "cfr", "-r", f"{project.video.target_fps}"]
    ov_frames = iter_frames(["-i", str(overlay)], w, h, 4, "rgba")
    src_frames = iter_frames(src_args, w, h, 3, "bgr24")

    writer = None
    if composite is not None:
        cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
               "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{project.video.target_fps}", "-i", "-",
               "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(composite)]
        writer = subprocess.Popen(cmd, stdin=subprocess.PIPE, creationflags=SUBPROCESS_FLAGS)

    shots = [s for s in project.shots if s.is_complete()]
    scale = project.style.scale_for(w, h)
    on_path, checked, frames = [], 0, 0
    for i, (ov, src) in enumerate(zip(ov_frames, src_frames)):
        frames += 1
        if writer is not None and writer.stdin is not None:
            writer.stdin.write(composite_over(src, ov).tobytes())
        for s in shots:
            geo = shot_geometry(s, i, project.fps, project.style, scale)
            if geo is None or geo.alpha < 0.5:
                continue
            pts = geo.points[:: max(1, len(geo.points) // 20)]
            for x, y in pts:
                xi, yi = int(round(x)), int(round(y))
                if 0 <= xi < w and 0 <= yi < h:
                    on_path.append(ov[yi, xi, 3] / 255.0)
                    checked += 1
    if writer is not None and writer.stdin is not None:
        writer.stdin.close()
        writer.wait()
    a = np.array(on_path) if on_path else np.zeros(1)
    report.update({
        "frames_compared": frames,
        "path_samples": checked,
        "path_alpha_min": float(a.min()),
        "path_alpha_mean": float(a.mean()),
        "frame_count_match": n_overlay == project.frame_count,
    })
    report["ok"] = bool(report["frame_count_match"] and report["path_alpha_min"] > 0.5)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("overlay")
    ap.add_argument("--composite")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    rep = verify(Project.load(a.project), Path(a.overlay), Path(a.composite) if a.composite else None)
    print(json.dumps(rep, indent=1))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
