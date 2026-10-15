"""Per-clip person-mask track: computed every ``stride`` frames, interpolated, cached on disk.

Masks are stored at a small analysis resolution (uint8, 0..255) in
``<cache>/masks_<model>_s<stride>.npz``; :meth:`MaskTrack.get` interpolates
between key frames and scales to any requested size.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from kpmn_tracer.io.decode import CancelFn, CancelledError, ProgressFn
from kpmn_tracer.segmentation.segmenter import PersonSegmenter

log = logging.getLogger(__name__)

FrameFn = Callable[[int], np.ndarray]


def analysis_size(w: int, h: int, long_side: int = 640) -> tuple[int, int]:
    s = min(1.0, long_side / max(w, h))
    return max(1, round(w * s)), max(1, round(h * s))


class MaskTrack:
    def __init__(self, frame_count: int, size: tuple[int, int], stride: int,
                 keys: dict[int, np.ndarray] | None = None) -> None:
        self.frame_count = frame_count
        self.size = size  # (w, h) of stored masks
        self.stride = max(1, stride)
        self.keys: dict[int, np.ndarray] = keys or {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ build / persist
    @staticmethod
    def key_frames(frame_count: int, stride: int, first: int = 0, last: int | None = None) -> list[int]:
        last = frame_count - 1 if last is None else last
        ks = list(range(first - first % stride, last + 1, stride))
        if ks and ks[-1] != last:
            ks.append(last)
        return [k for k in ks if 0 <= k < frame_count]

    def compute(self, read: FrameFn, segmenter: PersonSegmenter, first: int = 0, last: int | None = None,
                progress: ProgressFn | None = None, cancel: CancelFn | None = None) -> None:
        todo = [k for k in self.key_frames(self.frame_count, self.stride, first, last) if k not in self.keys]
        for i, k in enumerate(todo):
            if cancel is not None and cancel():
                raise CancelledError("segmentation cancelled")
            img = cv2.resize(read(k), self.size, interpolation=cv2.INTER_AREA)
            prob = segmenter.segment(img)
            with self._lock:
                self.keys[k] = np.clip(prob * 255 + 0.5, 0, 255).astype(np.uint8)
            if progress is not None:
                progress((i + 1) / len(todo))
        log.info("Person masks: %d key frames (stride %d)", len(self.keys), self.stride)

    def save(self, path: Path) -> None:
        ks = sorted(self.keys)
        tmp = path.with_name(path.stem + ".tmp.npz")
        np.savez_compressed(tmp, frames=np.array(ks, np.int32),
                            masks=np.stack([self.keys[k] for k in ks]) if ks else np.zeros((0, 1, 1), np.uint8),
                            frame_count=self.frame_count, size=np.array(self.size), stride=self.stride)
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> MaskTrack:
        d = np.load(path)
        keys = {int(k): m for k, m in zip(d["frames"], d["masks"])}
        return cls(int(d["frame_count"]), tuple(int(v) for v in d["size"]), int(d["stride"]), keys)

    # ------------------------------------------------------------ query
    def covers(self, frame: int) -> bool:
        ks = sorted(self.keys)
        return bool(ks) and ks[0] <= frame <= ks[-1]

    def get(self, frame: int, size: tuple[int, int] | None = None) -> np.ndarray | None:
        """Float32 probability [0,1] at ``size`` (w, h), interpolated between key frames."""
        with self._lock:
            if not self.keys:
                return None
            if frame in self.keys:
                m = self.keys[frame].astype(np.float32) / 255.0
            else:
                ks = np.array(sorted(self.keys))
                i = int(np.searchsorted(ks, frame))
                if i == 0 or i == len(ks):
                    return None  # outside the analysed range
                a, b = int(ks[i - 1]), int(ks[i])
                if b - a > 4 * self.stride:
                    return None  # gap (range not analysed)
                t = (frame - a) / (b - a)
                m = (self.keys[a].astype(np.float32) * (1 - t) + self.keys[b].astype(np.float32) * t) / 255.0
        if size is not None and size != self.size:
            m = cv2.resize(m, size, interpolation=cv2.INTER_LINEAR)
        return m


def tracking_exclusion(prob: np.ndarray | None, dilate_px: int = 6) -> np.ndarray | None:
    """Binary uint8 mask (255 = ignore) for feature tracking, slightly enlarged."""
    if prob is None:
        return None
    m = (prob > 0.35).astype(np.uint8) * 255
    if dilate_px > 0:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
        m = cv2.dilate(m, k)
    return m


def soft_occlusion(prob: np.ndarray | None, feather_px: float = 2.0) -> np.ndarray | None:
    """Soft-edged occlusion matte [0,1] for cutting the tracer."""
    if prob is None:
        return None
    m = np.clip((prob - 0.3) / 0.4, 0, 1).astype(np.float32)  # sharpen the probability ramp
    if feather_px > 0:
        m = cv2.GaussianBlur(m, (0, 0), feather_px)
    return m
