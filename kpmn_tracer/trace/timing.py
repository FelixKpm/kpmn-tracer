"""Time -> path-parameter mapping.

Normalised flight time ``tau in [0, 1]`` (0 = impact, 1 = landing) maps to the
path parameter ``u``. Two variants:

* :class:`EasingTiming` (manual mode): speed profile
  ``v(tau) = 1 + launch_boost * exp(-tau / launch_decay) + late_boost * tau**2``
  - fast right after impact, slowest around the apex, slightly faster when the
  ball comes down. ``u = E(tau)`` is the normalised integral of ``v``.
* :class:`AnchorTiming` (auto mode / measured): every anchor carries the time
  at which the ball was there; ``u(tau)`` is a monotone PCHIP interpolation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator


@dataclass(frozen=True)
class EasingTiming:
    launch_boost: float = 2.5
    launch_decay: float = 0.12
    late_boost: float = 0.8

    def _integral(self, tau: np.ndarray) -> np.ndarray:
        a, d, b = self.launch_boost, max(self.launch_decay, 1e-6), self.late_boost
        return tau + a * d * (1.0 - np.exp(-tau / d)) + b * tau**3 / 3.0

    def u_at(self, tau: float | np.ndarray) -> np.ndarray:
        tau = np.clip(np.atleast_1d(np.asarray(tau, dtype=float)), 0.0, 1.0)
        return self._integral(tau) / self._integral(np.array([1.0]))

    def speed(self, tau: float | np.ndarray) -> np.ndarray:
        """du/dtau (useful for tests / UI preview)."""
        tau = np.atleast_1d(np.asarray(tau, dtype=float))
        a, d, b = self.launch_boost, max(self.launch_decay, 1e-6), self.late_boost
        v = 1.0 + a * np.exp(-tau / d) + b * tau**2
        return v / self._integral(np.array([1.0]))


@dataclass(frozen=True)
class AnchorTiming:
    taus: tuple[float, ...]  # normalised times of the anchors, strictly increasing
    us: tuple[float, ...]  # path parameters (knots) of the anchors

    def __post_init__(self) -> None:
        if len(self.taus) != len(self.us) or len(self.taus) < 2:
            raise ValueError("need matching tau/u pairs (>= 2)")
        if np.any(np.diff(self.taus) <= 0):
            raise ValueError("anchor times must be strictly increasing")

    def u_at(self, tau: float | np.ndarray) -> np.ndarray:
        tau = np.clip(np.atleast_1d(np.asarray(tau, dtype=float)), self.taus[0], self.taus[-1])
        f = PchipInterpolator(np.asarray(self.taus), np.asarray(self.us))
        return np.clip(f(tau), 0.0, 1.0)
