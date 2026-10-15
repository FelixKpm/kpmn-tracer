"""Club-impact sounds: short, loud, broadband transients.

Pipeline: high-pass (removes wind, voices, hum) -> 1 ms log-energy envelope
-> sharp rise above the local noise floor -> peak picking with a minimum
distance -> sample-accurate onset time (first sample above a fraction of
the peak).
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.ndimage import maximum_filter1d, median_filter
from scipy.signal import butter, sosfiltfilt

log = logging.getLogger(__name__)


@dataclass
class OnsetParams:
    highpass_hz: float = 1500.0
    hop_ms: float = 1.0
    rise_ms: float = 4.0  # rise is measured over this lag
    min_rise_db: float = 12.0
    min_prominence_db: float = 18.0  # peak above the rolling noise floor
    floor_window_s: float = 1.0
    min_distance_s: float = 0.25  # echo suppression; neighbouring bays can hit 0.4 s apart
    onset_fraction: float = 0.25  # onset = first sample above this fraction of the peak amplitude


@dataclass
class Onset:
    time: float  # seconds from the start of the signal
    prominence_db: float
    rise_db: float

    @property
    def strength(self) -> float:
        """0..1 score (saturates around 40 dB prominence)."""
        return float(np.clip((self.prominence_db - 10.0) / 30.0, 0.0, 1.0))


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        sr, n, ch, sw = wf.getframerate(), wf.getnframes(), wf.getnchannels(), wf.getsampwidth()
        raw = wf.readframes(n)
    if sw != 2:
        raise ValueError("expected 16-bit PCM")
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def detect_onsets(x: np.ndarray, sr: int, p: OnsetParams | None = None) -> list[Onset]:
    p = p or OnsetParams()
    if x.size < sr // 10:
        return []
    sos = butter(4, p.highpass_hz, btype="highpass", fs=sr, output="sos")
    hp = sosfiltfilt(sos, x.astype(np.float64))
    hop = max(1, int(round(sr * p.hop_ms / 1000)))
    n = hp.size // hop
    energy = (hp[: n * hop] ** 2).reshape(n, hop).mean(axis=1)
    env = 10 * np.log10(energy + 1e-12)
    lag = max(1, int(round(p.rise_ms / p.hop_ms)))
    rise = np.zeros_like(env)
    rise[lag:] = env[lag:] - env[:-lag]
    win = max(3, int(p.floor_window_s * 1000 / p.hop_ms) | 1)
    floor = median_filter(env, size=win, mode="nearest")
    # local peak level shortly after the rise
    peak_level = maximum_filter1d(env, size=2 * lag + 1, origin=-lag)
    prom = peak_level - floor
    cand = np.flatnonzero((rise >= p.min_rise_db) & (prom >= p.min_prominence_db))
    if cand.size == 0:
        return []
    # one candidate per event: strongest rise in each cluster
    events: list[int] = []
    start = cand[0]
    best = cand[0]
    for c in cand[1:]:
        if c - start > lag * 4:
            events.append(best)
            start = best = c
        elif rise[c] > rise[best]:
            best = c
    events.append(best)
    # enforce minimum distance (keep the more prominent one)
    events.sort(key=lambda i: -prom[i])
    min_d = p.min_distance_s * 1000 / p.hop_ms
    kept: list[int] = []
    for e in events:
        if all(abs(e - k) >= min_d for k in kept):
            kept.append(e)
    out = []
    for e in sorted(kept):
        out.append(Onset(_onset_time(hp, sr, e * hop, hop, lag, p), float(prom[e]), float(rise[e])))
    log.info("Audio: %d impact-like transients", len(out))
    return out


def _onset_time(hp: np.ndarray, sr: int, idx: int, hop: int, lag: int, p: OnsetParams) -> float:
    """Sample-accurate onset: first sample above ``onset_fraction`` of the local peak."""
    a = max(0, idx - (lag + 2) * hop)
    b = min(hp.size, idx + (2 * lag + 4) * hop)
    seg = np.abs(hp[a:b])
    if seg.size == 0:
        return idx / sr
    thr = p.onset_fraction * seg.max()
    first = int(np.argmax(seg >= thr))
    return (a + first) / sr
