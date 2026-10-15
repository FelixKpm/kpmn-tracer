"""Batch processing of a whole range session (folder of clips).

1. :func:`analyze_folder` - every clip: impacts -> shots -> automatic tracking,
   project file saved next to the clip, one thumbnail per shot.
2. Review: the user confirms shots (GUI review list, or ``auto_confirm``).
3. :func:`export_confirmed` - overlay export per clip containing only the
   confirmed shots.

The ball position comes from the stored tripod position preset (normalised
coordinates), or from a project that already has a shot.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from kpmn_tracer.analysis import AnalysisOptions, analyze_clip
from kpmn_tracer.ball.impact import locate_ball
from kpmn_tracer.io.decode import CancelFn, CancelledError, ProgressFn
from kpmn_tracer.io.export import ExportSettings, export
from kpmn_tracer.project.presets import PositionPreset
from kpmn_tracer.project.project_file import Project, project_path_for
from kpmn_tracer.render.tracer import TracerRenderer, composite_over
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import AnchorKind, Shot, scaled_shot

log = logging.getLogger(__name__)

VIDEO_EXT = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm"}
THUMB_DIR = "kpmn_review"


@dataclass
class ShotReview:
    clip: str
    shot_id: str
    index: int
    impact_frame: int
    time_s: float
    confidence: float
    confirmed: bool
    thumbnail: str | None


@dataclass
class ClipResult:
    clip: str
    project: str | None
    shots: list[ShotReview] = field(default_factory=list)
    error: str | None = None


def find_clips(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in VIDEO_EXT and not p.stem.endswith("_tracer")
                  and "_tracer_" not in p.stem)


def find_hint_frame(session: ClipSession, hint: tuple[float, float], max_s: float = 6.0) -> int | None:
    """First frame (checked every 0.25 s) where a resting ball is visible near ``hint``."""
    hp = session.source_to_proxy(np.array([hint]))[0]
    step = max(1, int(round(0.25 * session.project.fps)))
    last = min(session.project.frame_count - 1, int(max_s * session.project.fps))
    for f in range(0, last + 1, step):
        g = session.reader.read(f)
        if locate_ball(g, (float(hp[0]), float(hp[1])), search_r=max(12.0, 0.03 * max(g.shape))) is not None:
            return f
    return None


def make_thumbnail(session: ClipSession, shot: Shot, path: Path, width: int = 360) -> Path:
    """Frame shortly before landing (impact if not tracked) with the tracer drawn."""
    p = session.project
    if shot.is_complete():
        f = int(min(p.frame_count - 1, shot.impact_frame + 0.85 * shot.flight_frames(p.fps)))
    else:
        f = shot.impact_frame
    img = session.reader.read(f)
    r = TracerRenderer(session.reader.width, session.reader.height, p.fps, p.style)
    s = scaled_shot(shot, session.sx, session.sy)
    out = composite_over(img, r.render([s], f)) if s.is_complete() else img.copy()
    h = int(round(out.shape[0] * width / out.shape[1]))
    thumb = cv2.resize(out, (width, h), interpolation=cv2.INTER_AREA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return path


def review_for(session: ClipSession, thumbs: bool = True) -> list[ShotReview]:
    p = session.project
    out = []
    tdir = Path(p.source).parent / THUMB_DIR
    for i, s in enumerate(p.shots):
        thumb = None
        if thumbs:
            thumb = str(make_thumbnail(session, s, tdir / f"{Path(p.source).stem}_{s.id}.jpg"))
        out.append(ShotReview(p.source, s.id, i, s.impact_frame, s.impact_frame / p.fps,
                              float(s.confidence or 0.0), s.confirmed, thumb))
    return out


def analyze_folder(
    folder: str | Path,
    preset: PositionPreset | None = None,
    options: AnalysisOptions | None = None,
    auto_confirm: float | None = None,
    reanalyze: bool = False,
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
    on_clip: Callable[[ClipResult], None] | None = None,
) -> list[ClipResult]:
    clips = find_clips(folder)
    results: list[ClipResult] = []
    for i, clip in enumerate(clips):
        if cancel is not None and cancel():
            raise CancelledError("batch cancelled")
        a, b = i / max(1, len(clips)), (i + 1) / max(1, len(clips))

        def sub(f: float, a: float = a, b: float = b) -> None:
            if progress:
                progress(a + (b - a) * f)

        res = ClipResult(str(clip), None)
        try:
            sess = ClipSession.open(clip, progress=lambda f: sub(0.1 * f), cancel=cancel)
            try:
                p = sess.project
                if reanalyze:
                    p.shots = [s for s in p.shots if s.confirmed]
                if not p.shots or reanalyze:
                    hint = None
                    existing = next((s for s in p.shots if s.anchor(AnchorKind.START)), None)
                    if existing is not None:
                        a0 = existing.anchor(AnchorKind.START)
                        hint = (a0.x, a0.y)
                    elif preset is not None:
                        hint = (preset.start[0] * p.width, preset.start[1] * p.height)
                    elif p.ball_start_hint:
                        hint = p.ball_start_hint
                    hint_frame = find_hint_frame(sess, hint) if hint else None
                    analyze_clip(sess, hint if hint_frame is not None else None, hint_frame, options,
                                 progress=lambda f: sub(0.1 + 0.85 * f), cancel=cancel)
                if auto_confirm is not None:
                    for s in p.shots:
                        if (s.confidence or 0) >= auto_confirm:
                            s.confirmed = True
                res.project = str(sess.save())
                res.shots = review_for(sess)
            finally:
                sess.close()
        except CancelledError:
            raise
        except Exception as exc:  # one broken clip must not stop the session
            log.exception("Batch: %s failed", clip)
            res.error = str(exc)
        results.append(res)
        if on_clip:
            on_clip(res)
        sub(1.0)
    return results


def set_confirmed(clip: str | Path, shot_id: str, confirmed: bool) -> None:
    pf = project_path_for(clip)
    proj = Project.load(pf)
    for s in proj.shots:
        if s.id == shot_id:
            s.confirmed = confirmed
    proj.save(pf)


def export_confirmed(
    folder_or_clips: str | Path | list[Path],
    fmt: str = "prores",
    progress: ProgressFn | None = None,
    cancel: CancelFn | None = None,
) -> list[Path]:
    clips = find_clips(folder_or_clips) if isinstance(folder_or_clips, (str, Path)) else folder_or_clips
    todo = []
    for c in clips:
        pf = project_path_for(c)
        if pf.exists():
            proj = Project.load(pf)
            if any(s.confirmed and s.is_complete() for s in proj.shots):
                todo.append(proj)
    outs = []
    for i, proj in enumerate(todo):
        def sub(f: float, i: int = i) -> None:
            if progress:
                progress((i + f) / len(todo))

        occl = None
        if any(s.occlude and s.confirmed for s in proj.shots):
            from kpmn_tracer.segmentation.provider import occlusion_for_session

            sess = ClipSession.open(proj.source)
            occl = occlusion_for_session(sess)
        outs.append(export(proj, ExportSettings(fmt, only_confirmed=True), occl, sub, cancel))
    return outs


def write_summary(results: list[ClipResult], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["clip", "shot", "impact_frame", "time_s", "confidence", "confirmed", "thumbnail", "error"])
        for r in results:
            if r.error:
                w.writerow([r.clip, "", "", "", "", "", "", r.error])
            for s in r.shots:
                w.writerow([s.clip, s.index + 1, s.impact_frame, f"{s.time_s:.2f}", f"{s.confidence:.2f}",
                            int(s.confirmed), s.thumbnail or "", ""])
    return path
