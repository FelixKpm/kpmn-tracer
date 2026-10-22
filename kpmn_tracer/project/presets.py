"""User presets stored in ``~/.kpmn_tracer`` (or ``$KPMN_HOME``).

* Tracer styles: ``styles/<name>.json``
* Position preset for a fixed tripod spot: last ball start point and the rough
  curve shape, stored *normalised* (0..1 of width/height) so it also works for
  clips with another resolution or orientation of the same setup.
* App defaults: analysis options used for new projects / batch runs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kpmn_tracer.render.style import TracerStyle
from kpmn_tracer.trace.model import Anchor, AnchorKind, Shot

log = logging.getLogger(__name__)

BUILTIN_STYLES: dict[str, TracerStyle] = {
    "TV Rot": TracerStyle(),
    "Gelb Schweif": TracerStyle(color="#ffd400", mode="tail", tail_seconds=0.8, glow_strength=1.0),
    "Weiß dezent": TracerStyle(color="#ffffff", glow_color="#7fb8ff", width=5.0, core_highlight=0.0,
                               glow_strength=0.8),
    "Blau mit Schatten": TracerStyle(color="#2aa8ff", shadow=True, width=8.0),
}


def home() -> Path:
    return Path(os.environ.get("KPMN_HOME", Path.home() / ".kpmn_tracer"))


def _safe(name: str) -> str:
    return re.sub(r"[^\w\- äöüÄÖÜß]", "_", name).strip() or "preset"


@dataclass
class PositionPreset:
    start: tuple[float, float]  # normalised
    apex: tuple[float, float] | None = None
    land: tuple[float, float] | None = None
    flight_s: float | None = None

    def apply(self, shot: Shot, width: int, height: int, fps: float) -> None:
        """Fill start (and the rough curve shape if known) into ``shot``."""
        def px(p: tuple[float, float]) -> tuple[float, float]:
            return p[0] * width, p[1] * height

        shot.set_anchor(AnchorKind.START, *px(self.start))
        if self.apex and self.land:
            shot.set_anchor(AnchorKind.APEX, *px(self.apex))
            shot.set_anchor(AnchorKind.LAND, *px(self.land))
            if self.flight_s:
                shot.land_frame = shot.impact_frame + self.flight_s * fps

    @classmethod
    def from_shot(cls, shot: Shot, width: int, height: int, fps: float) -> PositionPreset | None:
        def norm(a: Anchor | None) -> tuple[float, float] | None:
            return (a.x / width, a.y / height) if a else None

        start = norm(shot.anchor(AnchorKind.START))
        if start is None:
            return None
        return cls(start, norm(shot.anchor(AnchorKind.APEX)), norm(shot.anchor(AnchorKind.LAND)),
                   shot.flight_frames(fps) / fps if shot.is_complete() else None)


@dataclass
class AppDefaults:
    use_person_mask: bool = True
    detector: str = "classic"
    yolo_model: str | None = None
    mask_model: str = "multiclass"
    vfr_mode: str = "frames"
    export_format: str = "prores"
    last_style: str = "TV Rot"
    language: str = ""  # "de" / "en"; empty: not chosen yet (system language, asked in the tour)
    extra: dict[str, Any] = field(default_factory=dict)


class PresetStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or home()
        (self.root / "styles").mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ styles
    def style_names(self) -> list[str]:
        user = sorted(p.stem for p in (self.root / "styles").glob("*.json"))
        return list(BUILTIN_STYLES) + [n for n in user if n not in BUILTIN_STYLES]

    def load_style(self, name: str) -> TracerStyle:
        p = self.root / "styles" / f"{_safe(name)}.json"
        if p.exists():
            return TracerStyle.from_dict(json.loads(p.read_text(encoding="utf-8")))
        if name in BUILTIN_STYLES:
            return TracerStyle.from_dict(BUILTIN_STYLES[name].to_dict())
        raise KeyError(name)

    def save_style(self, name: str, style: TracerStyle) -> Path:
        p = self.root / "styles" / f"{_safe(name)}.json"
        p.write_text(json.dumps(style.to_dict(), indent=1), encoding="utf-8")
        log.info("Style preset saved: %s", p)
        return p

    def delete_style(self, name: str) -> bool:
        p = self.root / "styles" / f"{_safe(name)}.json"
        if p.exists():
            p.unlink()
            return True
        return False

    # ------------------------------------------------------------ position preset
    def save_position(self, preset: PositionPreset) -> None:
        (self.root / "position.json").write_text(json.dumps(asdict(preset)), encoding="utf-8")

    def load_position(self) -> PositionPreset | None:
        p = self.root / "position.json"
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return PositionPreset(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()})

    # ------------------------------------------------------------ defaults
    def load_defaults(self) -> AppDefaults:
        p = self.root / "settings.json"
        if not p.exists():
            return AppDefaults()
        d = json.loads(p.read_text(encoding="utf-8"))
        known = {k: v for k, v in d.items() if k in AppDefaults.__dataclass_fields__}
        return AppDefaults(**known)

    def save_defaults(self, d: AppDefaults) -> None:
        (self.root / "settings.json").write_text(json.dumps(asdict(d), indent=1), encoding="utf-8")
