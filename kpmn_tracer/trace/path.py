"""Geometric flight path through user/auto anchors.

The path is a piecewise cubic Hermite curve ``P(u), u in [0, 1]`` through the
anchor points in order. Knots ``u_i`` follow cumulative chord length, so ``u``
is roughly proportional to arc length.

Tangent rules:

* apex anchor: horizontal tangent, so the apex really is the top of the arc
* inner anchors: Catmull-Rom (chord of neighbours)
* first / last anchor: one-sided chord, bent by ``launch_steepness`` /
  ``descent_steepness`` (0 = plain chord, 0.5 = typical golf launch/descent).
  This is what makes a 3-point manual tracer (start, apex, land) look like a
  real ball flight. Extra anchors between apex and land act as the additional
  control point for draw/fade (side curvature).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Point = tuple[float, float]


@dataclass(frozen=True)
class FlightPath:
    points: np.ndarray  # (n, 2)
    knots: np.ndarray  # (n,) in [0, 1]
    tangents: np.ndarray  # (n, 2), dP/du

    @classmethod
    def build(
        cls,
        points: list[Point] | np.ndarray,
        apex_index: int | None = None,
        launch_steepness: float = 0.5,
        descent_steepness: float = 0.4,
    ) -> FlightPath:
        P = np.asarray(points, dtype=float).reshape(-1, 2)
        n = len(P)
        if n < 2:
            raise ValueError("a flight path needs at least two anchors")
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
        seg = np.maximum(seg, 1e-6)
        knots = np.concatenate([[0.0], np.cumsum(seg)]) / seg.sum()
        m = np.zeros_like(P)
        for i in range(n):
            if i == 0:
                d = (P[1] - P[0]) / (knots[1] - knots[0])
                if n > 2:
                    d = np.array([d[0] * (1 - launch_steepness), d[1] * (1 + launch_steepness)])
            elif i == n - 1:
                d = (P[-1] - P[-2]) / (knots[-1] - knots[-2])
                if n > 2:
                    d = np.array([d[0] * (1 - descent_steepness), d[1] * (1 + descent_steepness)])
            else:
                d = (P[i + 1] - P[i - 1]) / (knots[i + 1] - knots[i - 1])
                if i == apex_index:
                    d = np.array([d[0], 0.0])
            m[i] = d
        return cls(P, knots, m)

    def evaluate(self, u: float | np.ndarray) -> np.ndarray:
        """Points at parameter(s) ``u`` (clipped to [0, 1]). Returns (k, 2)."""
        u = np.clip(np.atleast_1d(np.asarray(u, dtype=float)), 0.0, 1.0)
        idx = np.clip(np.searchsorted(self.knots, u, side="right") - 1, 0, len(self.knots) - 2)
        u0, u1 = self.knots[idx], self.knots[idx + 1]
        h = (u1 - u0)[:, None]
        s = ((u - u0) / (u1 - u0))[:, None]
        s2, s3 = s * s, s * s * s
        h00 = 2 * s3 - 3 * s2 + 1
        h10 = s3 - 2 * s2 + s
        h01 = -2 * s3 + 3 * s2
        h11 = s3 - s2
        P0, P1 = self.points[idx], self.points[idx + 1]
        M0, M1 = self.tangents[idx], self.tangents[idx + 1]
        return h00 * P0 + h10 * h * M0 + h01 * P1 + h11 * h * M1

    def sample(self, count: int = 256, u_start: float = 0.0, u_end: float = 1.0) -> np.ndarray:
        if u_end <= u_start:
            return self.evaluate(u_start)
        return self.evaluate(np.linspace(u_start, u_end, max(2, count)))
