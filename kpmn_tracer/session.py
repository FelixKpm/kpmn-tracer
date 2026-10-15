"""A loaded clip: project + proxy reader + coordinate scaling between proxy and source."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from kpmn_tracer.io.decode import CancelFn, ProgressFn, cache_dir_for, make_proxy
from kpmn_tracer.io.probe import probe
from kpmn_tracer.io.reader import FrameReader
from kpmn_tracer.project.project_file import Project, project_path_for

log = logging.getLogger(__name__)


class ClipSession:
    def __init__(self, project: Project, reader: FrameReader, cache_dir: Path) -> None:
        self.project = project
        self.reader = reader
        self.cache_dir = cache_dir
        # proxy pixel = source pixel * scale
        self.sx = reader.width / project.width
        self.sy = reader.height / project.height

    @classmethod
    def open(
        cls,
        clip_or_project: str | Path,
        vfr_mode: str = "frames",
        cache_root: Path | None = None,
        progress: ProgressFn | None = None,
        cancel: CancelFn | None = None,
    ) -> ClipSession:
        """Open a clip (or its ``.kpmntrace.json``). Existing project files are reused."""
        p = Path(clip_or_project)
        project: Project | None = None
        if p.name.endswith(".kpmntrace.json"):
            project = Project.load(p)
            clip = Path(project.source)
        else:
            clip = p
            pf = project_path_for(clip)
            if pf.exists():
                try:
                    project = Project.load(pf)
                except Exception:  # corrupt/old project: start fresh but keep the file
                    log.exception("Could not load %s - starting a new project", pf)
        info = project.video if project else probe(clip)
        mode = project.vfr_mode if project else vfr_mode
        cache = cache_dir_for(clip, cache_root)
        proxy = make_proxy(info, cache, vfr_mode=mode, progress=progress, cancel=cancel)
        if project is None:
            project = Project(source=str(clip.resolve()), video=info,
                              frame_count=proxy.frame_count, vfr_mode=mode)
        elif project.frame_count != proxy.frame_count:
            log.warning("Project frame count %d != proxy %d; using proxy",
                        project.frame_count, proxy.frame_count)
            project.frame_count = proxy.frame_count
        return cls(project, FrameReader(proxy.path), cache)

    # ------------------------------------------------------------ timing
    def frame_times(self) -> np.ndarray:
        """Absolute source time (s) of each normalised frame (cached in the cache dir).

        ``frames`` mode keeps every source frame, so these are the real (possibly
        irregular) timestamps; ``resample`` mode uses the constant output rate.
        """
        p = self.project
        start = p.video.start_time
        if p.vfr_mode == "resample" or not p.video.is_vfr:
            return start + np.arange(p.frame_count) / p.fps
        cache = self.cache_dir / "frame_times.npy"
        if cache.exists():
            t = np.load(cache)
        else:
            from kpmn_tracer.io.probe import frame_times

            t = frame_times(p.source)
            np.save(cache, t)
        if len(t) != p.frame_count:  # should not happen; fall back to nominal timing
            return start + np.arange(p.frame_count) / p.fps
        return t

    def time_to_frame(self, t: float) -> int:
        """Frame being shown at absolute time ``t`` (last frame with pts <= t)."""
        ft = self.frame_times()
        return int(np.clip(np.searchsorted(ft, t + 1e-6, side="right") - 1, 0, len(ft) - 1))

    # ------------------------------------------------------------ coordinates
    def proxy_to_source(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, float).reshape(-1, 2)
        return pts / np.array([self.sx, self.sy])

    def source_to_proxy(self, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, float).reshape(-1, 2)
        return pts * np.array([self.sx, self.sy])

    def H_proxy_to_source(self, H: np.ndarray) -> np.ndarray:
        """Convert a homography between proxy frames to one between source frames."""
        S = np.diag([self.sx, self.sy, 1.0])
        return np.linalg.inv(S) @ H @ S

    def save(self) -> Path:
        return self.project.save()

    def close(self) -> None:
        self.reader.close()
