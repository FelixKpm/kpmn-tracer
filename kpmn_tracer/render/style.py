"""Tracer style (serialisable, also used for presets)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

# Sizes are given for a 1080-pixel short side and scaled to the clip.
REFERENCE_SHORT_SIDE = 1080


@dataclass
class TracerStyle:
    color: str = "#ff2a2a"
    width: float = 7.0  # core line width at the start of the path (px @1080)
    taper: float = 0.6  # 0 = constant width, 1 = zero width at the ball end
    opacity: float = 1.0
    core_highlight: float = 0.6  # white-hot inner line (0 = off)
    glow_color: str | None = None  # None = same as color
    glow_radius: float = 14.0  # px @1080 (gaussian sigma)
    glow_strength: float = 1.2  # 0 = off
    shadow: bool = False
    shadow_opacity: float = 0.45
    shadow_offset: tuple[float, float] = (3.0, 4.0)
    shadow_blur: float = 4.0
    mode: str = "full"  # "full" = path stays, "tail" = short trail behind the ball
    tail_seconds: float = 0.6
    head_dot: bool = True  # small bright ball at the head while in flight
    hold_seconds: float = 0.8  # keep full tracer after landing
    fade_out_seconds: float = 1.0

    def scale_for(self, width: int, height: int) -> float:
        return min(width, height) / REFERENCE_SHORT_SIDE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["shadow_offset"] = list(self.shadow_offset)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TracerStyle:
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in d.items() if k in names}
        if "shadow_offset" in kw:
            kw["shadow_offset"] = tuple(kw["shadow_offset"])
        return cls(**kw)


def hex_to_rgb(color: str) -> tuple[float, float, float]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return (int(c[0:2], 16) / 255.0, int(c[2:4], 16) / 255.0, int(c[4:6], 16) / 255.0)
