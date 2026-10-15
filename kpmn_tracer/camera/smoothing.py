"""Camera-path cleanup: outlier rejection + confidence-weighted Kalman (RTS) smoothing.

The path is parametrised by the positions of the four image corners (8 values
per frame). A constant-velocity Kalman filter runs forward, a
Rauch-Tung-Striebel pass backward. Measurement noise scales with
``1 / confidence``, so well-tracked frames are kept almost exactly (real hand
shake must stay in the path - the tracer has to follow it), while
low-confidence frames and outliers get bridged from their neighbours.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from kpmn_tracer.camera.homography import from_params, to_params


@dataclass
class SmoothParams:
    process_accel: float = 10.0  # expected camera acceleration (px/frame^2) -> process noise
    meas_sigma: float = 0.05  # px registration noise at confidence 1
    min_conf: float = 0.15  # below: measurement ignored
    outlier_sigmas: float = 6.0
    outlier_min_px: float = 4.0


def _spike_magnitude(x: np.ndarray) -> np.ndarray:
    dev = np.zeros_like(x)
    dev[1:-1] = x[1:-1] - 0.5 * (x[:-2] + x[2:])
    dev[0] = x[0] - (2 * x[1] - x[2])  # linear extrapolation at the ends
    dev[-1] = x[-1] - (2 * x[-2] - x[-3])
    return np.max(np.abs(dev), axis=1)


def spike_outliers(x: np.ndarray, p: SmoothParams) -> np.ndarray:
    """Boolean (n,) - frames that jump away from both neighbours (isolated spikes).

    Uses the deviation from the neighbours' mean (a second difference) against a
    *global* robust scale, so genuine high-frequency hand shake is not rejected.
    Spikes are removed one at a time (largest first) so a spike does not also
    flag its neighbours.
    """
    n = len(x)
    out = np.zeros(n, bool)
    if n < 5:
        return out
    x = x.copy()
    mag = _spike_magnitude(x)
    med = np.median(mag)
    thr = max(med + p.outlier_sigmas * 1.4826 * np.median(np.abs(mag - med)), p.outlier_min_px)
    for _ in range(max(1, n // 4)):
        i = int(np.argmax(mag))
        if mag[i] <= thr:
            break
        out[i] = True
        good = np.flatnonzero(~out)
        for c in range(x.shape[1]):
            x[i, c] = np.interp(i, good, x[good, c])
        mag = _spike_magnitude(x)
        mag[out] = 0
    return out


def rts_smooth(z: np.ndarray, r: np.ndarray, q: float) -> np.ndarray:
    """Constant-velocity RTS smoother for independent channels.

    z: (n, k) measurements, r: (n,) measurement variance (inf = missing), q: accel. variance.
    """
    n, k = z.shape
    F = np.array([[1.0, 1.0], [0.0, 1.0]])
    Q = q * np.array([[0.25, 0.5], [0.5, 1.0]])
    xs = np.zeros((n, k, 2))
    Ps = np.zeros((n, 2, 2))
    xp_all = np.zeros((n, k, 2))
    Pp_all = np.zeros((n, 2, 2))
    first = int(np.argmax(np.isfinite(r))) if np.isfinite(r).any() else 0
    x = np.stack([z[first], np.zeros(k)], axis=1)
    P = np.diag([1e6, 1e6])
    for i in range(n):
        if i > 0:
            x = x @ F.T
            P = F @ P @ F.T + Q
        xp_all[i], Pp_all[i] = x, P
        if np.isfinite(r[i]):
            S = P[0, 0] + r[i]
            K = P[:, 0] / S
            x = x + np.outer(z[i] - x[:, 0], K)
            P = P - np.outer(K, P[0, :])
        xs[i], Ps[i] = x, P
    out = xs.copy()
    for i in range(n - 2, -1, -1):
        C = Ps[i] @ F.T @ np.linalg.inv(Pp_all[i + 1])
        out[i] = xs[i] + (out[i + 1] - xp_all[i + 1]) @ C.T
    return out[:, :, 0]


def smooth_path(
    Hs: np.ndarray, conf: np.ndarray, w: int, h: int, ref_index: int | None = None,
    p: SmoothParams | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (smoothed homographies, confidence with outliers set to 0)."""
    p = p or SmoothParams()
    if len(Hs) < 3:
        return Hs, conf
    x = to_params(Hs, w, h)
    conf = conf.copy()
    conf[spike_outliers(x, p)] = 0.0
    if ref_index is not None:
        conf[ref_index] = 1.0
    r = np.where(conf >= p.min_conf, p.meas_sigma**2 / np.maximum(conf, 1e-6) ** 2, np.inf)
    if ref_index is not None:
        r[ref_index] = 1e-8  # the reference frame is exact by definition
    xs = rts_smooth(x, r, p.process_accel**2)
    out = from_params(xs, w, h)
    if ref_index is not None:
        out[ref_index] = np.eye(3)
    return out, conf
