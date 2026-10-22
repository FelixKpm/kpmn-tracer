"""Batch window: analyse a folder (range session), review every shot as a thumbnail, export."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from kpmn_tracer.batch import ClipResult, ShotReview, analyze_folder, export_confirmed, set_confirmed
from kpmn_tracer.gui.workers import TaskRunner
from kpmn_tracer.i18n import tr
from kpmn_tracer.project.presets import PresetStore

log = logging.getLogger(__name__)

ROLE = Qt.ItemDataRole.UserRole


class BatchWindow(QDialog):
    """Non-modal window. ``openShot(clip, impact_frame)`` asks the main window to open a shot."""

    openShot = Signal(str, int)

    def __init__(self, parent: QWidget | None = None, options_fn=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Batch – Range-Session"))
        self.resize(1100, 760)
        self.tasks = TaskRunner(self)
        self.options_fn = options_fn
        self._task = None

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setPlaceholderText(tr("Ordner mit Clips"))
        browse = QPushButton(tr("Ordner…"))
        browse.clicked.connect(self.browse)
        self.run_btn = QPushButton(tr("Analysieren"))
        self.run_btn.clicked.connect(self.run)
        self.cancel_btn = QPushButton(tr("Abbrechen"))
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(lambda: self._task and self._task.cancel())
        for w in (QLabel(tr("Ordner:")), self.folder, browse, self.run_btn, self.cancel_btn):
            top.addWidget(w)
        top.setStretch(1, 1)
        lay.addLayout(top)

        opts = QHBoxLayout()
        self.use_preset = QCheckBox(tr("Ballposition vom letzten Clip verwenden (gleicher Stativ-Standort)"))
        self.use_preset.setToolTip(tr("Nur einschalten, wenn alle Clips vom selben Stativ-Platz aus gefilmt sind."))
        self.use_preset.toggled.connect(self._update_preset_info)
        self.reanalyze = QCheckBox(tr("Bereits analysierte Clips neu berechnen"))
        self.reanalyze.setToolTip(tr("Unbestätigte Schläge werden verworfen und neu gesucht, bestätigte bleiben."))
        opts.addWidget(self.use_preset)
        opts.addWidget(self.reanalyze)
        opts.addStretch(1)
        lay.addLayout(opts)
        self.preset_info = QLabel()
        self.preset_info.setStyleSheet("color:#aaa;")
        self.preset_info.setWordWrap(True)
        lay.addWidget(self.preset_info)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        lay.addWidget(self.progress)

        self.list = QListWidget()
        self.list.setViewMode(QListView.ViewMode.IconMode)
        self.list.setIconSize(QSize(240, 240))
        self.list.setGridSize(QSize(270, 300))
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setWordWrap(True)
        self.list.itemChanged.connect(self._item_changed)
        self.list.itemDoubleClicked.connect(self._open_item)
        lay.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(QLabel(tr("Bestätigen ab")))
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0, 1)
        self.threshold.setSingleStep(0.05)
        self.threshold.setValue(0.8)
        bottom.addWidget(self.threshold)
        conf_btn = QPushButton(tr("Alle darüber bestätigen"))
        conf_btn.clicked.connect(self.confirm_above)
        bottom.addWidget(conf_btn)
        bottom.addStretch(1)
        self.fmt = QComboBox()
        for k, label in (("prores", "ProRes 4444 (Alpha)"), ("png", "PNG-Sequenz"), ("h264", "H.264 eingebrannt"),
                         ("h265", "H.265 eingebrannt")):
            self.fmt.addItem(tr(label), k)
        bottom.addWidget(self.fmt)
        self.export_btn = QPushButton(tr("Bestätigte exportieren"))
        self.export_btn.clicked.connect(self.export)
        bottom.addWidget(self.export_btn)
        lay.addLayout(bottom)
        hint = QLabel(tr("Häkchen = Schlag bestätigt. Doppelklick öffnet den Schlag im Editor zum Nachkorrigieren."))
        hint.setStyleSheet("color:#aaa;")
        lay.addWidget(hint)
        self._update_preset_info()

    # ------------------------------------------------------------ helpers
    def _update_preset_info(self) -> None:
        pre = PresetStore().load_position()
        if not self.use_preset.isChecked():
            self.preset_info.setText(tr("Ohne Ballposition werden Impacts nur über den Ton gefunden und nicht "
                                        "getrackt. Clips mit einem im Editor markierten Ball werden voll analysiert."))
        elif pre is None:
            self.preset_info.setText(tr("Noch keine Ballposition gespeichert: einen Schlag im Editor setzen und "
                                        "speichern – die Ballposition wird gemerkt."))
        else:
            self.preset_info.setText(tr("Ballposition vom letzten Clip: {x:.0%} / {y:.0%} des Bildes – wird pro "
                                        "Clip geprüft (nur verwendet, wenn dort ein Ball liegt).",
                                        x=pre.start[0], y=pre.start[1]))

    def browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Ordner mit Clips"), self.folder.text())
        if d:
            self.folder.setText(d)

    def _busy(self, on: bool) -> None:
        self.run_btn.setEnabled(not on)
        self.export_btn.setEnabled(not on)
        self.cancel_btn.setEnabled(on)

    # ------------------------------------------------------------ analysis
    def run(self) -> None:
        folder = Path(self.folder.text())
        if not folder.is_dir():
            QMessageBox.information(self, "Batch", tr("Bitte einen Ordner wählen."))
            return
        self.list.clear()
        preset = PresetStore().load_position() if self.use_preset.isChecked() else None
        opts = self.options_fn() if self.options_fn else None
        re = self.reanalyze.isChecked()
        self._busy(True)
        task = self.tasks.start(lambda pr, cancel: analyze_folder(folder, preset, opts, reanalyze=re,
                                                                   progress=pr, cancel=cancel))
        self._task = task
        task.progress.connect(lambda f: self.progress.setValue(int(f * 1000)))
        task.finished.connect(self._done)
        task.failed.connect(lambda m: (self._busy(False), QMessageBox.critical(self, "Batch", m)))
        task.cancelled.connect(lambda: self._busy(False))

    def _done(self, results: list[ClipResult]) -> None:
        self._busy(False)
        self.progress.setValue(1000)
        self.show_results(results)

    def show_results(self, results: list[ClipResult]) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for r in results:
            if r.error:
                it = QListWidgetItem(tr("{name}\nFehler: {error}", name=Path(r.clip).name, error=r.error))
                it.setForeground(QColor(230, 90, 90))
                self.list.addItem(it)
                continue
            if not r.shots:
                self.list.addItem(QListWidgetItem(tr("{name}\nkeine Schläge gefunden", name=Path(r.clip).name)))
            for s in r.shots:
                self.list.addItem(self._item(s))
        self.list.blockSignals(False)

    def _item(self, s: ShotReview) -> QListWidgetItem:
        it = QListWidgetItem(tr("{name} · Schlag {i}\n{t:.1f} s · Konfidenz {conf:.0%}", name=Path(s.clip).name,
                                i=s.index + 1, t=s.time_s, conf=s.confidence))
        if s.thumbnail:
            it.setIcon(QIcon(QPixmap(s.thumbnail)))
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if s.confirmed else Qt.CheckState.Unchecked)
        if s.confidence < 0.5:
            it.setForeground(QColor(230, 160, 60))
        it.setData(ROLE, s)
        return it

    def items(self) -> list[QListWidgetItem]:
        return [self.list.item(i) for i in range(self.list.count()) if self.list.item(i).data(ROLE)]

    def _item_changed(self, it: QListWidgetItem) -> None:
        s: ShotReview | None = it.data(ROLE)
        if s is None:
            return
        on = it.checkState() == Qt.CheckState.Checked
        if on != s.confirmed:
            set_confirmed(s.clip, s.shot_id, on)
            s.confirmed = on
            it.setData(ROLE, s)

    def confirm_above(self) -> None:
        for it in self.items():
            s: ShotReview = it.data(ROLE)
            if s.confidence >= self.threshold.value():
                it.setCheckState(Qt.CheckState.Checked)

    def _open_item(self, it: QListWidgetItem) -> None:
        s: ShotReview | None = it.data(ROLE)
        if s is not None:
            self.openShot.emit(s.clip, s.impact_frame)

    # ------------------------------------------------------------ export
    def export(self) -> None:
        folder = Path(self.folder.text())
        if not folder.is_dir():
            return
        fmt = self.fmt.currentData()
        self._busy(True)
        task = self.tasks.start(lambda pr, cancel: export_confirmed(folder, fmt, pr, cancel))
        self._task = task
        task.progress.connect(lambda f: self.progress.setValue(int(f * 1000)))

        def done(outs) -> None:
            self._busy(False)
            QMessageBox.information(self, "Export", tr("{n} Overlays exportiert:", n=len(outs)) + "\n" +
                                    "\n".join(str(o) for o in outs) if outs else tr("Nichts bestätigt."))

        task.finished.connect(done)
        task.failed.connect(lambda m: (self._busy(False), QMessageBox.critical(self, "Export", m)))
        task.cancelled.connect(lambda: self._busy(False))

    def closeEvent(self, e) -> None:  # noqa: N802
        self.tasks.cancel_all()
        e.accept()
