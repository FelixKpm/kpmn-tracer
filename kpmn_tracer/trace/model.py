"""Shot data model - the single editable structure used by manual and automatic modes.

Coordinates of anchors are *reference-frame* pixel coordinates in the source
clip's display resolution, where the reference frame is the shot's impact
frame. A per-shot :class:`CameraTrack` maps every frame into that reference.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

import numpy as np

from kpmn_tracer.trace.path import FlightPath
from kpmn_tracer.trace.timing import AnchorTiming, EasingTiming

DEFAULT_FLIGHT_SECONDS = 4.0


class AnchorKind(str, Enum):
    START = "start"
    APEX = "apex"
    LAND = "land"
    POINT = "point"  # extra shape point (draw/fade control, auto-fit samples)


@dataclass
class Anchor:
    x: float
    y: float
    kind: AnchorKind = AnchorKind.POINT
    t: float | None = None  # frames after impact when the ball was here (optional)

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "kind": self.kind.value, "t": self.t}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Anchor:
        return cls(float(d["x"]), float(d["y"]), AnchorKind(d.get("kind", "point")), d.get("t"))


@dataclass
class OffsetKeyframe:
    """Manual correction: shift the projected tracer by (dx, dy) pixels at ``frame``."""

    frame: int
    dx: float
    dy: float


@dataclass
class CameraTrack:
    """Homographies frame -> reference (impact) frame for frames ``first..first+len-1``."""

    first_frame: int = 0
    homographies: list[list[list[float]]] = field(default_factory=list)
    confidence: list[float] = field(default_factory=list)
    mode: str = "tripod"  # "tripod" (identity) or "tracked"

    def H(self, frame: int) -> np.ndarray:
        """frame -> reference homography (identity outside the tracked range / tripod)."""
        if self.mode == "tripod" or not self.homographies:
            return np.eye(3)
        i = int(np.clip(frame - self.first_frame, 0, len(self.homographies) - 1))
        return np.asarray(self.homographies[i], dtype=float)

    def conf(self, frame: int) -> float:
        if self.mode == "tripod" or not self.confidence:
            return 1.0
        i = frame - self.first_frame
        if 0 <= i < len(self.confidence):
            return float(self.confidence[i])
        return 0.0

    def covers(self, frame: int) -> bool:
        return self.mode == "tripod" or self.first_frame <= frame < self.first_frame + len(self.homographies)


@dataclass
class PathShape:
    launch_steepness: float = 0.5
    descent_steepness: float = 0.4


def _apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    hom = np.c_[pts, np.ones(len(pts))] @ H.T
    return hom[:, :2] / hom[:, 2:3]


@dataclass
class Shot:
    impact_frame: int
    anchors: list[Anchor] = field(default_factory=list)
    land_frame: float | None = None  # frame where the ball lands (manual timing)
    timing: EasingTiming = field(default_factory=EasingTiming)
    shape: PathShape = field(default_factory=PathShape)
    camera: CameraTrack = field(default_factory=CameraTrack)
    offsets: list[OffsetKeyframe] = field(default_factory=list)
    occlude: bool = False  # cut the tracer where the person mask is
    source: str = "manual"  # "manual" | "auto"
    confidence: float | None = None
    confirmed: bool = False
    label: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    # ------------------------------------------------------------ anchors
    def anchor(self, kind: AnchorKind) -> Anchor | None:
        return next((a for a in self.anchors if a.kind == kind), None)

    def set_anchor(self, kind: AnchorKind, x: float, y: float) -> None:
        """Set start/apex/land (keeps ordering start < points < apex < points < land)."""
        a = self.anchor(kind)
        if a is not None:
            a.x, a.y = x, y
            a.t = None if self.source == "manual" else a.t
            return
        order = {AnchorKind.START: 0, AnchorKind.APEX: 1, AnchorKind.LAND: 2}
        new = Anchor(x, y, kind)
        idx = len(self.anchors)
        for i, b in enumerate(self.anchors):
            if b.kind in order and order[b.kind] > order[kind]:
                idx = i
                break
        self.anchors.insert(idx, new)

    def is_complete(self) -> bool:
        return self.anchor(AnchorKind.START) is not None and self.anchor(AnchorKind.LAND) is not None

    def path(self) -> FlightPath | None:
        if len(self.anchors) < 2 or not self.is_complete():
            return None
        pts = [(a.x, a.y) for a in self.anchors]
        apex = next((i for i, a in enumerate(self.anchors) if a.kind == AnchorKind.APEX), None)
        return FlightPath.build(pts, apex, self.shape.launch_steepness, self.shape.descent_steepness)

    # ------------------------------------------------------------ timing
    def uses_anchor_times(self) -> bool:
        ts = [a.t for a in self.anchors]
        if len(ts) < 2:
            return False
        return all(t is not None for t in ts) and np.all(np.diff(np.asarray(ts, float)) > 0)

    def flight_frames(self, fps: float) -> float:
        """Impact -> landing duration in frames."""
        if self.uses_anchor_times():
            return float(self.anchors[-1].t)  # type: ignore[arg-type]
        if self.land_frame is not None and self.land_frame > self.impact_frame:
            return float(self.land_frame - self.impact_frame)
        return DEFAULT_FLIGHT_SECONDS * fps

    def head_u(self, frame: float, fps: float) -> float | None:
        """Path parameter of the ball at ``frame`` (None before impact). 1.0 after landing."""
        if frame < self.impact_frame:
            return None
        path = self.path()
        if path is None:
            return None
        dur = self.flight_frames(fps)
        tau = (frame - self.impact_frame) / dur
        if tau >= 1.0:
            return 1.0
        return float(self.u_at_tau(tau, path)[0])

    def u_at_tau(self, tau: float | np.ndarray, path: FlightPath | None = None) -> np.ndarray:
        path = path or self.path()
        if path is None:
            raise ValueError("incomplete shot")
        if self.uses_anchor_times():
            dur = float(self.anchors[-1].t)  # type: ignore[arg-type]
            taus = tuple(float(a.t) / dur for a in self.anchors)  # type: ignore[arg-type]
            taus = (0.0,) + taus[1:] if taus[0] > 0 else taus
            return AnchorTiming(taus, tuple(path.knots)).u_at(tau)
        return self.timing.u_at(tau)

    # ------------------------------------------------------------ projection
    def offset_at(self, frame: float) -> np.ndarray:
        if not self.offsets:
            return np.zeros(2)
        kf = sorted(self.offsets, key=lambda k: k.frame)
        fr = np.array([k.frame for k in kf], float)
        dx = np.interp(frame, fr, [k.dx for k in kf])
        dy = np.interp(frame, fr, [k.dy for k in kf])
        return np.array([dx, dy])

    def to_frame(self, pts_ref: np.ndarray, frame: int) -> np.ndarray:
        """Project reference-frame points into frame ``frame`` (camera + manual offsets)."""
        pts_ref = np.asarray(pts_ref, float).reshape(-1, 2)
        H = self.camera.H(frame)
        out = pts_ref if self.camera.mode == "tripod" else _apply_h(np.linalg.inv(H), pts_ref)
        return out + self.offset_at(frame)

    def to_ref(self, pts_frame: np.ndarray, frame: int) -> np.ndarray:
        """Inverse of :meth:`to_frame` (used when the user clicks in a frame)."""
        pts = np.asarray(pts_frame, float).reshape(-1, 2) - self.offset_at(frame)
        if self.camera.mode == "tripod":
            return pts
        return _apply_h(self.camera.H(frame), pts)

    # ------------------------------------------------------------ serialisation
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "impact_frame": self.impact_frame,
            "anchors": [a.to_dict() for a in self.anchors],
            "land_frame": self.land_frame,
            "timing": asdict(self.timing),
            "shape": asdict(self.shape),
            "camera": asdict(self.camera),
            "offsets": [asdict(o) for o in self.offsets],
            "occlude": self.occlude,
            "source": self.source,
            "confidence": self.confidence,
            "confirmed": self.confirmed,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Shot:
        return cls(
            id=d.get("id") or uuid.uuid4().hex[:8],
            label=d.get("label", ""),
            impact_frame=int(d["impact_frame"]),
            anchors=[Anchor.from_dict(a) for a in d.get("anchors", [])],
            land_frame=d.get("land_frame"),
            timing=EasingTiming(**d.get("timing", {})),
            shape=PathShape(**d.get("shape", {})),
            camera=CameraTrack(**d.get("camera", {})),
            offsets=[OffsetKeyframe(**o) for o in d.get("offsets", [])],
            occlude=bool(d.get("occlude", False)),
            source=d.get("source", "manual"),
            confidence=d.get("confidence"),
            confirmed=bool(d.get("confirmed", False)),
        )


def scaled_shot(shot: Shot, sx: float, sy: float) -> Shot:
    """Copy of ``shot`` in another pixel space (e.g. source -> proxy: sx = proxy_w / src_w)."""
    s = Shot.from_dict(shot.to_dict())
    for a in s.anchors:
        a.x *= sx
        a.y *= sy
    for o in s.offsets:
        o.dx *= sx
        o.dy *= sy
    if s.camera.homographies:
        S = np.diag([sx, sy, 1.0])
        Si = np.diag([1 / sx, 1 / sy, 1.0])
        s.camera.homographies = [(S @ np.asarray(h) @ Si).tolist() for h in s.camera.homographies]
    return s
