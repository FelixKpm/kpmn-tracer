"""Side panels: shot list + point tools, flight parameters, tracer style."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kpmn_tracer.render.style import TracerStyle
from kpmn_tracer.trace.model import AnchorKind, Shot

TOOLS = (
    ("select", "Auswählen", "V", "Punkte ziehen / auswählen"),
    ("start", "Start", "S", "Ball-Startpunkt im Impact-Frame setzen"),
    ("apex", "Apex", "A", "Höchsten Punkt der Flugbahn setzen"),
    ("land", "Landung", "L", "Landepunkt setzen"),
    ("point", "Zusatzpunkt", "P", "Zusätzlicher Kurvenpunkt (Draw/Fade)"),
    ("offset", "Korrektur", "K", "Tracer in diesem Frame verschieben (Keyframe)"),
    ("ball", "Ball hier", "H", "Auf den Ball klicken: der Tracer-Kopf ist in diesem Frame genau dort"),
)


def dspin(lo: float, hi: float, step: float, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(decimals)
    if suffix:
        w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#ff0000", allow_none: bool = False) -> None:
        super().__init__()
        self._color: str | None = color
        self._allow_none = allow_none
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> str | None:
        return self._color

    def set_color(self, c: str | None) -> None:
        self._color = c
        self._refresh()

    def _refresh(self) -> None:
        if self._color is None:
            self.setText("wie Linie")
            self.setStyleSheet("")
        else:
            self.setText(self._color)
            fg = "#000" if QColor(self._color).lightness() > 128 else "#fff"
            self.setStyleSheet(f"background:{self._color}; color:{fg};")

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color or "#ffffff"), self, "Farbe wählen")
        if c.isValid():
            self.set_color(c.name())
            self.colorChanged.emit(c.name())


class StylePanel(QGroupBox):
    changed = Signal()
    presetChosen = Signal(str)
    presetSave = Signal()
    presetDelete = Signal()

    def __init__(self) -> None:
        super().__init__("Tracer-Style")
        self.style_obj = TracerStyle()
        f = QFormLayout(self)
        self._setters: list[Callable[[], None]] = []
        self._building = False

        prow = QGridLayout()
        self.presets = QComboBox()
        self.presets.setToolTip("Gespeicherte Styles")
        self.presets.activated.connect(lambda _i: self.presetChosen.emit(self.presets.currentText()))
        save = QPushButton("Speichern…")
        save.setToolTip("Aktuellen Style als Preset speichern")
        save.clicked.connect(self.presetSave.emit)
        delete = QPushButton("Löschen")
        delete.setToolTip("Eigenes Preset löschen")
        delete.clicked.connect(self.presetDelete.emit)
        prow.addWidget(self.presets, 0, 0, 1, 2)
        prow.addWidget(save, 1, 0)
        prow.addWidget(delete, 1, 1)
        f.addRow("Preset", prow)

        self.color = ColorButton()
        self.color.colorChanged.connect(lambda c: self._set("color", c))
        f.addRow("Farbe", self.color)
        self.glow_color = ColorButton(allow_none=True)
        self.glow_color.set_color(None)
        self.glow_color.colorChanged.connect(lambda c: self._set("glow_color", c))
        f.addRow("Glow-Farbe", self.glow_color)

        self._spin(f, "Dicke", "width", 0.5, 60, 0.5, 1, " px")
        self._spin(f, "Verjüngung", "taper", 0, 1, 0.05)
        self._spin(f, "Deckkraft", "opacity", 0, 1, 0.05)
        self._spin(f, "Weißer Kern", "core_highlight", 0, 1, 0.05)
        self._spin(f, "Glow-Radius", "glow_radius", 0, 80, 1, 1, " px")
        self._spin(f, "Glow-Stärke", "glow_strength", 0, 4, 0.1)
        self._check(f, "Schatten", "shadow")
        self._spin(f, "Schatten-Deckkraft", "shadow_opacity", 0, 1, 0.05)
        self.mode = QComboBox()
        self.mode.addItem("Voller Pfad bleibt stehen", "full")
        self.mode.addItem("Kurzer Schweif", "tail")
        self.mode.currentIndexChanged.connect(lambda _i: self._set("mode", self.mode.currentData()))
        f.addRow("Modus", self.mode)
        self._spin(f, "Schweif-Länge", "tail_seconds", 0.05, 5, 0.05, 2, " s")
        self._check(f, "Ball-Punkt am Kopf", "head_dot")
        self._spin(f, "Stehen nach Landung", "hold_seconds", 0, 20, 0.1, 1, " s")
        self._spin(f, "Ausblenden", "fade_out_seconds", 0, 10, 0.1, 1, " s")

    def _spin(self, form: QFormLayout, label: str, attr: str, lo: float, hi: float,
              step: float, dec: int = 2, suffix: str = "") -> None:
        w = dspin(lo, hi, step, dec, suffix)
        w.valueChanged.connect(lambda v, a=attr: self._set(a, float(v)))
        self._setters.append(lambda w=w, a=attr: w.setValue(getattr(self.style_obj, a)))
        form.addRow(label, w)

    def _check(self, form: QFormLayout, label: str, attr: str) -> None:
        w = QCheckBox()
        w.toggled.connect(lambda v, a=attr: self._set(a, bool(v)))
        self._setters.append(lambda w=w, a=attr: w.setChecked(getattr(self.style_obj, a)))
        form.addRow(label, w)

    def _set(self, attr: str, value: Any) -> None:
        if self._building:
            return
        setattr(self.style_obj, attr, value)
        self.changed.emit()

    def set_presets(self, names: list[str], current: str | None = None) -> None:
        self.presets.blockSignals(True)
        self.presets.clear()
        self.presets.addItems(names)
        if current and current in names:
            self.presets.setCurrentText(current)
        self.presets.blockSignals(False)

    def set_style(self, style: TracerStyle) -> None:
        self.style_obj = style
        self._building = True
        try:
            self.color.set_color(style.color)
            self.glow_color.set_color(style.glow_color)
            self.mode.setCurrentIndex(max(0, self.mode.findData(style.mode)))
            for s in self._setters:
                s()
        finally:
            self._building = False


class TextPanel(QGroupBox):
    """Text label of the current shot + global text style."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__("Text-Einblendung")
        from kpmn_tracer.render.text import TextStyle

        self.text_style = TextStyle()
        f = QFormLayout(self)
        self.text = QLineEdit()
        self.text.setPlaceholderText("z. B. 7-Eisen · 145 m  (leer = kein Text)")
        self.text.editingFinished.connect(self._emit)
        self.position = QComboBox()
        for k, label in (("apex", "Am Apex"), ("land", "Am Landepunkt"), ("top_left", "Oben links"),
                         ("top_right", "Oben rechts"), ("bottom_left", "Unten links"),
                         ("bottom_right", "Unten rechts")):
            self.position.addItem(label, k)
        self.trigger = QComboBox()
        self.trigger.addItem("nach dem Impact", "impact")
        self.trigger.addItem("nach der Landung", "land")
        self.delay = dspin(0, 10, 0.1, 1, " s")
        self.size = dspin(10, 200, 2, 0, " px")
        self.box = QCheckBox("Hintergrund-Box")
        for w in (self.position, self.trigger):
            w.currentIndexChanged.connect(lambda _i: self._emit())
        for w in (self.delay, self.size):
            w.valueChanged.connect(lambda _v: self._emit())
        self.box.toggled.connect(lambda _v: self._emit())
        f.addRow("Text (Schlag)", self.text)
        f.addRow("Position", self.position)
        f.addRow("Erscheint", self.trigger)
        f.addRow("Verzögerung", self.delay)
        f.addRow("Schriftgröße", self.size)
        f.addRow(self.box)
        self._building = False

    def _emit(self) -> None:
        if self._building:
            return
        ts = self.text_style
        ts.position = self.position.currentData()
        ts.trigger = self.trigger.currentData()
        ts.delay_s = self.delay.value()
        ts.size = self.size.value()
        ts.box = self.box.isChecked()
        self.changed.emit()

    def load(self, text: str, enabled: bool, ts) -> None:
        self._building = True
        try:
            self.text_style = ts
            self.text.setText(text)
            self.text.setEnabled(enabled)
            self.position.setCurrentIndex(max(0, self.position.findData(ts.position)))
            self.trigger.setCurrentIndex(max(0, self.trigger.findData(ts.trigger)))
            self.delay.setValue(ts.delay_s)
            self.size.setValue(ts.size)
            self.box.setChecked(ts.box)
        finally:
            self._building = False


