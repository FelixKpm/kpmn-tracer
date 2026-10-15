"""Homography helpers: robust estimation, point mapping, corner parametrisation."""

from __future__ import annotations

import cv2
import numpy as np


def apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, float).reshape(-1, 2)
    hom = np.c_[pts, np.ones(len(pts))] @ np.asarray(H, float).T
    return hom[:, :2] / hom[:, 2:3]


def estimate(src: np.ndarray, dst: np.ndarray, thresh: float = 1.5) -> tuple[np.ndarray | None, np.ndarray]:
    """Robust homography mapping ``src`` -> ``dst``. Returns (H or None, inlier mask)."""
    if len(src) < 8:
        return None, np.zeros(len(src), bool)
    H, inl = cv2.findHomography(src.astype(np.float32), dst.astype(np.float32),
                                cv2.USAC_MAGSAC, thresh, maxIters=4000, confidence=0.999)
    if H is None:
        return None, np.zeros(len(src), bool)
    inl = inl.ravel().astype(bool)
    if inl.sum() >= 8:  # least-squares refit on inliers for sub-pixel accuracy
        H2, _ = cv2.findHomography(src[inl].astype(np.float32), dst[inl].astype(np.float32), 0)
        if H2 is not None:
            H = H2
    return H / H[2, 2], inl


def corners(w: int, h: int) -> np.ndarray:
    return np.array([[0, 0], [w, 0], [w, h], [0, h]], float)


def to_params(Hs: np.ndarray, w: int, h: int) -> np.ndarray:
    """(n,3,3) -> (n,8): where the four image corners are mapped. Smooth, well-conditioned."""
    c = corners(w, h)
    return np.stack([apply_h(H, c).ravel() for H in Hs])


def from_params(params: np.ndarray, w: int, h: int) -> np.ndarray:
    c = corners(w, h).astype(np.float32)
    out = []
    for p in params:
        H = cv2.getPerspectiveTransform(c, p.reshape(4, 2).astype(np.float32))
        out.append(H / H[2, 2])
    return np.stack(out)


def corner_displacement(H: np.ndarray, w: int, h: int) -> float:
    """Max distance an image corner moves under ``H`` (0 for identity)."""
    c = corners(w, h)
    return float(np.max(np.linalg.norm(apply_h(H, c) - c, axis=1)))
