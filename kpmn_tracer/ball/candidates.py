"""Ball candidate detection in camera-compensated (reference) coordinates.

The :class:`BallDetector` protocol is the seam for alternative detectors
(e.g. an ML model, phase 6): every detector returns :class:`Candidate`
objects in reference-frame proxy pixels, and the same tracker/fit consumes them.

:class:`ClassicDetector` (no ML): the region of interest is warped into the
reference geometry for frames ``f-k``, ``f`` and ``f+k``. A moving ball is the
only thing that differs from *both* neighbours with the same sign, so
``min(f - (f-k), f - (f+k))`` keeps bright movers (ball in front of grass)
and the mirrored expression dark movers (ball against a bright sky), while
static structure and residual noise cancel. Small, compact blobs remain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

GrayFn = Callable[[int], np.ndarray]
HFn = Callable[[int], np.ndarray]  # frame -> reference homography (proxy px)
MaskFn = Callable[[int], "np.ndarray | None"]

Roi = tuple[int, int, int, int]  # x0, y0, x1, y1 (reference coordinates, exclusive end)


@dataclass
class Candidate:
    frame: int
    x: float
    y: float
    score: float  # contrast / noise threshold (>= 1)
    area: float
    polarity: int  # +1 bright, -1 dark


class BallDetector(Protocol):
    def _invalid(self, f: int, roi: Roi) -> np.ndarray:
        x0, y0, x1, y1 = roi
        T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], float)
        ones = np.full((self.h, self.w), 255, np.uint8)
        v = cv2.warpPerspective(ones, T @ self.H(f), (x1 - x0, y1 - y0), flags=cv2.INTER_NEAREST,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return cv2.erode(v, np.ones((7, 7), np.uint8), borderType=cv2.BORDER_REPLICATE) == 0

    @staticmethod
    def _grad(img: np.ndarray) -> np.ndarray:
        f = img.astype(np.float32)
        gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        return cv2.dilate(np.sqrt(gx * gx + gy * gy), np.ones((3, 3), np.uint8)).astype(np.int16)

    def detect(self, frame: int, roi: Roi, expected_radius: float = 2.0, gap: int = 2) -> list[Candidate]:
        ...


@dataclass
class DetectorParams:
    min_contrast: float = 5.0  # grey levels
    noise_k: float = 4.0  # threshold = max(min_contrast, noise_k * robust sigma)
    max_elongation: float = 8.0  # motion-blur streaks are allowed
    max_area_factor: float = 30.0  # area <= factor * expected_radius^2 (+ streak allowance)
    edge_tolerance: float = 0.6  # px of assumed misregistration: threshold += this * local gradient


class ClassicDetector:
    def __init__(self, gray: GrayFn, H: HFn, size: tuple[int, int], frame_count: int,
                 exclude: MaskFn | None = None, params: DetectorParams | None = None) -> None:
        self.gray = gray
        self.H = H
        self.w, self.h = size
        self.n = frame_count
        self.exclude = exclude
        self.p = params or DetectorParams()

    def clip_roi(self, roi: Roi) -> Roi | None:
        x0, y0, x1, y1 = roi
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.w, int(x1)), min(self.h, int(y1))
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        return x0, y0, x1, y1

    def _warp(self, f: int, roi: Roi, mask: bool = False) -> np.ndarray:
        x0, y0, x1, y1 = roi
        T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], float)
        src = self.gray(f) if not mask else self.exclude(f)  # type: ignore[misc]
        flags = cv2.INTER_LINEAR if not mask else cv2.INTER_NEAREST
        return cv2.warpPerspective(src, T @ self.H(f), (x1 - x0, y1 - y0), flags=flags,
                                   borderMode=cv2.BORDER_REPLICATE)

    def _invalid(self, f: int, roi: Roi) -> np.ndarray:
        x0, y0, x1, y1 = roi
        T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], float)
        ones = np.full((self.h, self.w), 255, np.uint8)
        v = cv2.warpPerspective(ones, T @ self.H(f), (x1 - x0, y1 - y0), flags=cv2.INTER_NEAREST,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return cv2.erode(v, np.ones((7, 7), np.uint8), borderType=cv2.BORDER_REPLICATE) == 0

    @staticmethod
    def _grad(img: np.ndarray) -> np.ndarray:
        f = img.astype(np.float32)
        gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        return cv2.dilate(np.sqrt(gx * gx + gy * gy), np.ones((3, 3), np.uint8)).astype(np.int16)

    def detect(self, frame: int, roi: Roi, expected_radius: float = 2.0, gap: int = 2) -> list[Candidate]:
        roi_c = self.clip_roi(roi)
        if roi_c is None:
            return []
        a, b = frame - gap, frame + gap
        if a < 0:
            a = frame + 2 * gap
        if b >= self.n:
            b = frame - 2 * gap
        if not (0 <= a < self.n and 0 <= b < self.n):
            return []
        cur = self._warp(frame, roi_c).astype(np.int16)
        pa = self._warp(a, roi_c).astype(np.int16)
        pb = self._warp(b, roi_c).astype(np.int16)
        bright = np.minimum(cur - pa, cur - pb)
        dark = np.minimum(pa - cur, pb - cur)
        if self.p.edge_tolerance > 0:
            # residual misregistration/interpolation produces differences ~ gradient * shift
            g = np.maximum(self._grad(pa), self._grad(pb)) * self.p.edge_tolerance
            bright = bright - g
            dark = dark - g
        # ignore pixels that came from outside any of the three source frames
        invalid = np.zeros(cur.shape, bool)
        for f in (frame, a, b):
            invalid |= self._invalid(f, roi_c)
        bright[invalid] = 0
        dark[invalid] = 0
        if self.exclude is not None and self.exclude(frame) is not None:
            m = self._warp(frame, roi_c, mask=True) > 0
            bright[m] = 0
            dark[m] = 0
        out: list[Candidate] = []
        for pol, D in ((1, bright), (-1, dark)):
            out.extend(self._blobs(frame, D.astype(np.float32), roi_c, expected_radius, pol))
        return out

    def _blobs(self, frame: int, D: np.ndarray, roi: Roi, r: float, pol: int) -> list[Candidate]:
        pos = D[D > 0]
        sigma = 1.4826 * float(np.median(np.abs(D - np.median(D)))) if D.size else 0.0
        thr = max(self.p.min_contrast, self.p.noise_k * max(sigma, 0.5))
        if pos.size == 0 or D.max() < thr:
            return []
        bw = (D >= thr).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
        max_area = self.p.max_area_factor * max(r, 1.0) ** 2 + 40
        x0, y0 = roi[0], roi[1]
        out = []
        for i in range(1, n):
            area = stats[i, cv2.CC_STAT_AREA]
            if area > max_area:
                continue
            bx, by, bw_, bh_ = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                                stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT])
            patch = np.where(lab[by:by + bh_, bx:bx + bw_] == i, D[by:by + bh_, bx:bx + bw_], 0)
            wsum = patch.sum()
            yy, xx = np.mgrid[0:bh_, 0:bw_]
            cx = (xx * patch).sum() / wsum
            cy = (yy * patch).sum() / wsum
            if area >= 4:
                cov = np.cov(np.c_[xx[patch > 0], yy[patch > 0]].T, aweights=patch[patch > 0])
                ev = np.linalg.eigvalsh(cov)
                if ev[0] > 1e-6 and np.sqrt(ev[1] / ev[0]) > self.p.max_elongation:
                    continue
            out.append(Candidate(frame, float(x0 + bx + cx), float(y0 + by + cy),
                                 float(patch.max() / thr), float(area), pol))
        return out
