"""Physically motivated 2-D flight model and robust fitting.

A ball on a (drag-free) parabola in 3-D, seen by a pinhole camera, projects to

    x(t) = (Sx + a1 t + a2 t^2) / (1 + c t)
    y(t) = (Sy + b1 t + b2 t^2) / (1 + c t)

with ``t`` in frames since impact, ``(Sx, Sy)`` the start point (fixed) and a
*shared* denominator (depth grows linearly in time). ``c > 0``: ball flies away
from the camera (the typical behind-the-golfer view), ``c = 0`` reduces to a
screen-space parabola. Lateral curvature (draw/fade) lives in ``a2``. The
model is linear in ``(a1, a2, b1, b2, c)`` after multiplying by the
denominator, which makes RANSAC cheap; a robust non-linear refinement on the
true pixel residuals follows.

Landing: the ball starts on the ground at height ``Y = H`` (camera frame).
With principal point ``cy`` the numerator of ``y - cy`` is proportional to
``Y(t)``, so ``Y(t) = H`` again at ``t_land = (cy*c - b1) / b2``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares


@dataclass
class FlightModel:
    start: tuple[float, float]
    a1: float
    a2: float
    b1: float
    b2: float
    c: float

    @property
    def params(self) -> np.ndarray:
        return np.array([self.a1, self.a2, self.b1, self.b2, self.c])

    @classmethod
    def from_params(cls, start: tuple[float, float], p: np.ndarray) -> FlightModel:
        return cls(start, *map(float, p))

    def __call__(self, t: float | np.ndarray) -> np.ndarray:
        t = np.atleast_1d(np.asarray(t, float))
        den = 1.0 + self.c * t
        x = (self.start[0] + self.a1 * t + self.a2 * t * t) / den
        y = (self.start[1] + self.b1 * t + self.b2 * t * t) / den
        return np.c_[x, y]

    def valid_until(self) -> float:
        """Largest t with a positive denominator (inf for c >= 0)."""
        return np.inf if self.c >= 0 else -0.95 / self.c

    def apex_time(self, t_max: float) -> float:
        ts = np.linspace(0, t_max, max(50, int(t_max * 8)))
        return float(ts[int(np.argmin(self(ts)[:, 1]))])

    def landing_time(self, cy: float) -> float | None:
        """Time when the ball is back at ground height (None if the model never comes down)."""
        if self.b2 <= 1e-9:
            return None
        t = (cy * self.c - self.b1) / self.b2
        return float(t) if t > 0 and t < self.valid_until() else None


def _linear_system(t: np.ndarray, xy: np.ndarray, start: tuple[float, float],
                   w: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    sx, sy = start
    n = len(t)
    A = np.zeros((2 * n, 5))
    b = np.zeros(2 * n)
    A[0::2, 0], A[0::2, 1], A[0::2, 4] = t, t * t, -t * xy[:, 0]
    A[1::2, 2], A[1::2, 3], A[1::2, 4] = t, t * t, -t * xy[:, 1]
    b[0::2] = xy[:, 0] - sx
    b[1::2] = xy[:, 1] - sy
    if w is not None:
        ww = np.repeat(w, 2)
        A, b = A * ww[:, None], b * ww
    return A, b


def fit_linear(t: np.ndarray, xy: np.ndarray, start: tuple[float, float], perspective: bool = True,
               w: np.ndarray | None = None) -> FlightModel | None:
    A, b = _linear_system(t, xy, start, w)
    if not perspective:
        A = A[:, :4]
    if A.shape[0] < A.shape[1]:
        return None
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    p = np.r_[sol, 0.0] if not perspective else sol
    return FlightModel.from_params(start, p)


def residuals(m: FlightModel, t: np.ndarray, xy: np.ndarray) -> np.ndarray:
    return np.linalg.norm(m(t) - xy, axis=1)


@dataclass
class FitResult:
    model: FlightModel
    inliers: np.ndarray  # bool per point
    rms: float  # px, on inliers


def ransac_fit(t: np.ndarray, xy: np.ndarray, start: tuple[float, float], tol: float = 2.5,
               iters: int = 300, perspective: bool = True, seed: int = 0,
               sample_weights: np.ndarray | None = None) -> FitResult | None:
    """Robust fit: RANSAC on the linearised model, then soft-L1 refinement on pixel residuals."""
    t = np.asarray(t, float)
    xy = np.asarray(xy, float)
    n = len(t)
    k = 3 if perspective else 2
    if n < k:
        return None
    rng = np.random.default_rng(seed)
    prob = None
    if sample_weights is not None:
        prob = np.asarray(sample_weights, float)
        prob = prob / prob.sum()
    best_inl, best_cnt, best_err = None, -1, np.inf
    for _ in range(iters if n > k else 1):
        try:
            idx = rng.choice(n, k, replace=False, p=prob)
        except ValueError:  # fewer non-zero weights than k
            idx = rng.choice(n, k, replace=False)
        if len(set(t[idx])) < k:
            continue  # need k distinct times
        m = fit_linear(t[idx], xy[idx], start, perspective)
        if m is None or (perspective and m.c < -0.9 / max(t.max(), 1)):
            continue
        r = residuals(m, t, xy)
        inl = r < tol
        cnt, err = int(inl.sum()), float(np.minimum(r, tol).sum())
        if cnt > best_cnt or (cnt == best_cnt and err < best_err):
            best_inl, best_cnt, best_err = inl, cnt, err
    if best_inl is None or best_cnt < k:
        return None
    m = fit_linear(t[best_inl], xy[best_inl], start, perspective)
    if m is None:
        return None
    for _ in range(2):  # refine and re-select inliers
        m = refine(m, t[best_inl], xy[best_inl], perspective)
        best_inl = residuals(m, t, xy) < tol
        if best_inl.sum() < k:
            return None
    r = residuals(m, t[best_inl], xy[best_inl])
    return FitResult(m, best_inl, float(np.sqrt(np.mean(r * r))))


def refine(m: FlightModel, t: np.ndarray, xy: np.ndarray, perspective: bool = True) -> FlightModel:
    if len(t) < (5 if perspective else 4) // 2 + 1:
        return m
    t_max = float(t.max())

    def fun(p: np.ndarray) -> np.ndarray:
        q = p if perspective else np.r_[p, 0.0]
        return (FlightModel.from_params(m.start, q)(t) - xy).ravel()

    p0 = m.params if perspective else m.params[:4]
    lb = np.full(p0.shape, -np.inf)
    ub = np.full(p0.shape, np.inf)
    if perspective:
        lb[4] = -0.9 / max(t_max, 1.0)
        p0[4] = max(p0[4], lb[4] + 1e-6)
    res = least_squares(fun, p0, bounds=(lb, ub), loss="soft_l1", f_scale=1.0, max_nfev=200)
    q = res.x if perspective else np.r_[res.x, 0.0]
    return FlightModel.from_params(m.start, q)
