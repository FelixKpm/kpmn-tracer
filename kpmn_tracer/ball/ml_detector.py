"""Optional ML ball detector (Ultralytics YOLO) behind the same :class:`BallDetector` interface.

Not required for the app: ``ultralytics`` (AGPL-3.0, pulls in PyTorch) is only
imported when a YOLO model is actually configured. Inference runs on the CPU by
default; a CUDA GPU is used when available and ``device="auto"``.

The detector looks at the *stabilised* region of interest (same warp as the
classic detector), so its candidates are in reference coordinates and flow
into the identical tracker / flight fit. :class:`CombinedDetector` merges the
candidates of several detectors (e.g. classic + YOLO).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np

from kpmn_tracer.ball.candidates import BallDetector, Candidate, GrayFn, HFn, Roi

log = logging.getLogger(__name__)

FrameFn = GrayFn  # returns BGR here


class YoloModel(Protocol):
    def predict(self, source: Any, **kwargs: Any) -> Any: ...


def load_yolo(model_path: str | Path) -> YoloModel:
    try:
        from ultralytics import YOLO
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("ML-Erkennung braucht das optionale Paket 'ultralytics' "
                           "(pip install -r requirements-ml.txt)") from exc
    return YOLO(str(model_path))


def pick_device(device: str = "auto") -> str:
    if device != "auto":
        return device
    try:  # pragma: no cover - depends on installed torch
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


class YoloDetector:
    def __init__(self, frame: FrameFn, H: HFn, size: tuple[int, int], frame_count: int,
                 model: YoloModel, conf: float = 0.15, imgsz: int = 320, device: str = "auto",
                 overlap: int = 32) -> None:
        self.frame = frame
        self.H = H
        self.w, self.h = size
        self.n = frame_count
        self.model = model
        self.conf = conf
        self.imgsz = imgsz
        self.overlap = overlap
        self.device = pick_device(device)

    def _warp(self, f: int, roi: Roi) -> np.ndarray:
        x0, y0, x1, y1 = roi
        T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], float)
        img = self.frame(f)
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        return cv2.warpPerspective(img, T @ self.H(f), (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_REPLICATE)

    def detect(self, frame: int, roi: Roi, expected_radius: float = 2.0, gap: int = 2) -> list[Candidate]:
        rx0, ry0, rx1, ry1 = roi
        if not 0 <= frame < self.n:
            return []
        # never feed less than one native tile (the model must not see an upscaled ball)
        cx, cy = (rx0 + rx1) / 2, (ry0 + ry1) / 2
        half_w, half_h = max((rx1 - rx0) / 2, self.imgsz / 2), max((ry1 - ry0) / 2, self.imgsz / 2)
        x0 = int(max(0, min(cx - half_w, self.w - 2 * half_w)))
        y0 = int(max(0, min(cy - half_h, self.h - 2 * half_h)))
        x1, y1 = int(min(self.w, x0 + 2 * half_w)), int(min(self.h, y0 + 2 * half_h))
        if x1 - x0 < 8 or y1 - y0 < 8:
            return []
        crop = self._warp(frame, (x0, y0, x1, y1))
        # native-resolution tiles (the ball is only a few pixels; never downscale it)
        t, step = self.imgsz, max(1, self.imgsz - self.overlap)
        H_, W_ = crop.shape[:2]
        tiles, offs = [], []
        for ty in range(0, max(1, H_ - self.overlap), step):
            for tx in range(0, max(1, W_ - self.overlap), step):
                ty0, tx0 = min(ty, max(0, H_ - t)), min(tx, max(0, W_ - t))
                tiles.append(crop[ty0:ty0 + t, tx0:tx0 + t])
                offs.append((tx0, ty0))
        res = self.model.predict(tiles, conf=self.conf, imgsz=self.imgsz, device=self.device, verbose=False)
        out: list[Candidate] = []
        for r, (ox, oy) in zip(res, offs):
            boxes = r.boxes
            xyxy = np.asarray(boxes.xyxy.cpu() if hasattr(boxes.xyxy, "cpu") else boxes.xyxy, float)
            confs = np.asarray(boxes.conf.cpu() if hasattr(boxes.conf, "cpu") else boxes.conf, float)
            for (bx0, by0, bx1, by1), c in zip(xyxy.reshape(-1, 4), confs.ravel()):
                area = max(1.0, (bx1 - bx0) * (by1 - by0) * np.pi / 4)
                out.append(Candidate(frame, x0 + ox + (bx0 + bx1) / 2, y0 + oy + (by0 + by1) / 2,
                                     float(1.0 + 9.0 * c), float(area), 0))
        # back to the requested window; tiles overlap: drop duplicates
        out = [c for c in out if rx0 <= c.x < rx1 and ry0 <= c.y < ry1]
        out.sort(key=lambda c: -c.score)
        kept: list[Candidate] = []
        for c in out:
            if all(np.hypot(c.x - k.x, c.y - k.y) >= 2.5 for k in kept):
                kept.append(c)
        return kept


class CombinedDetector:
    """Union of several detectors; near-duplicates (< ``merge_px``) keep the best score."""

    def __init__(self, detectors: list[BallDetector], merge_px: float = 2.5) -> None:
        self.detectors = detectors
        self.merge_px = merge_px

    def detect(self, frame: int, roi: Roi, expected_radius: float = 2.0, gap: int = 2) -> list[Candidate]:
        allc = [c for d in self.detectors for c in d.detect(frame, roi, expected_radius, gap)]
        allc.sort(key=lambda c: -c.score)
        kept: list[Candidate] = []
        for c in allc:
            if all(np.hypot(c.x - k.x, c.y - k.y) >= self.merge_px for k in kept):
                kept.append(c)
        return kept
