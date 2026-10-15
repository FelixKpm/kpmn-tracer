"""Main window: preview, timeline, manual tracer editing, export."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QDragEnterEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from kpmn_tracer.gui.panels import TOOLS, ShotPanel, StylePanel
from kpmn_tracer.gui.timeline import Marker, Timeline
from kpmn_tracer.gui.video_view import Handle, VideoView
from kpmn_tracer.gui.workers import TaskRunner
from kpmn_tracer.io.export import FORMATS, ExportSettings, default_output, export
from kpmn_tracer.project.project_file import Project
from kpmn_tracer.render.tracer import TracerRenderer, composite_over
from kpmn_tracer.session import ClipSession
from kpmn_tracer.trace.model import Anchor, AnchorKind, OffsetKeyframe, Shot, scaled_shot

log = logging.getLogger(__name__)

VIDEO_FILTER = "Videos (*.mov *.mp4 *.m4v *.avi *.mkv);;Projekte (*.kpmntrace.json);;Alle Dateien (*)"
KIND_COLORS = {
    AnchorKind.START: QColor(80, 220, 120),
    AnchorKind.APEX: QColor(255, 210, 60),
    AnchorKind.LAND: QColor(80, 170, 255),
    AnchorKind.POINT: QColor(230, 230, 230),
}
KIND_LABELS = {AnchorKind.START: "Start", AnchorKind.APEX: "Apex", AnchorKind.LAND: "Landung",
               AnchorKind.POINT: ""}
TOOL_HINTS = {
    "select": "Punkte mit der Maus ziehen. Entf löscht einen Zusatzpunkt.",
    "start": "Im Impact-Frame auf den Ball klicken.",
    "apex": "Auf den höchsten Punkt der Flugbahn klicken (beliebiger Frame).",
    "land": "Auf den Landepunkt klicken. Mit „Landung = Frame“ den Zeitpunkt setzen.",
    "point": "Klick fügt einen Kurvenpunkt hinzu (z. B. für Draw/Fade).",
    "offset": "Klick = wo der Tracer-Kopf in diesem Frame sein soll (Korrektur-Keyframe).",
}
EXPORT_LABELS = {"prores": "ProRes 4444 mit Alpha (.mov)", "png": "PNG-Sequenz mit Alpha",
                 "h264": "Eingebrannt H.264 (.mp4)", "h265": "Eingebrannt H.265 (.mp4)"}


class ExportDialog(QDialog):
    def __init__(self, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportieren")
        self.project = project
        f = QFormLayout(self)
        self.fmt = QComboBox()
        for k in FORMATS:
            self.fmt.addItem(EXPORT_LABELS[k], k)
        self.path = QLineEdit()
        browse = QPushButton("…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(browse)
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(18)
        self.crf.setToolTip("Qualität für eingebrannte Exporte (kleiner = besser)")
        f.addRow("Format", self.fmt)
        f.addRow("Ziel", row)
        f.addRow("CRF", self.crf)
        info = QLabel(f"{project.width}×{project.height}, {project.frame_count} Frames @ "
                      f"{float(project.video.target_fps):.3f} fps – identisch zum Clip.")
        info.setStyleSheet("color:#999;")
        f.addRow(info)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.fmt.currentIndexChanged.connect(self._update_default)
        self._update_default()

    def _update_default(self) -> None:
        fmt = self.fmt.currentData()
        self.path.setText(str(default_output(self.project, fmt)))
        self.crf.setEnabled(fmt in ("h264", "h265"))

    def _browse(self) -> None:
        fmt = self.fmt.currentData()
        if fmt == "png":
            d = QFileDialog.getExistingDirectory(self, "Zielordner", str(Path(self.path.text()).parent))
            if d:
                self.path.setText(d)
        else:
            p, _ = QFileDialog.getSaveFileName(self, "Ziel", self.path.text())
            if p:
                self.path.setText(p)

    def settings(self) -> ExportSettings:
        return ExportSettings(self.fmt.currentData(), Path(self.path.text()), self.crf.value())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KPMN Tracer")
        self.resize(1500, 900)
        self.setAcceptDrops(True)
        self.session: ClipSession | None = None
        self.frame = 0
        self.shot_idx = -1
        self.tool = "select"
        self.dirty = False
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._drag_snapshot = False
        self._preview_shots: list[Shot] | None = None
        self._overlay_buf: np.ndarray | None = None
        self._masks = None  # MaskTrack of the current clip (person segmentation)
        self.tasks = TaskRunner(self)

        self.view = VideoView()
        self.timeline = Timeline()
        self.shot_panel = ShotPanel()
        self.style_panel = StylePanel()
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._tick)

        self._build_layout()
        self._build_actions()
        self._connect()
        self._update_enabled()

    # ================================================================ layout
    def _build_layout(self) -> None:
        center = QWidget()
        v = QVBoxLayout(center)
        v.setContentsMargins(4, 4, 4, 4)
        v.addWidget(self.view, 1)
        transport = QHBoxLayout()
        self.btn = {}
        for key, text, tip in (("first", "⏮", "Anfang (Pos1)"), ("prev10", "−10", "10 Frames zurück (Shift+←)"),
                               ("prev", "◀", "Frame zurück (←)"), ("play", "▶", "Abspielen/Pause (Leertaste)"),
                               ("next", "▶|", "Frame vor (→)"), ("next10", "+10", "10 Frames vor (Shift+→)"),
                               ("last", "⏭", "Ende (Ende)")):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.setMinimumWidth(36)
            transport.addWidget(b)
            self.btn[key] = b
        self.frame_label = QLabel("–")
        self.frame_label.setMinimumWidth(260)
        transport.addWidget(self.frame_label)
        transport.addStretch(1)
        self.export_btn = QPushButton("Exportieren…")
        transport.addWidget(self.export_btn)
        v.addLayout(transport)
        v.addWidget(self.timeline)
        self.setCentralWidget(center)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(4, 4, 4, 4)
        sl.addWidget(self.shot_panel)
        sl.addWidget(self.style_panel)
        sl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(410)
        from PySide6.QtWidgets import QDockWidget

        dock = QDockWidget("Bearbeiten", self)
        dock.setObjectName("edit_dock")
        dock.setWidget(scroll)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.status_info = QLabel("")
        self.status_warn = QLabel("")
        self.status_warn.setStyleSheet("color:#e0a030;")
        self.statusBar().addWidget(self.status_info, 1)
        self.statusBar().addPermanentWidget(self.status_warn)

    def _build_actions(self) -> None:
        m = self.menuBar()
        filem = m.addMenu("&Datei")
        editm = m.addMenu("&Bearbeiten")
        viewm = m.addMenu("&Ansicht")

        def act(menu, text: str, slot, shortcut: str | QKeySequence | None = None) -> QAction:
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(slot)
            menu.addAction(a)
            self.addAction(a)
            return a

        act(filem, "Clip öffnen…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.a_save = act(filem, "Projekt speichern", self.save, QKeySequence.StandardKey.Save)
        self.a_export = act(filem, "Exportieren…", self.export_dialog, "Ctrl+E")
        filem.addSeparator()
        act(filem, "Beenden", self.close, "Ctrl+Q")
        self.a_undo = act(editm, "Rückgängig", self.undo, QKeySequence.StandardKey.Undo)
        self.a_redo = act(editm, "Wiederholen", self.redo, QKeySequence.StandardKey.Redo)
        editm.addSeparator()
        act(editm, "Neuer Schlag (Impact = Frame)", self.add_shot, "N")
        act(editm, "Impact = aktueller Frame", self.set_impact, "I")
        act(editm, "Landung = aktueller Frame", self.set_land_frame, "O")
        act(editm, "Ausgewählten Punkt löschen", self.delete_selected, QKeySequence.StandardKey.Delete)
        act(editm, "Kamera tracken", lambda: self.track_camera(False), "T")
        act(editm, "Impacts erkennen", self.detect_impacts, "D")
        act(editm, "Ball automatisch tracken", self.auto_track_shot, "B")
        for key, text, sc, _tip in TOOLS:
            act(editm, f"Werkzeug: {text}", lambda _c=False, k=key: self.set_tool(k), sc)
        act(viewm, "Ansicht einpassen", self.view.reset_view, "F")
        act(viewm, "Frame vor", lambda: self.step(1), "Right")
        act(viewm, "Frame zurück", lambda: self.step(-1), "Left")
        act(viewm, "10 Frames vor", lambda: self.step(10), "Shift+Right")
        act(viewm, "10 Frames zurück", lambda: self.step(-10), "Shift+Left")
        act(viewm, "Abspielen / Pause", self.toggle_play, "Space")
        act(viewm, "Zum Anfang", lambda: self.goto(0), "Ctrl+Home")
        act(viewm, "Zum Ende", lambda: self.goto(10**9), "Ctrl+End")
        act(viewm, "Zum Impact", self.jump_impact, "Home")
        act(viewm, "Nächster Schlag", lambda: self.select_shot(self.shot_idx + 1, jump=True), "Ctrl+Right")
        act(viewm, "Vorheriger Schlag", lambda: self.select_shot(self.shot_idx - 1, jump=True), "Ctrl+Left")

    def _connect(self) -> None:
        b = self.btn
        b["first"].clicked.connect(lambda: self.goto(0))
        b["last"].clicked.connect(lambda: self.goto(10**9))
        b["prev"].clicked.connect(lambda: self.step(-1))
        b["next"].clicked.connect(lambda: self.step(1))
        b["prev10"].clicked.connect(lambda: self.step(-10))
        b["next10"].clicked.connect(lambda: self.step(10))
        b["play"].clicked.connect(self.toggle_play)
        self.export_btn.clicked.connect(self.export_dialog)
        self.timeline.frameChanged.connect(self.goto)
        self.view.clicked.connect(self.on_view_click)
        self.view.handleMoved.connect(self.on_handle_moved)
        self.view.handleReleased.connect(lambda _k: self._end_drag())
        sp = self.shot_panel
        sp.toolChanged.connect(self.set_tool)
        sp.shotSelected.connect(lambda i: self.select_shot(i, jump=False))
        sp.addShot.connect(self.add_shot)
        sp.deleteShot.connect(self.delete_shot)
        sp.setImpact.connect(self.set_impact)
        sp.setLandFrame.connect(self.set_land_frame)
        sp.jumpImpact.connect(self.jump_impact)
        sp.clearOffsets.connect(self.clear_offsets)
        sp.paramsChanged.connect(self.on_params_changed)
        sp.trackCamera.connect(self.track_camera)
        sp.detectImpacts.connect(self.detect_impacts)
        sp.adoptCandidate.connect(self.adopt_candidate)
        sp.adoptAll.connect(self.adopt_all_candidates)
        sp.autoTrack.connect(self.auto_track_shot)
        sp.analyzeClip.connect(self.analyze_whole_clip)
        sp.simplify.connect(self.simplify_shot)
        self.timeline.markerClicked.connect(lambda m: self.goto(int(m.frame)))
        self.style_panel.changed.connect(self.on_style_changed)

    # ================================================================ loading
    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Clip öffnen", "", VIDEO_FILTER)
        if path:
            self.open_path(Path(path))

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:  # noqa: N802
        urls = e.mimeData().urls()
        if urls:
            self.open_path(Path(urls[0].toLocalFile()))

    def open_path(self, path: Path) -> None:
        if not self._maybe_save():
            return
        dlg = QProgressDialog(f"Analysiere {path.name} …\n(Proxy für die Vorschau wird erstellt)",
                              "Abbrechen", 0, 1000, self)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        worker = self.tasks.start(lambda prog, cancel: ClipSession.open(path, progress=prog, cancel=cancel))
        worker.progress.connect(lambda f: dlg.setValue(int(f * 1000)))
        dlg.canceled.connect(worker.cancel)
        worker.finished.connect(lambda s: (dlg.close(), self.set_session(s)))
        worker.failed.connect(lambda msg: (dlg.close(), QMessageBox.critical(self, "Fehler beim Öffnen", msg)))
        worker.cancelled.connect(dlg.close)

    def set_session(self, session: ClipSession) -> None:
        if self.session is not None:
            self.session.close()
        self.session = session
        from kpmn_tracer.segmentation.provider import load_masks

        self._masks = load_masks(session)
        p = session.project
        self.frame = 0
        self.shot_idx = 0 if p.shots else -1
        self._undo.clear()
        self._redo.clear()
        self.dirty = False
        self.timeline.set_count(p.frame_count)
        self.style_panel.set_style(p.style)
        self.setWindowTitle(f"KPMN Tracer – {Path(p.source).name}")
        self.status_info.setText(p.video.summary())
        warn = []
        if p.video.is_vfr:
            warn.append(f"VFR → {p.frame_count} Frames @ {float(p.video.target_fps):.3f} fps "
                        f"(1:1 wie in Resolve)")
        if p.video.is_hdr:
            warn.append(f"HDR ({p.video.hdr_format}) – Vorschau in SDR, Original unverändert")
        self.status_warn.setText("   ".join(warn))
        if p.shots:
            self.goto(p.shots[0].impact_frame)
        self.on_project_changed(record=False)
        self._update_enabled()

    # ================================================================ state helpers
    @property
    def project(self) -> Project | None:
        return self.session.project if self.session else None

    def current_shot(self) -> Shot | None:
        p = self.project
        if p is None or not (0 <= self.shot_idx < len(p.shots)):
            return None
        return p.shots[self.shot_idx]

    def _snapshot(self) -> None:
        if self.project is None:
            return
        self._undo.append(self.project.to_dict())
        self._undo = self._undo[-100:]
        self._redo.clear()

    def _restore(self, d: dict) -> None:
        assert self.session is not None
        base = Path(self.session.project.source).parent
        self.session.project = Project.from_dict(d, base)
        self.shot_idx = min(self.shot_idx, len(self.session.project.shots) - 1)
        self.style_panel.set_style(self.session.project.style)
        self.on_project_changed(record=False)

    def undo(self) -> None:
        if self._undo and self.project:
            self._redo.append(self.project.to_dict())
            self._restore(self._undo.pop())

    def redo(self) -> None:
        if self._redo and self.project:
            self._undo.append(self.project.to_dict())
            self._restore(self._redo.pop())

    def on_project_changed(self, record: bool = True) -> None:
        """Call after any modification of the project."""
        if record:
            self.dirty = True
        self._preview_shots = None
        p = self.project
        if p is not None:
            self.shot_panel.set_shots(p.shots, self.shot_idx, p.fps)
            self.shot_panel.load_params(self.current_shot(), p.fps)
        self._update_timeline()
        self.refresh()

    def _update_enabled(self) -> None:
        has = self.session is not None
        for w in (self.export_btn, self.shot_panel, self.style_panel, self.a_save, self.a_export):
            w.setEnabled(has)

    def _update_timeline(self) -> None:
        p = self.project
        tl = self.timeline
        tl.markers, tl.ranges, tl.bad_frames = [], [], set()
        if p is None:
            tl.update()
            return
        for i, s in enumerate(p.shots):
            cur = i == self.shot_idx
            land = s.impact_frame + s.flight_frames(p.fps)
            tl.markers.append(Marker(s.impact_frame, QColor(255, 200, 40) if cur else QColor(170, 140, 40),
                                     "triangle", f"Impact Schlag {i + 1}"))
            tl.markers.append(Marker(land, QColor(80, 170, 255), "line", f"Landung Schlag {i + 1}"))
            if cur:
                tl.ranges.append((s.impact_frame, int(land), QColor(255, 200, 40, 40)))
                for o in s.offsets:
                    tl.markers.append(Marker(o.frame, QColor(255, 120, 40), "diamond", "Korrektur-Keyframe"))
                if s.camera.mode == "tracked":
                    tl.bad_frames = {s.camera.first_frame + k for k, c in enumerate(s.camera.confidence)
                                     if c < 0.5}
        for c in self.candidates():
            if any(abs(s.impact_frame - c.frame) <= 2 for s in p.shots):
                continue
            col = QColor(230, 80, 230) if c.confidence >= 0.5 else QColor(140, 90, 140)
            tl.markers.append(Marker(c.frame, col, "triangle",
                                     f"Impact-Kandidat {c.confidence:.0%} ({'+'.join(c.sources)})"))
        tl.update()

    # ================================================================ navigation
    def goto(self, frame: int) -> None:
        p = self.project
        if p is None:
            return
        self.frame = int(min(max(frame, 0), p.frame_count - 1))
        self.timeline.set_current(self.frame)
        self.refresh()

    def step(self, d: int) -> None:
        self.goto(self.frame + d)

    def toggle_play(self) -> None:
        p = self.project
        if p is None:
            return
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.btn["play"].setText("▶")
        else:
            if self.frame >= p.frame_count - 1:
                self.goto(0)
            self.play_timer.start(max(1, int(1000 / p.fps)))
            self.btn["play"].setText("⏸")

    def _tick(self) -> None:
        p = self.project
        if p is None or self.frame >= p.frame_count - 1:
            self.toggle_play()
            return
        self.goto(self.frame + 1)

    def jump_impact(self) -> None:
        s = self.current_shot()
        if s:
            self.goto(s.impact_frame)

    def select_shot(self, i: int, jump: bool = False) -> None:
        p = self.project
        if p is None or not p.shots:
            return
        self.shot_idx = int(min(max(i, 0), len(p.shots) - 1))
        self.view.selected = None
        self.on_project_changed(record=False)
        if jump:
            self.jump_impact()

    # ================================================================ rendering
    def _scaled_shots(self) -> list[Shot]:
        assert self.session is not None
        if self._preview_shots is None:
            s = self.session
            self._preview_shots = [scaled_shot(x, s.sx, s.sy) for x in s.project.shots if x.is_complete()]
        return self._preview_shots

    def refresh(self) -> None:
        s = self.session
        if s is None:
            return
        p = s.project
        img = s.reader.read(self.frame)
        r = TracerRenderer(s.reader.width, s.reader.height, p.fps, p.style)
        if self._overlay_buf is None or self._overlay_buf.shape[:2] != img.shape[:2]:
            self._overlay_buf = np.zeros(img.shape[:2] + (4,), np.uint8)
        ov = r.render(self._scaled_shots(), self.frame, self._occlusion_preview(), out=self._overlay_buf)
        self.view.set_frame(composite_over(img, ov))
        self.view.set_handles(self._handles())
        t = self.frame / p.fps
        shot = self.current_shot()
        rel = f"   Impact {self.frame - shot.impact_frame:+d}" if shot else ""
        self.frame_label.setText(f"Frame {self.frame} / {p.frame_count - 1}   {int(t // 60):02d}:{t % 60:05.2f}{rel}")
        conf = ""
        if shot and shot.camera.mode == "tracked" and shot.camera.covers(self.frame):
            conf = f"Tracking-Konfidenz {shot.camera.conf(self.frame):.0%}"
        self.view.info_text = conf

    def _occlusion_preview(self) -> np.ndarray | None:
        shot, s = self.current_shot(), self.session
        if s is None or self._masks is None or not any(x.occlude for x in s.project.shots):
            return None
        from kpmn_tracer.segmentation.mask_cache import soft_occlusion

        _ = shot
        return soft_occlusion(self._masks.get(self.frame, (s.reader.width, s.reader.height)), 1.5)

    def _handles(self) -> list[Handle]:
        s, shot = self.session, self.current_shot()
        if s is None or shot is None:
            return []
        out = []
        for i, a in enumerate(shot.anchors):
            if a.kind == AnchorKind.POINT and shot.source == "auto" and len(shot.anchors) > 8:
                continue  # dense auto samples: only show the main anchors
            fp = shot.to_frame(np.array([[a.x, a.y]]), self.frame)
            pp = s.source_to_proxy(fp)[0]
            out.append(Handle(f"a{i}", float(pp[0]), float(pp[1]), KIND_COLORS[a.kind], KIND_LABELS[a.kind]))
        return out

    # ================================================================ editing
    def set_tool(self, key: str) -> None:
        self.tool = key
        self.shot_panel.select_tool(key)
        self.shot_panel.hint.setText(TOOL_HINTS.get(key, ""))
        self.view.set_placing(key != "select")

    def _ensure_shot(self) -> Shot | None:
        p = self.project
        if p is None:
            return None
        if self.current_shot() is None:
            self._snapshot()
            p.shots.append(Shot(impact_frame=self.frame))
            p.shots.sort(key=lambda s: s.impact_frame)
            self.shot_idx = next(i for i, s in enumerate(p.shots) if s.impact_frame == self.frame)
        return self.current_shot()

    def add_shot(self) -> None:
        p = self.project
        if p is None:
            return
        self._snapshot()
        shot = Shot(impact_frame=self.frame)
        if p.ball_start_hint:
            shot.set_anchor(AnchorKind.START, *p.ball_start_hint)
        p.shots.append(shot)
        p.shots.sort(key=lambda s: s.impact_frame)
        self.shot_idx = p.shots.index(shot)
        self.set_tool("start" if not p.ball_start_hint else "apex")
        self.on_project_changed()

    def delete_shot(self) -> None:
        p, shot = self.project, self.current_shot()
        if p is None or shot is None:
            return
        self._snapshot()
        p.shots.remove(shot)
        self.shot_idx = min(self.shot_idx, len(p.shots) - 1)
        self.on_project_changed()

    def set_impact(self) -> None:
        shot = self._ensure_shot()
        if shot is None:
            return
        self._snapshot()
        shot.impact_frame = self.frame
        if shot.land_frame is not None and shot.land_frame <= self.frame:
            shot.land_frame = None
        self.project.shots.sort(key=lambda s: s.impact_frame)  # type: ignore[union-attr]
        self.shot_idx = self.project.shots.index(shot)  # type: ignore[union-attr]
        self.on_project_changed()

    def set_land_frame(self) -> None:
        shot = self.current_shot()
        if shot is None or self.frame <= shot.impact_frame:
            self.statusBar().showMessage("Lande-Frame muss nach dem Impact liegen", 3000)
            return
        self._snapshot()
        shot.land_frame = float(self.frame)
        for a in shot.anchors:
            a.t = None  # switch to manual timing
        self.on_project_changed()

    def clear_offsets(self) -> None:
        shot = self.current_shot()
        if shot and shot.offsets:
            self._snapshot()
            shot.offsets.clear()
            self.on_project_changed()

    def _click_to_ref(self, shot: Shot, x: float, y: float) -> tuple[float, float]:
        assert self.session is not None
        src = self.session.proxy_to_source(np.array([[x, y]]))
        ref = shot.to_ref(src, self.frame)[0]
        return float(ref[0]), float(ref[1])

    def on_view_click(self, x: float, y: float) -> None:
        if self.project is None or self.tool == "select":
            self.view.selected = None
            self.view.update()
            return
        shot = self._ensure_shot()
        if shot is None:
            return
        self._snapshot()
        if self.tool == "offset":
            self._add_offset(shot, x, y)
        else:
            rx, ry = self._click_to_ref(shot, x, y)
            if self.tool == "point":
                self._insert_point(shot, rx, ry)
            else:
                kind = AnchorKind(self.tool)
                shot.set_anchor(kind, rx, ry)
                if kind == AnchorKind.START:
                    self.project.ball_start_hint = (rx, ry)  # type: ignore[union-attr]
                nxt = {"start": "apex", "apex": "land", "land": "select"}[self.tool]
                if nxt == "apex" and shot.anchor(AnchorKind.APEX):
                    nxt = "land" if not shot.anchor(AnchorKind.LAND) else "select"
                if nxt == "land" and shot.anchor(AnchorKind.LAND):
                    nxt = "select"
                self.set_tool(nxt)
        self.on_project_changed()

    def _insert_point(self, shot: Shot, rx: float, ry: float) -> None:
        path = shot.path()
        new = Anchor(rx, ry, AnchorKind.POINT)
        if path is None:
            shot.anchors.insert(max(1, len(shot.anchors) - 1), new)
            return
        us = np.linspace(0, 1, 800)
        pts = path.evaluate(us)
        u = us[int(np.argmin(np.hypot(pts[:, 0] - rx, pts[:, 1] - ry)))]
        idx = int(np.searchsorted(path.knots, u))
        idx = min(max(idx, 1), len(shot.anchors) - 1)
        if shot.uses_anchor_times():
            a, b = shot.anchors[idx - 1], shot.anchors[idx]
            new.t = 0.5 * (a.t + b.t)  # type: ignore[operator]
        shot.anchors.insert(idx, new)

    def _add_offset(self, shot: Shot, x: float, y: float) -> None:
        """Correction keyframe: the tracer head should be at (x, y) in this frame.

        If the correction has no neighbour keyframes yet, zero keyframes are added at
        the closest well-tracked frames, so the correction stays local.
        """
        assert self.session is not None and self.project is not None
        path = shot.path()
        if path is None:
            return
        f = self.frame
        u = shot.head_u(f, self.project.fps)
        ref = path.evaluate(u if u is not None else 0.0)
        shot.offsets = [o for o in shot.offsets if o.frame != f]
        base = shot.to_frame(ref, f)[0] - shot.offset_at(f)
        target = self.session.proxy_to_source(np.array([[x, y]]))[0]
        d = target - base
        if not any(o.frame < f for o in shot.offsets):
            shot.offsets.append(OffsetKeyframe(self._good_neighbour(shot, f, -1), 0.0, 0.0))
        if not any(o.frame > f for o in shot.offsets):
            shot.offsets.append(OffsetKeyframe(self._good_neighbour(shot, f, 1), 0.0, 0.0))
        shot.offsets.append(OffsetKeyframe(f, float(d[0]), float(d[1])))
        shot.offsets.sort(key=lambda o: o.frame)

    def _good_neighbour(self, shot: Shot, f: int, direction: int) -> int:
        """Nearest frame in ``direction`` with good camera tracking (fallback: 1/3 s away)."""
        assert self.project is not None
        n = self.project.frame_count
        default = int(min(max(f + direction * max(2, round(self.project.fps / 3)), 0), n - 1))
        if shot.camera.mode != "tracked":
            return default
        g = f + direction
        while 0 <= g < n and shot.camera.covers(g):
            if shot.camera.conf(g) >= 0.5:
                return g
            g += direction
        return default

    def on_handle_moved(self, key: str, x: float, y: float) -> None:
        shot = self.current_shot()
        if shot is None or not key.startswith("a"):
            return
        i = int(key[1:])
        if not (0 <= i < len(shot.anchors)):
            return
        if not self._drag_snapshot:
            self._snapshot()
            self._drag_snapshot = True
        rx, ry = self._click_to_ref(shot, x, y)
        shot.anchors[i].x, shot.anchors[i].y = rx, ry
        if shot.anchors[i].kind == AnchorKind.START and self.project:
            self.project.ball_start_hint = (rx, ry)
        self._preview_shots = None
        self.dirty = True
        self.refresh()

    def _end_drag(self) -> None:
        self._drag_snapshot = False
        self.on_project_changed()

    def delete_selected(self) -> None:
        shot, key = self.current_shot(), self.view.selected
        if shot is None or not key or not key.startswith("a"):
            return
        i = int(key[1:])
        if 0 <= i < len(shot.anchors) and shot.anchors[i].kind in (AnchorKind.POINT, AnchorKind.APEX):
            self._snapshot()
            del shot.anchors[i]
            self.view.selected = None
            self.on_project_changed()

    def on_params_changed(self) -> None:
        shot, p = self.current_shot(), self.project
        if shot is None or p is None:
            return
        self._snapshot()
        sp = self.shot_panel
        from kpmn_tracer.trace.timing import EasingTiming

        shot.timing = EasingTiming(sp.boost.value(), sp.decay.value(), sp.late.value())
        shot.shape.launch_steepness = sp.launch.value()
        shot.shape.descent_steepness = sp.descent.value()
        newly_occluding = sp.occlude.isChecked() and not shot.occlude
        shot.occlude = sp.occlude.isChecked()
        if not shot.uses_anchor_times():
            shot.land_frame = shot.impact_frame + sp.duration.value() * p.fps
        self.on_project_changed()
        if newly_occluding:
            self.compute_masks_for_shot()

    def on_style_changed(self) -> None:
        if self.project is None:
            return
        self.project.style = self.style_panel.style_obj
        self.dirty = True
        self.refresh()

    def track_camera(self, force: bool = False) -> None:
        shot = self.current_shot()
        if self.session is None or shot is None:
            return
        from kpmn_tracer.camera.shot_camera import analyze_shot_camera

        from kpmn_tracer.camera.tracker import track_range_for_shot
        from kpmn_tracer.segmentation.provider import compute_masks, tracking_mask_fn

        sess = self.session
        use_mask = bool(sess.project.settings.get("use_person_mask", True))
        prog = QProgressDialog("Personen-Maske + Kamera-Tracking …", "Abbrechen", 0, 1000, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)

        def job(pr, cancel):
            p = sess.project
            masks = None
            if use_mask:
                a, b = track_range_for_shot(shot.impact_frame, shot.flight_frames(p.fps), p.fps, p.frame_count)
                try:
                    masks = compute_masks(sess, a, b, progress=lambda f: pr(0.5 * f), cancel=cancel)
                except (FileNotFoundError, ImportError, RuntimeError) as exc:
                    log.warning("Person mask unavailable, tracking without: %s", exc)
            mfn = tracking_mask_fn(masks, (sess.reader.width, sess.reader.height)) if masks else None
            off = 0.5 if use_mask else 0.0
            cam = analyze_shot_camera(sess, shot, mfn, progress=lambda f: pr(off + (1 - off) * f),
                                      cancel=cancel, force_tracking=force)
            return cam, masks

        task = self.tasks.start(job)
        task.progress.connect(lambda f: prog.setValue(int(f * 1000)))
        prog.canceled.connect(task.cancel)

        def done(result) -> None:
            cam, masks = result
            prog.close()
            if masks is not None:
                self._masks = masks
            if shot not in sess.project.shots:
                return
            self._snapshot()
            shot.camera = cam
            msg = "Stativ erkannt" if cam.mode == "tripod" else "Kamera getrackt"
            self.statusBar().showMessage(msg, 5000)
            self.on_project_changed()

        task.finished.connect(done)
        task.failed.connect(lambda msg: (prog.close(), QMessageBox.critical(self, "Tracking fehlgeschlagen", msg)))
        task.cancelled.connect(prog.close)

    def compute_masks_for_shot(self) -> None:
        """Make sure person masks exist for the current shot (needed for occlusion)."""
        shot, sess = self.current_shot(), self.session
        if shot is None or sess is None:
            return
        from kpmn_tracer.segmentation.provider import _has_masks, compute_masks, shot_mask_range

        a, b = shot_mask_range(sess, shot)
        if _has_masks(self._masks, a, b):
            self.refresh()
            return
        prog = QProgressDialog("Personen-Maske wird berechnet …", "Abbrechen", 0, 1000, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        task = self.tasks.start(lambda pr, cancel: compute_masks(sess, a, b, progress=pr, cancel=cancel))
        task.progress.connect(lambda f: prog.setValue(int(f * 1000)))
        prog.canceled.connect(task.cancel)
        task.finished.connect(lambda m: (prog.close(), setattr(self, "_masks", m), self.refresh()))
        task.failed.connect(lambda msg: (prog.close(), QMessageBox.warning(self, "Personen-Maske", msg)))
        task.cancelled.connect(prog.close)

    # ================================================================ impacts
    def candidates(self):
        from kpmn_tracer.ball.impact import ImpactCandidate

        p = self.project
        if p is None:
            return []
        return [ImpactCandidate.from_dict(d) for d in p.settings.get("impact_candidates", [])]

    def _open_candidates(self):
        p = self.project
        shots = p.shots if p else []
        return [c for c in self.candidates() if not any(abs(s.impact_frame - c.frame) <= 2 for s in shots)]

    def _ball_hint(self) -> tuple[tuple[float, float] | None, int | None]:
        """Resting ball position (source px) and a frame where it is visible."""
        shot = self.current_shot()
        if shot is not None and shot.anchor(AnchorKind.START) is not None:
            a = shot.anchor(AnchorKind.START)
            pos = shot.to_frame(np.array([[a.x, a.y]]), shot.impact_frame)[0]
            return (float(pos[0]), float(pos[1])), shot.impact_frame
        p = self.project
        if p is not None and p.ball_start_hint is not None:
            return p.ball_start_hint, self.frame
        return None, None

    def detect_impacts(self) -> None:
        if self.session is None:
            return
        from kpmn_tracer.ball.impact import detect_impacts

        sess = self.session
        hint, hint_frame = self._ball_hint()
        prog = QProgressDialog("Impacts werden gesucht …", "Abbrechen", 0, 1000, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        task = self.tasks.start(
            lambda pr, cancel: detect_impacts(sess, hint, hint_frame, progress=pr, cancel=cancel))
        task.progress.connect(lambda f: prog.setValue(int(f * 1000)))
        prog.canceled.connect(task.cancel)

        def done(cands) -> None:
            prog.close()
            self._snapshot()
            sess.project.settings["impact_candidates"] = [c.to_dict() for c in cands]
            sure = sum(c.confidence >= 0.5 for c in cands)
            src = "Audio + Video" if hint else "nur Audio (Ball nicht markiert)"
            self.shot_panel.auto_status.setText(f"{len(cands)} Kandidaten, {sure} sicher – {src}. "
                                                "Magenta-Marker in der Timeline anklicken.")
            self.on_project_changed()

        task.finished.connect(done)
        task.failed.connect(lambda msg: (prog.close(), QMessageBox.critical(self, "Impact-Erkennung", msg)))
        task.cancelled.connect(prog.close)

    def _shot_from_candidate(self, c) -> Shot:
        from kpmn_tracer.ball.impact import locate_ball

        shot = Shot(impact_frame=c.frame, confidence=c.confidence, label="+".join(c.sources))
        hint = c.ball_pos or (self.project.ball_start_hint if self.project else None)
        if hint is not None and self.session is not None:
            s = self.session
            hp = s.source_to_proxy(np.array([hint]))[0]
            g = s.reader.gray(c.frame)
            loc = locate_ball(g, (float(hp[0]), float(hp[1])), search_r=max(12.0, 0.03 * max(g.shape)))
            if loc is not None:
                pos = s.proxy_to_source(np.array([[loc[0], loc[1]]]))[0]
                shot.set_anchor(AnchorKind.START, float(pos[0]), float(pos[1]))
        return shot

    def adopt_candidate(self) -> None:
        p = self.project
        cands = self._open_candidates()
        if p is None or not cands:
            self.statusBar().showMessage("Kein offener Impact-Kandidat", 3000)
            return
        c = min(cands, key=lambda c: abs(c.frame - self.frame))
        self._snapshot()
        shot = self._shot_from_candidate(c)
        p.shots.append(shot)
        p.shots.sort(key=lambda s: s.impact_frame)
        self.shot_idx = p.shots.index(shot)
        self.goto(shot.impact_frame)
        self.set_tool("apex" if shot.anchor(AnchorKind.START) else "start")
        self.on_project_changed()

    def adopt_all_candidates(self) -> None:
        p = self.project
        if p is None:
            return
        new = [c for c in self._open_candidates() if c.confidence >= 0.5]
        if not new:
            self.statusBar().showMessage("Keine neuen sicheren Kandidaten", 3000)
            return
        self._snapshot()
        for c in new:
            p.shots.append(self._shot_from_candidate(c))
        p.shots.sort(key=lambda s: s.impact_frame)
        self.shot_idx = 0
        self.statusBar().showMessage(f"{len(new)} Schläge angelegt", 4000)
        self.on_project_changed()

    # ================================================================ auto tracking
    def _run_task(self, title: str, fn, done) -> None:
        prog = QProgressDialog(title, "Abbrechen", 0, 1000, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(300)
        task = self.tasks.start(fn)
        task.progress.connect(lambda f: prog.setValue(int(f * 1000)))
        prog.canceled.connect(task.cancel)
        task.finished.connect(lambda r: (prog.close(), done(r)))
        task.failed.connect(lambda msg: (prog.close(), QMessageBox.warning(self, title.rstrip(" …"), msg)))
        task.cancelled.connect(prog.close)

    def _analysis_options(self):
        from kpmn_tracer.analysis import AnalysisOptions

        st = self.session.project.settings if self.session else {}
        return AnalysisOptions(use_person_mask=bool(st.get("use_person_mask", True)),
                               detector=st.get("detector", "classic"), yolo_model=st.get("yolo_model"))

    def auto_track_shot(self) -> None:
        shot, sess = self.current_shot(), self.session
        if shot is None or sess is None:
            self.statusBar().showMessage("Erst einen Schlag anlegen (N) und den Ball markieren", 4000)
            return
        if shot.anchor(AnchorKind.START) is None and sess.project.ball_start_hint is None:
            QMessageBox.information(self, "Ball tracken", "Bitte im Impact-Frame zuerst mit „Start“ auf den Ball klicken.")
            return
        from kpmn_tracer.analysis import AnalysisOptions, analyze_shot

        work = Shot.from_dict(shot.to_dict())  # analyse a copy; apply on success (undo-able)
        opts = self._analysis_options()

        def done(result) -> None:
            if shot not in sess.project.shots:
                return
            self._snapshot()
            idx = sess.project.shots.index(shot)
            sess.project.shots[idx] = work
            self._masks = None
            from kpmn_tracer.segmentation.provider import load_masks

            self._masks = load_masks(sess)
            if result is None:
                msg = "Ball nicht gefunden – Punkte vorbefüllt, bitte von Hand setzen"
            elif result.confidence < 0.5:
                msg = f"Unsicher ({result.confidence:.0%}) – Start/Apex/Landung vorbefüllt, bitte prüfen"
            else:
                msg = f"Ball getrackt: {result.n_detections} Detektionen, Konfidenz {result.confidence:.0%}"
            self.statusBar().showMessage(msg, 8000)
            self.shot_panel.auto_status.setText(msg)
            self.set_tool("select")
            self.on_project_changed()

        self._run_task("Ball wird getrackt …",
                       lambda pr, cancel: analyze_shot(sess, work, opts, pr, cancel), done)

    def analyze_whole_clip(self) -> None:
        sess = self.session
        if sess is None:
            return
        from kpmn_tracer.analysis import AnalysisOptions, analyze_clip

        hint, hint_frame = self._ball_hint()
        if hint is None:
            QMessageBox.information(self, "Clip analysieren",
                                    "Bitte zuerst in einem Frame mit ruhendem Ball einen Schlag anlegen (N) "
                                    "und mit „Start“ auf den Ball klicken.")
            return
        opts = self._analysis_options()
        self._snapshot()

        def done(new) -> None:
            from kpmn_tracer.segmentation.provider import load_masks

            self._masks = load_masks(sess)
            # drop the helper shot used only to mark the ball if it has no landing
            sess.project.shots = [s for s in sess.project.shots if s.is_complete() or s in new]
            ok = sum((s.confidence or 0) >= 0.5 for s in new)
            msg = f"{len(new)} Schläge analysiert, {ok} sicher"
            self.statusBar().showMessage(msg, 8000)
            self.shot_panel.auto_status.setText(msg)
            self.shot_idx = 0 if sess.project.shots else -1
            self.on_project_changed()

        self._run_task("Clip wird analysiert …",
                       lambda pr, cancel: analyze_clip(sess, hint, hint_frame, opts, progress=pr, cancel=cancel),
                       done)

    def simplify_shot(self) -> None:
        shot, p = self.current_shot(), self.project
        if shot is None or p is None or not shot.is_complete():
            return
        self._snapshot()
        shot.simplify(p.fps)
        self.on_project_changed()

    # ================================================================ save / export
    def save(self) -> bool:
        if self.session is None:
            return True
        try:
            path = self.session.save()
        except OSError as exc:
            QMessageBox.critical(self, "Speichern fehlgeschlagen", str(exc))
            return False
        self.dirty = False
        self.statusBar().showMessage(f"Gespeichert: {path.name}", 4000)
        return True

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Änderungen speichern?", "Das Projekt wurde geändert. Speichern?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def export_dialog(self) -> None:
        p = self.project
        if p is None:
            return
        if not any(s.is_complete() for s in p.shots):
            QMessageBox.information(self, "Export", "Noch kein vollständiger Tracer (Start + Landung) gesetzt.")
            return
        dlg = ExportDialog(p, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.run_export(dlg.settings())

    def run_export(self, settings: ExportSettings) -> None:
        assert self.session is not None
        snapshot = Project.from_dict(self.session.project.to_dict())
        sess = self.session
        prog = QProgressDialog(f"Exportiere {EXPORT_LABELS[settings.fmt]} …", "Abbrechen", 0, 1000, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        def job(pr, cancel):
            occl = None
            if any(s.occlude for s in snapshot.shots):
                from kpmn_tracer.segmentation.provider import occlusion_for_session

                occl = occlusion_for_session(sess, cancel=cancel)
            return export(snapshot, settings, occl, pr, cancel)

        worker = self.tasks.start(job)
        worker.progress.connect(lambda f: prog.setValue(int(f * 1000)))
        prog.canceled.connect(worker.cancel)
        worker.finished.connect(lambda out: (prog.close(), self.statusBar().showMessage(f"Export fertig: {out}", 10000)))
        worker.failed.connect(lambda msg: (prog.close(), QMessageBox.critical(self, "Export fehlgeschlagen", msg)))
        worker.cancelled.connect(prog.close)

    def closeEvent(self, e) -> None:  # noqa: N802
        if not self._maybe_save():
            e.ignore()
            return
        self.play_timer.stop()
        self.tasks.cancel_all()
        if self.session:
            self.session.close()
        e.accept()
