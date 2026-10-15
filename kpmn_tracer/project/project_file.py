"""Per-clip project file ``<clip>.kpmntrace.json``.

Contains everything needed to re-render without re-analysis: video metadata,
shots (anchors, timing, camera path, corrections) and the tracer style.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kpmn_tracer import __version__
from kpmn_tracer.io.probe import VideoInfo
from kpmn_tracer.render.style import TracerStyle
from kpmn_tracer.trace.model import Shot

log = logging.getLogger(__name__)

PROJECT_SUFFIX = ".kpmntrace.json"
FORMAT_VERSION = 1


def project_path_for(clip: str | Path) -> Path:
    clip = Path(clip)
    return clip.with_name(clip.name + PROJECT_SUFFIX)


@dataclass
class Project:
    source: str  # absolute path of the clip
    video: VideoInfo
    frame_count: int  # frames of the normalised stream (== overlay frames)
    vfr_mode: str = "frames"
    style: TracerStyle = field(default_factory=TracerStyle)
    shots: list[Shot] = field(default_factory=list)
    ball_start_hint: tuple[float, float] | None = None  # last ball position (tripod preset)
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def fps(self) -> float:
        return float(self.video.target_fps)

    @property
    def width(self) -> int:
        return self.video.width

    @property
    def height(self) -> int:
        return self.video.height

    def shot_at(self, frame: int) -> Shot | None:
        """Shot whose flight/fade covers ``frame`` (latest impact <= frame), else None."""
        cands = [s for s in self.shots if s.impact_frame <= frame]
        return max(cands, key=lambda s: s.impact_frame) if cands else None

    # ------------------------------------------------------------ persistence
    def to_dict(self, base_dir: Path | None = None) -> dict[str, Any]:
        src = self.source
        if base_dir is not None:
            try:
                src = os.path.relpath(self.source, base_dir)
            except ValueError:  # different drive on Windows
                src = self.source
        return {
            "format": "kpmn-tracer-project",
            "format_version": FORMAT_VERSION,
            "app_version": __version__,
            "source": src,
            "video": self.video.to_dict(),
            "frame_count": self.frame_count,
            "vfr_mode": self.vfr_mode,
            "style": self.style.to_dict(),
            "shots": [s.to_dict() for s in self.shots],
            "ball_start_hint": list(self.ball_start_hint) if self.ball_start_hint else None,
            "settings": self.settings,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any], base_dir: Path | None = None) -> Project:
        if d.get("format") != "kpmn-tracer-project":
            raise ValueError("not a KPMN Tracer project file")
        src = Path(d["source"])
        if not src.is_absolute() and base_dir is not None:
            src = (base_dir / src).resolve()
        video = VideoInfo.from_dict(d["video"])
        video.path = str(src)
        hint = d.get("ball_start_hint")
        return cls(
            source=str(src),
            video=video,
            frame_count=int(d["frame_count"]),
            vfr_mode=d.get("vfr_mode", "frames"),
            style=TracerStyle.from_dict(d.get("style", {})),
            shots=[Shot.from_dict(s) for s in d.get("shots", [])],
            ball_start_hint=tuple(hint) if hint else None,
            settings=d.get("settings", {}),
        )

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else project_path_for(self.source)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(path.parent), indent=1), encoding="utf-8")
        tmp.replace(path)
        log.info("Project saved: %s", path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> Project:
        path = Path(path)
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(d, path.parent)
