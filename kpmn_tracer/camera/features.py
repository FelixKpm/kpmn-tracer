"""Feature detection and robust Lucas-Kanade tracking."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class FeatureParams:
    max_corners: int = 1200
    quality: float = 0.005
    min_distance: int = 9
    block_size: int = 7
    border: int = 12  # ignore image borders (warp artefacts, vignetting)
    lk_win: int = 21
    lk_levels: int = 4
    fb_max_error: float = 0.7  # forward-backward consistency threshold (px)


def detect(gray: np.ndarray, p: FeatureParams, exclude: np.ndarray | None = None,
           valid: np.ndarray | None = None) -> np.ndarray:
    """Corners as float32 (n, 2). ``exclude``: uint8 mask (>0 = do not use, e.g. person)."""
    h, w = gray.shape
    mask = np.zeros((h, w), np.uint8)
    b = p.border
    mask[b:h - b, b:w - b] = 255
    if valid is not None:
        mask &= valid
    if exclude is not None:
        grown = cv2.dilate((exclude > 0).astype(np.uint8), np.ones((15, 15), np.uint8))
        mask[grown > 0] = 0
    pts = cv2.goodFeaturesToTrack(gray, p.max_corners, p.quality, p.min_distance,
                                  mask=mask, blockSize=p.block_size)
    if pts is None:
        return np.zeros((0, 2), np.float32)
    return pts.reshape(-1, 2).astype(np.float32)


def track(prev: np.ndarray, nxt: np.ndarray, pts: np.ndarray, p: FeatureParams,
          init: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Track ``pts`` from ``prev`` to ``nxt`` with forward-backward check.

    Returns (pts_next (n,2), ok (n,) bool).
    """
    n = len(pts)
    if n == 0:
        return pts.copy(), np.zeros(0, bool)
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01)
    kw = dict(winSize=(p.lk_win, p.lk_win), maxLevel=p.lk_levels, criteria=crit)
    p0 = pts.reshape(-1, 1, 2).astype(np.float32)
    flags = 0
    p1_init = None
    if init is not None:
        p1_init = init.reshape(-1, 1, 2).astype(np.float32).copy()
        flags = cv2.OPTFLOW_USE_INITIAL_FLOW
    p1, st1, _ = cv2.calcOpticalFlowPyrLK(prev, nxt, p0, p1_init, flags=flags, **kw)
    p0b, st2, _ = cv2.calcOpticalFlowPyrLK(nxt, prev, p1, p0.copy(),
                                           flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **kw)
    fb = np.linalg.norm((p0 - p0b).reshape(-1, 2), axis=1)
    ok = (st1.ravel() == 1) & (st2.ravel() == 1) & (fb < p.fb_max_error)
    h, w = nxt.shape
    q = p1.reshape(-1, 2)
    ok &= (q[:, 0] >= 0) & (q[:, 0] < w) & (q[:, 1] >= 0) & (q[:, 1] < h)
    return q, ok