class ShotPanel(QWidget):
    """Shot list, point tools and per-shot flight parameters."""

    toolChanged = Signal(str)
    shotSelected = Signal(int)
    addShot = Signal()
    deleteShot = Signal()
    setImpact = Signal()
    setLandFrame = Signal()
    jumpImpact = Signal()
    clearOffsets = Signal()
    paramsChanged = Signal()
    trackCamera = Signal(bool)  # force tracking (skip tripod detection)
    detectImpacts = Signal()
    autoTrack = Signal()
    analyzeClip = Signal()
    simplify = Signal()
    adoptCandidate = Signal()
    adoptAll = Signal()

    def __init__(self) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        box = QGroupBox("Schläge")
        bl = QVBoxLayout(box)
        self.list = QListWidget()
        self.list.setMaximumHeight(130)
        self.list.currentRowChanged.connect(self.shotSelected.emit)
        bl.addWidget(self.list)
        row = QGridLayout()
        for i, (text, sig, tip) in enumerate((
            ("Neuer Schlag", self.addShot, "Neuen Schlag mit Impact = aktueller Frame anlegen (N)"),
            ("Löschen", self.deleteShot, "Ausgewählten Schlag löschen"),
            ("Impact = Frame", self.setImpact, "Impact-Frame auf aktuellen Frame setzen (I)"),
            ("Landung = Frame", self.setLandFrame, "Lande-Frame auf aktuellen Frame setzen (O)"),
            ("→ Impact", self.jumpImpact, "Zum Impact-Frame springen (Pos1)"),
            ("Korrekturen löschen", self.clearOffsets, "Alle Korrektur-Keyframes dieses Schlags entfernen"),
        )):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(sig.emit)
            row.addWidget(b, i // 2, i % 2)
        bl.addLayout(row)
        lay.addWidget(box)

        tbox = QGroupBox("Werkzeug")
        tl = QGridLayout(tbox)
        self.tool_group = QButtonGroup(self)
        self.tool_buttons: dict[str, QToolButton] = {}
        for i, (key, text, sc, tip) in enumerate(TOOLS):
            b = QToolButton()
            b.setText(f"{text} ({sc})")
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.tool_group.addButton(b)
            self.tool_buttons[key] = b
            b.clicked.connect(lambda _c=False, k=key: self.toolChanged.emit(k))
            tl.addWidget(b, i // 2, i % 2)
        self.tool_buttons["select"].setChecked(True)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#aaa;")
        tl.addWidget(self.hint, 4, 0, 1, 2)
        lay.addWidget(tbox)

        abox = QGroupBox("Automatik")
        al = QGridLayout(abox)
        for i, (text, sig, tip) in enumerate((
            ("Impacts erkennen (D)", self.detectImpacts,
             "Schläge über Audio (Schlaggeräusch) und Video (Ball verlässt den Abschlagpunkt) finden"),
            ("Kandidat übernehmen", self.adoptCandidate, "Nächsten Kandidaten zum aktuellen Frame als Schlag anlegen"),
            ("Alle sicheren übernehmen", self.adoptAll, "Alle Kandidaten mit Konfidenz ≥ 50 % als Schläge anlegen"),
            ("Ball tracken (B)", self.autoTrack,
             "Flugbahn dieses Schlags automatisch verfolgen (Kamera, Maske, Ball)"),
            ("Ganzen Clip analysieren", self.analyzeClip,
             "Alle Impacts finden und jeden Schlag automatisch tracken"),
            ("Vereinfachen", self.simplify,
             "Auto-Ergebnis auf Start/Apex/Landung reduzieren (bequemer von Hand nachzubessern)"),
        )):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(sig.emit)
            al.addWidget(b, i // 2, i % 2)
        self.auto_status = QLabel("Tipp: zuerst den Ball mit „Start“ markieren – dann wird auch das Video ausgewertet.")
        self.auto_status.setWordWrap(True)
        self.auto_status.setStyleSheet("color:#aaa;")
        al.addWidget(self.auto_status, 3, 0, 1, 2)
        lay.addWidget(abox)

        cbox = QGroupBox("Kamera")
        cl = QGridLayout(cbox)
        self.cam_btn = QPushButton("Kamera tracken (T)")
        self.cam_btn.setToolTip("Kamerabewegung um diesen Schlag analysieren (Stativ wird automatisch erkannt)")
        self.cam_btn.clicked.connect(lambda: self.trackCamera.emit(False))
        self.cam_force = QPushButton("Erzwingen")
        self.cam_force.setToolTip("Tracking auch dann durchführen, wenn ein Stativ erkannt würde")
        self.cam_force.clicked.connect(lambda: self.trackCamera.emit(True))
        self.cam_status = QLabel("nicht analysiert (Stativ angenommen)")
        self.cam_status.setWordWrap(True)
        self.cam_status.setStyleSheet("color:#aaa;")
        cl.addWidget(self.cam_btn, 0, 0)
        cl.addWidget(self.cam_force, 0, 1)
        cl.addWidget(self.cam_status, 1, 0, 1, 2)
        lay.addWidget(cbox)

        pbox = QGroupBox("Flugkurve")
        pf = QFormLayout(pbox)
        self.duration = dspin(0.2, 15, 0.1, 2, " s")
        self.duration.setToolTip("Flugzeit Impact → Landung (bestimmt den Lande-Frame)")
        self.launch = dspin(0, 0.95, 0.05)
        self.launch.setToolTip("Wie steil der Ball startet (0 = gerade Linie zum Apex)")
        self.descent = dspin(0, 0.95, 0.05)
        self.descent.setToolTip("Wie steil der Ball fällt")
        self.boost = dspin(0, 100, 0.5)
        self.boost.setToolTip("Tempo direkt nach dem Impact (Easing)")
        self.decay = dspin(0.005, 1, 0.005, 3)
        self.decay.setToolTip("Wie schnell der Ball nach dem Abflug abbremst")
        self.late = dspin(0, 5, 0.1)
        self.late.setToolTip("Beschleunigung auf dem Weg nach unten")
        self.occlude = QCheckBox("Tracer hinter Golfer")
        self.occlude.setToolTip("Tracer dort ausschneiden, wo die Personen-Maske liegt")
        for label, w in (("Flugzeit", self.duration), ("Start-Steilheit", self.launch),
                         ("Abstiegs-Steilheit", self.descent), ("Start-Tempo", self.boost),
                         ("Abbremsen", self.decay), ("Spätes Tempo", self.late)):
            pf.addRow(label, w)
            w.valueChanged.connect(lambda _v: self._emit_params())
        pf.addRow(self.occlude)
        self.occlude.toggled.connect(lambda _v: self._emit_params())
        lay.addWidget(pbox)
        self._building = False

    def _emit_params(self) -> None:
        if not self._building:
            self.paramsChanged.emit()

    def select_tool(self, key: str) -> None:
        self.tool_buttons[key].setChecked(True)

    def set_shots(self, shots: list[Shot], current: int, fps: float) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for i, s in enumerate(shots):
            conf = f", {s.confidence:.0%}" if s.confidence is not None else ""
            mark = "✔ " if s.confirmed else ""
            t = s.impact_frame / fps if fps else 0
            item = QListWidgetItem(f"{mark}Schlag {i + 1} – Frame {s.impact_frame} ({t:.2f}s, {s.source}{conf})")
            if not s.is_complete():
                item.setForeground(QColor(230, 160, 60))
            self.list.addItem(item)
        if 0 <= current < len(shots):
            self.list.setCurrentRow(current)
        self.list.blockSignals(False)

    def load_params(self, shot: Shot | None, fps: float) -> None:
        self._building = True
        try:
            enabled = shot is not None
            for w in (self.duration, self.launch, self.descent, self.boost, self.decay, self.late, self.occlude):
                w.setEnabled(enabled)
            if shot is None:
                self.cam_status.setText("")
                return
            cam = shot.camera
            if cam.mode == "tracked":
                bad = sum(c < 0.5 for c in cam.confidence)
                self.cam_status.setText(
                    f"Handheld: Frames {cam.first_frame}–{cam.first_frame + len(cam.homographies) - 1} "
                    f"getrackt, {bad} unsicher (rot in der Timeline)")
            elif cam.analyzed:
                self.cam_status.setText("Stativ erkannt – keine Kompensation nötig")
            else:
                self.cam_status.setText("nicht analysiert (Stativ angenommen)")
            self.duration.setValue(shot.flight_frames(fps) / fps)
            land = shot.anchor(AnchorKind.LAND)
            self.duration.setEnabled(land is None or land.t is None)
            pinned = sum(1 for a in shot.anchors if a.t is not None and a.kind == AnchorKind.POINT)
            for w in (self.boost, self.decay, self.late):
                w.setEnabled(pinned == 0)
                w.setToolTip(w.toolTip().split(" (")[0] + (" (inaktiv: Timing folgt den „Ball hier“-Punkten)"
                                                          if pinned else ""))
            self.launch.setValue(shot.shape.launch_steepness)
            self.descent.setValue(shot.shape.descent_steepness)
            self.boost.setValue(shot.timing.launch_boost)
            self.decay.setValue(shot.timing.launch_decay)
            self.late.setValue(shot.timing.late_boost)
            self.occlude.setChecked(shot.occlude)
        finally:
            self._building = False
