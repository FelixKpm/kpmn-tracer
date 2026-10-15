"""Camera tracking: per-frame homography to the reference (impact) frame.

Algorithm (outward from the reference frame, forward and backward):

1. Track features frame-to-frame with LK and estimate ``H(f -> f-1)``;
   chaining gives a prediction of ``H(f -> ref)``.
2. Re-register directly against the reference: warp frame ``f`` with the
   prediction into reference geometry and track the reference features into
   it. The residual homography corrects the prediction - this removes drift
   (done every ``refine_every`` frames, default every frame).
3. Confidence = RANSAC inlier ratio of the direct registration (damped when
   fewer than 60 points support it).
4. Outliers are rejected and the path is smoothed (see ``smoothing``).

All of this happens in proxy pixels; :func:`track_shot_camera` converts the
result to source pixels and stores it in the shot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

from kpmn_tracer.camera import features as ft
from kpmn_tracer.camera.homography import apply_h, corner_displacement, estimate
from kpmn_tracer.camera.smoothing import SmoothParams, smooth_path
from kpmn_tracer.io.decode import CancelFn, CancelledError, ProgressFn

log = logging.getLogger(__name__)

GrayFn = Callable[[int], np.ndarray]
MaskFn = Callable[[int], "np.ndarray | None"]


@dataclass
class TrackParams:
    features: ft.FeatureParams = field(default_factory=ft.FeatureParams)
    smooth: SmoothParams = field(default_factory=SmoothParams)
    refine_every: int = 1
    ransac_thresh: float = 1.5
    min_inliers: int = 15
    tripod_threshold_px: float = 0.6  # max corner motion for tripod mode (proxy px)
    tripod_samples: int = 10
    smoothing: bool = True


@dataclass
class TrackResult:
    first: int
    homographies: np.ndarray  # (n,3,3) frame -> ref, proxy pixels
    confidence: np.ndarray  # (n,)
    mode: str  # "tripod" | "tracked"

    def H(self, frame: int) -> np.ndarray:
        return self.homographies[frame - self.first]


class CameraTracker:
    def __init__(self, gray: GrayFn, size: tuple[int, int], mask: MaskFn | None = None,
                 params: TrackParams | None = None) -> None:
        self.gray = gray
        self.w, self.h = size
        self.mask = mask or (lambda _f: None)
        self.p = params or TrackParams()

    # ---------------------------------------------------------------- tripod check
    def is_tripod(self, ref: int, first: int, last: int) -> bool:
        """Quick check: register a few sampled frames directly against ``ref``."""
        ref_img = self.gray(ref)
        pts = ft.detect(ref_img, self.p.features, self.mask(ref))
        if len(pts) < self.p.min_inliers:
            return False
        frames = np.unique(np.linspace(first, last, self.p.tripod_samples).round().astype(int))
        for f in frames:
            if f == ref:
                continue
            q, ok = ft.track(ref_img, self.gray(f), pts, self.p.features)
            if ok.sum() < self.p.min_inliers:
                return False
            H, inl = estimate(pts[ok], q[ok], self.p.ransac_thresh)
            if H is None or corner_displacement(H, self.w, self.h) > self.p.tripod_threshold_px:
                return False
        return True

    # ---------------------------------------------------------------- full track
    def track(self, ref: int, first: int, last: int, progress: ProgressFn | None = None,
              cancel: CancelFn | None = None, detect_tripod: bool = True) -> TrackResult:
        first, last = min(first, ref), max(last, ref)
        n = last - first + 1
        if detect_tripod and self.is_tripod(ref, first, last):
            log.info("Camera static (tripod) - tracking skipped")
            return TrackResult(first, np.repeat(np.eye(3)[None], n, 0), np.ones(n), "tripod")

        Hs = np.repeat(np.eye(3)[None], n, 0)
        conf = np.zeros(n)
        conf[ref - first] = 1.0
        ref_img = self.gray(ref)
        ref_pts = ft.detect(ref_img, self.p.features, self.mask(ref))
        done = [0]

        def tick() -> None:
            done[0] += 1
            if cancel is not None and cancel():
                raise CancelledError("camera tracking cancelled")
            if progress is not None and done[0] % 5 == 0:
                progress(done[0] / n)

        for direction in (1, -1):
            stop = last if direction == 1 else first
            prev_f = ref
            prev_img = ref_img
            prev_pts = ref_pts.copy()
            H_prev = np.eye(3)
            for f in range(ref + direction, stop + direction, direction):
                img = self.gray(f)
                H_pred, c_pred = self._frame_to_frame(prev_img, img, prev_pts, H_prev, f)
                H, c = H_pred, c_pred * 0.5
                if (abs(f - ref) % self.p.refine_every) == 0:
                    H_ref, c_ref = self._refine_against_ref(ref_img, ref_pts, img, H_pred)
                    if H_ref is not None:
                        H, c = H_ref, c_ref
                Hs[f - first] = H
                conf[f - first] = c
                prev_img, H_prev, prev_f = img, H, f
                prev_pts = ft.detect(img, self.p.features, self.mask(f))
                tick()
            _ = prev_f
        if self.p.smoothing:
            Hs, conf = smooth_path(Hs, conf, self.w, self.h, ref - first, self.p.smooth)
        if progress is not None:
            progress(1.0)
        return TrackResult(first, Hs, conf, "tracked")

    def _frame_to_frame(self, prev_img: np.ndarray, img: np.ndarray, prev_pts: np.ndarray,
                        H_prev: np.ndarray, f: int) -> tuple[np.ndarray, float]:
        """Chain prediction: H(f->ref) = H(prev->ref) @ H(f->prev)."""
        q, ok = ft.track(prev_img, img, prev_pts, self.p.features)
        exclude = self.mask(f)
        if exclude is not None and ok.any():
            qi = np.clip(q.round().astype(int), 0, [self.w - 1, self.h - 1])
            ok &= exclude[qi[:, 1], qi[:, 0]] == 0
        if ok.sum() < self.p.min_inliers:
            return H_prev, 0.0
        H_fp, inl = estimate(q[ok], prev_pts[ok], self.p.ransac_thresh)
        if H_fp is None:
            return H_prev, 0.0
        return H_prev @ H_fp, float(inl.mean())

    def _refine_against_ref(self, ref_img: np.ndarray, ref_pts: np.ndarray, img: np.ndarray,
                            H_pred: np.ndarray) -> tuple[np.ndarray | None, float]:
        """Warp ``img`` into the reference with ``H_pred`` and register the residual."""
        warped = cv2.warpPerspective(img, H_pred, (self.w, self.h), flags=cv2.INTER_LINEAR,
                                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        valid = cv2.warpPerspective(np.full_like(img, 255), H_pred, (self.w, self.h),
                                    flags=cv2.INTER_NEAREST, borderValue=0)
        valid = cv2.erode(valid, np.ones((25, 25), np.uint8))
        if len(ref_pts) == 0:
            return None, 0.0
        ri = np.clip(ref_pts.round().astype(int), 0, [self.w - 1, self.h - 1])
        sel = valid[ri[:, 1], ri[:, 0]] > 0
        pts = ref_pts[sel]
        if len(pts) < self.p.min_inliers:
            return None, 0.0
        q, ok = ft.track(ref_img, warped, pts, self.p.features)
        if ok.sum() < self.p.min_inliers:
            return None, 0.0
        # residual R maps warped-image coords -> reference coords
        R, inl = estimate(q[ok], pts[ok], self.p.ransac_thresh)
        if R is None or inl.sum() < self.p.min_inliers:
            return None, 0.0
        # geometric agreement of the tracked points, damped when few points support it
        conf = float(inl.sum() / ok.sum()) * min(1.0, inl.sum() / 60.0)
        return R @ H_pred, conf


def track_range_for_shot(impact: int, flight_frames: float, fps: float, frame_count: int,
                         pre_s: float = 0.5, post_s: float = 2.5) -> tuple[int, int]:
    first = max(0, int(impact - pre_s * fps))
    last = min(frame_count - 1, int(np.ceil(impact + flight_frames + post_s * fps)))
    return first, last


def result_to_source(res: TrackResult, sx: float, sy: float) -> tuple[list, list]:
    """Convert proxy-pixel homographies to source pixels (S^-1 H S with S = diag(sx, sy))."""
    S = np.diag([sx, sy, 1.0])
    Si = np.linalg.inv(S)
    Hs = [(Si @ H @ S).tolist() for H in res.homographies]
    return Hs, [float(c) for c in res.confidence]


def project_points(res: TrackResult, frame: int, pts_ref: np.ndarray) -> np.ndarray:
    """Reference -> frame coordinates (proxy pixels)."""
    return apply_h(np.linalg.inv(res.H(frame)), pts_ref)
