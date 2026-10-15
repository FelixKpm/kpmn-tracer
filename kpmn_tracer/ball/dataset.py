"""Training data for the optional ML detector, bootstrapped from the user's own projects.

Every shot that was tracked (auto with good confidence, or confirmed by the
user) knows where the ball is in each frame. :func:`export_shot` cuts square
tiles around those positions out of the proxy frames (the resolution the
detector later sees) and writes YOLO labels (``class cx cy w h``, normalised).
Tiles without a ball (from frames before the impact) are added as negatives.
The labels can be checked/fixed with ``tools/label_balls.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import Shot

log = logging.getLogger(__name__)


@dataclass
class DatasetParams:
    tile: int = 320
    every_n: int = 2  # use every n-th flight frame
    min_box: float = 6.0  # px (proxy) - tiny balls still get a learnable box
    start_box: float = 14.0  # px box at the start, shrinks along the flight
    negatives_per_shot: int = 6
    jpeg_quality: int = 95
    seed: int = 0


def write_yaml(out: Path) -> Path:
    y = out / "dataset.yaml"
    y.write_text(f"path: {out.resolve().as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: ball\n",
                 encoding="utf-8")
    return y


def _tile(img: np.ndarray, cx: float, cy: float, size: int, rng: np.random.Generator) -> tuple[np.ndarray, int, int]:
    h, w = img.shape[:2]
    size = min(size, w, h)
    jitter = size // 3
    x0 = int(np.clip(cx - size / 2 + rng.integers(-jitter, jitter + 1), 0, w - size))
    y0 = int(np.clip(cy - size / 2 + rng.integers(-jitter, jitter + 1), 0, h - size))
    return img[y0:y0 + size, x0:x0 + size], x0, y0


def export_shot(session: ClipSession, shot: Shot, out: Path, split: str = "train",
                p: DatasetParams | None = None) -> int:
    """Write tiles + labels for one shot. Returns the number of positive tiles."""
    p = p or DatasetParams()
    path = shot.path()
    if path is None:
        return 0
    rng = np.random.default_rng(p.seed + shot.impact_frame)
    (out / "images" / split).mkdir(parents=True, exist_ok=True)
    (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    stem = f"{Path(session.project.source).stem}_{shot.id}"
    fps = session.project.fps
    end = int(min(session.project.frame_count - 1, shot.impact_frame + shot.flight_frames(fps)))
    n_pos = 0
    for f in range(shot.impact_frame + 1, end + 1, p.every_n):
        u = shot.head_u(f, fps)
        if u is None:
            continue
        xy = session.source_to_proxy(shot.to_frame(path.evaluate(u), f))[0]
        img = session.reader.read(f)
        h, w = img.shape[:2]
        if not (0 <= xy[0] < w and 0 <= xy[1] < h):
            continue
        tile, x0, y0 = _tile(img, xy[0], xy[1], p.tile, rng)
        ts = tile.shape[0]
        box = max(p.min_box, p.start_box * (1.0 - 0.8 * u))
        cx, cy = (xy[0] - x0) / ts, (xy[1] - y0) / ts
        name = f"{stem}_{f:06d}"
        cv2.imwrite(str(out / "images" / split / f"{name}.jpg"), tile, [cv2.IMWRITE_JPEG_QUALITY, p.jpeg_quality])
        (out / "labels" / split / f"{name}.txt").write_text(f"0 {cx:.6f} {cy:.6f} {box / ts:.6f} {box / ts:.6f}\n")
        n_pos += 1
    # negatives: sky/ground around the flight path before the impact (no ball in the air)
    pre = list(range(max(0, shot.impact_frame - int(2 * fps)), shot.impact_frame))
    for i in range(min(p.negatives_per_shot, len(pre))):
        f = int(rng.choice(pre))
        u = float(rng.uniform(0.1, 0.9))
        xy = session.source_to_proxy(shot.to_frame(path.evaluate(u), f))[0]
        tile, _, _ = _tile(session.reader.read(f), xy[0], xy[1], p.tile, rng)
        name = f"{stem}_neg{i}_{f:06d}"
        cv2.imwrite(str(out / "images" / split / f"{name}.jpg"), tile, [cv2.IMWRITE_JPEG_QUALITY, p.jpeg_quality])
        (out / "labels" / split / f"{name}.txt").write_text("")
    log.info("Dataset: %d positive tiles from shot %s", n_pos, shot.id)
    return n_pos


def usable_shots(session: ClipSession, min_conf: float = 0.6) -> list[Shot]:
    return [s for s in session.project.shots if s.is_complete()
            and (s.confirmed or (s.source == "auto" and (s.confidence or 0) >= min_conf))]
