"""Small dialogs: export, settings, keyboard shortcut overview."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kpmn_tracer.io.export import FORMATS, ExportSettings, default_output
from kpmn_tracer.project.presets import AppDefaults
from kpmn_tracer.project.project_file import Project

EXPORT_LABELS = {"prores": "ProRes 4444 mit Alpha (.mov)", "png": "PNG-Sequenz mit Alpha",
                 "h264": "Eingebrannt H.264 (.mp4)", "h265": "Eingebrannt H.265 (.mp4)"}


def _buttons(dlg: QDialog) -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class ExportDialog(QDialog):
    def __init__(self, project: Project, default_fmt: str = "prores", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportieren")
        self.project = project
        f = QFormLayout(self)
        self.fmt = QComboBox()
        for k in FORMATS:
            self.fmt.addItem(EXPORT_LABELS[k], k)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(default_fmt)))
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
        self.only_confirmed = QCheckBox("Nur bestätigte Schläge")
        self.only_confirmed.setEnabled(any(s.confirmed for s in project.shots))
        f.addRow("Format", self.fmt)
        f.addRow("Ziel", row)
        f.addRow("CRF", self.crf)
        f.addRow(self.only_confirmed)
        info = QLabel(f"{project.width}×{project.height}, {project.frame_count} Frames @ "
                      f"{float(project.video.target_fps):.3f} fps – identisch zum Clip.")
        info.setStyleSheet("color:#999;")
        f.addRow(info)
        f.addRow(_buttons(self))
        self.fmt.currentIndexChanged.connect(self._update_default)
        self._update_default()

    def _update_default(self) -> None:
        fmt = self.fmt.currentData()
        self.path.setText(str(default_output(self.project, fmt)))
        self.crf.setEnabled(fmt in ("h264", "h265"))

    def _browse(self) -> None:
        if self.fmt.currentData() == "png":
            d = QFileDialog.getExistingDirectory(self, "Zielordner", str(Path(self.path.text()).parent))
            if d:
                self.path.setText(d)
        else:
            p, _ = QFileDialog.getSaveFileName(self, "Ziel", self.path.text())
            if p:
                self.path.setText(p)

    def settings(self) -> ExportSettings:
        return ExportSettings(self.fmt.currentData(), Path(self.path.text()), self.crf.value(),
                              only_confirmed=self.only_confirmed.isChecked())


class SettingsDialog(QDialog):
    def __init__(self, defaults: AppDefaults, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        f = QFormLayout(self)
        self.mask = QCheckBox("Personen-Maske beim Tracking verwenden (MediaPipe)")
        self.mask.setChecked(defaults.use_person_mask)
        self.mask_model = QComboBox()
        for k, label in (("multiclass", "Selfie multiclass (Standard, inkl. Schläger)"),
                         ("pose", "Pose (schnell, nur große Personen)"), ("deeplab", "DeepLab v3")):
            self.mask_model.addItem(label, k)
        self.mask_model.setCurrentIndex(max(0, self.mask_model.findData(defaults.mask_model)))
        self.detector = QComboBox()
        for k, label in (("classic", "Klassisch (Standard)"), ("yolo", "YOLO (ML)"), ("both", "Klassisch + YOLO")):
            self.detector.addItem(label, k)
        self.detector.setCurrentIndex(max(0, self.detector.findData(defaults.detector)))
        self.yolo = QLineEdit(defaults.yolo_model or "")
        self.yolo.setPlaceholderText("Pfad zu best.pt (nur für YOLO; benötigt requirements-ml.txt)")
        yb = QPushButton("…")
        yb.clicked.connect(self._pick_model)
        row = QHBoxLayout()
        row.addWidget(self.yolo)
        row.addWidget(yb)
        self.vfr = QComboBox()
        self.vfr.addItem("Frame für Frame (wie DaVinci Resolve)", "frames")
        self.vfr.addItem("Zeitbasiert neu abtasten", "resample")
        self.vfr.setCurrentIndex(max(0, self.vfr.findData(defaults.vfr_mode)))
        self.fmt = QComboBox()
        for k in FORMATS:
            self.fmt.addItem(EXPORT_LABELS[k], k)
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(defaults.export_format)))
        f.addRow(self.mask)
        f.addRow("Masken-Modell", self.mask_model)
        f.addRow("Ball-Erkennung", self.detector)
        f.addRow("YOLO-Modell", row)
        f.addRow("VFR-Clips (neue Projekte)", self.vfr)
        f.addRow("Standard-Exportformat", self.fmt)
        f.addRow(_buttons(self))
        self._defaults = defaults

    def _pick_model(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "YOLO-Modell", "", "PyTorch (*.pt)")
        if p:
            self.yolo.setText(p)

    def values(self) -> AppDefaults:
        d = self._defaults
        d.use_person_mask = self.mask.isChecked()
        d.mask_model = self.mask_model.currentData()
        d.detector = self.detector.currentData()
        d.yolo_model = self.yolo.text().strip() or None
        d.vfr_mode = self.vfr.currentData()
        d.export_format = self.fmt.currentData()
        return d


class ShortcutDialog(QDialog):
    def __init__(self, actions: list[QAction], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tastenkürzel")
        self.resize(520, 640)
        rows = [(a.text().replace("&", ""), a.shortcut().toString()) for a in actions if not a.shortcut().isEmpty()]
        t = QTableWidget(len(rows), 2)
        t.setHorizontalHeaderLabels(["Aktion", "Taste"])
        for i, (name, key) in enumerate(rows):
            t.setItem(i, 0, QTableWidgetItem(name))
            t.setItem(i, 1, QTableWidgetItem(key))
        t.resizeColumnsToContents()
        t.horizontalHeader().setStretchLastSection(True)
        t.verticalHeader().setVisible(False)
        lay = QVBoxLayout(self)
        lay.addWidget(t)
        lay.addWidget(QLabel("Maus: Rad = Zoom, rechte/mittlere Taste ziehen = verschieben, "
                             "Doppelklick rechts = einpassen."))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
