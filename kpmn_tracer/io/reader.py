"""Random-access frame reader on top of the MJPEG proxy."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


class FrameReader:
    """Frame-exact reader. Every MJPEG frame is a keyframe, so seeks are exact and cheap.

    Thread-safe; keeps a small LRU cache of decoded BGR frames.
    """

    def __init__(self, path: str | Path, cache_size: int = 48) -> None:
        self.path = Path(path)
        self._cap = cv2.VideoCapture(str(self.path), cv2.CAP_FFMPEG)
        if not self._cap.isOpened():
            raise OSError(f"Cannot open {self.path}")
        self.frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.fps = float(self._cap.get(cv2.CAP_PROP_FPS))
        self._next = 0  # index the capture will return on the next read()
        self._lock = threading.Lock()
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._cache_size = cache_size

    def __len__(self) -> int:
        return self.frame_count

    def read(self, index: int) -> np.ndarray:
        """Return frame ``index`` as BGR uint8 (do not modify in place)."""
        if not 0 <= index < self.frame_count:
            raise IndexError(f"frame {index} out of range 0..{self.frame_count - 1}")
        with self._lock:
            hit = self._cache.get(index)
            if hit is not None:
                self._cache.move_to_end(index)
                return hit
            if index != self._next:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = self._cap.read()
            if not ok:
                # Some backends refuse seeks near the end; retry from scratch.
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = self._cap.read()
                if not ok:
                    raise OSError(f"Failed to read frame {index} of {self.path}")
            self._next = index + 1
            self._cache[index] = frame
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            return frame

    def gray(self, index: int) -> np.ndarray:
        return cv2.cvtColor(self.read(index), cv2.COLOR_BGR2GRAY)

    def close(self) -> None:
        with self._lock:
            self._cap.release()

    def __enter__(self) -> FrameReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
