"""Guided tour through the main window (shown once on first start, again via Hilfe).

An overlay dims the window except for the area being explained and shows a
speech bubble next to it. The first step asks for the UI language. Steps name their target lazily (a callable returning
widgets), so the tour adapts to the actual layout; targets inside the scrolled
side panel are scrolled into view first.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from kpmn_tracer.gui.keys import native
from kpmn_tracer.i18n import LANGUAGES, language, tr

ACCENT = QColor(255, 200, 40)  # tracer yellow, also used for the impact markers
DIM = QColor(0, 0, 0, 165)


@dataclass
class TourStep:
    title: str
    text: str  # rich text
    targets: Callable[[], Sequence[QWidget]] | None = None  # None: centred, nothing highlighted
    choices: dict[str, str] | None = None  # buttons instead of "Weiter" (key -> label), see TourOverlay.chosen


class TourOverlay(QWidget):
    """Dimmed overlay with a highlighted rectangle and an explanation bubble."""

    finished = Signal(bool)  # True: went through to the end, False: skipped
    chosen = Signal(str)  # key of a choice button (the window decides how the tour goes on)

    def __init__(self, window: QWidget, steps: list[TourStep], scroll: QScrollArea | None = None) -> None:
        super().__init__(window)
        self.window_ = window
        self.steps = steps
        self.scroll = scroll
        self.index = 0
        self.hole = QRect()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.bubble = QFrame(self)
        self.bubble.setObjectName("tourBubble")
        self.bubble.setStyleSheet(
            "#tourBubble { background: #26262b; border: 2px solid rgb(255,200,40); border-radius: 10px; }"
            "QLabel { color: #e6e6e6; background: transparent; }"
            "#tourTitle { color: rgb(255,200,40); font-size: 16px; font-weight: 600; }"
            "#tourCount { color: #9a9a9a; }")
        bl = QVBoxLayout(self.bubble)
        bl.setContentsMargins(16, 14, 16, 12)
        bl.setSpacing(8)
        self.title = QLabel()
        self.title.setObjectName("tourTitle")
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setMinimumWidth(360)
        bl.addWidget(self.title)
        bl.addWidget(self.text)
        self.choice_row = QHBoxLayout()
        bl.addLayout(self.choice_row)
        self.choice_btns: list[QPushButton] = []
        row = QHBoxLayout()
        self.count = QLabel()
        self.count.setObjectName("tourCount")
        self.skip_btn = QPushButton(tr("Tour beenden"))
        self.back_btn = QPushButton(tr("Zurück"))
        self.next_btn = QPushButton(tr("Weiter"))
        self.next_btn.setDefault(True)
        row.addWidget(self.count)
        row.addStretch(1)
        for b in (self.skip_btn, self.back_btn, self.next_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row.addWidget(b)
        bl.addLayout(row)
        self.skip_btn.clicked.connect(lambda: self.finish(False))
        self.back_btn.clicked.connect(lambda: self.show_step(self.index - 1))
        self.next_btn.clicked.connect(self.next)

        window.installEventFilter(self)

    # ------------------------------------------------------------ control
    def start(self, index: int = 0) -> None:
        self.setGeometry(self.window_.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.show_step(index)
        QTimer.singleShot(0, self._layout_step)  # once more when the new widgets are laid out

    def next(self) -> None:
        if self.steps[self.index].choices:
            return  # answered with a choice button
        if self.index >= len(self.steps) - 1:
            self.finish(True)
        else:
            self.show_step(self.index + 1)

    def finish(self, completed: bool) -> None:
        self.window_.removeEventFilter(self)
        self.hide()
        self.finished.emit(completed)
        self.deleteLater()

    def show_step(self, i: int) -> None:
        self.index = max(0, min(i, len(self.steps) - 1))
        st = self.steps[self.index]
        self.title.setText(tr(st.title))
        self.text.setText(native(tr(st.text)))
        n = len(self.steps)
        self.count.setText(f"{self.index + 1} / {n}")
        self.back_btn.setEnabled(self.index > 0)
        self.next_btn.setText(tr("Los geht's") if self.index == n - 1 else tr("Weiter"))
        self.next_btn.setVisible(not st.choices)
        for b in self.choice_btns:
            b.deleteLater()
        self.choice_btns = []
        for key, label in (st.choices or {}).items():
            b = QPushButton(label)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _c=False, k=key: self.chosen.emit(k))
            self.choice_row.addWidget(b)
            self.choice_btns.append(b)
        self._layout_step()

    # ------------------------------------------------------------ geometry
    def _target_rect(self) -> QRect:
        st = self.steps[self.index]
        widgets = [w for w in (st.targets() if st.targets else [])
                   if w is not None and w.isVisible() and not QWidget.size(w).isEmpty()]  # macOS: native menu bar
        rect = QRect()
        for w in widgets:
            if self.scroll is not None and self.scroll.widget() is not None and self.scroll.widget().isAncestorOf(w):
                self.scroll.ensureWidgetVisible(w, 0, 0)
            r = QRect(w.mapTo(self.window_, QPoint(0, 0)), QWidget.size(w))  # panels may shadow size()
            if self.scroll is not None and self.scroll.viewport().isAncestorOf(w):
                vp = self.scroll.viewport()
                r = r.intersected(QRect(vp.mapTo(self.window_, QPoint(0, 0)), vp.size()))
            rect = r if rect.isNull() else rect.united(r)
        return rect.adjusted(-6, -6, 6, 6) if not rect.isNull() else QRect()

    def _layout_step(self) -> None:
        self.setGeometry(self.window_.rect())
        self.hole = self._target_rect()
        self.bubble.setMaximumWidth(min(460, self.width() - 32))
        # explicit size: adjustSize does not always account for how high the wrapped text gets
        lay = self.bubble.layout()
        lay.activate()
        bw = min(max(lay.sizeHint().width(), self.bubble.minimumSizeHint().width()), self.bubble.maximumWidth())
        self.bubble.resize(bw, lay.totalHeightForWidth(bw))
        b = self.bubble.size()
        W, H, m = self.width(), self.height(), 16
        if self.hole.isNull():
            pos = QPoint((W - b.width()) // 2, (H - b.height()) // 2)
        else:
            h = self.hole
            # the side with the most free room; bubble vertically/horizontally aligned with the target
            room = {"right": W - h.right(), "left": h.left(), "below": H - h.bottom(), "above": h.top()}
            fits = {k: v for k, v in room.items()
                    if v >= (b.width() if k in ("right", "left") else b.height()) + 2 * m}
            side = max(fits or room, key=lambda k: (fits or room)[k])
            if side == "right":
                pos = QPoint(h.right() + m, h.top())
            elif side == "left":
                pos = QPoint(h.left() - m - b.width(), h.top())
            elif side == "below":
                pos = QPoint(h.left(), h.bottom() + m)
            else:
                pos = QPoint(h.left(), h.top() - m - b.height())
        pos.setX(max(m, min(pos.x(), W - b.width() - m)))
        pos.setY(max(m, min(pos.y(), H - b.height() - m)))
        self.bubble.move(pos)
        self.bubble.raise_()
        self.update()

    # ------------------------------------------------------------ events
    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:  # noqa: N802
        if obj is self.window_ and ev.type() in (QEvent.Type.Resize, QEvent.Type.LayoutRequest):
            self._layout_step()
        return False

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRect(self.rect().toRectF())
        if not self.hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(self.hole.toRectF(), 8, 8)
            path = path.subtracted(hole)
        p.fillPath(path, DIM)
        if not self.hole.isNull():
            p.setPen(QPen(ACCENT, 3))
            p.drawRoundedRect(self.hole.toRectF(), 8, 8)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self.finish(False)
        elif k in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.next()
        elif k == Qt.Key.Key_Left:
            self.show_step(self.index - 1)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        e.accept()  # the window underneath stays untouched while the tour runs


def main_window_steps(w) -> list[TourStep]:
    """The tour of :class:`MainWindow` (``w``)."""
    sp = w.shot_panel
    return [
        TourStep("Sprache · Language",
                 "Möchtest du KPMN Tracer auf Deutsch oder auf Englisch benutzen?<br>"
                 "<i>Would you like to use KPMN Tracer in German or in English?</i><br><br>"
                 "<span style='color:#9a9a9a'>Später änderbar unter <i>Einstellungen</i>. · "
                 "You can change this later in <i>Settings</i>.</span>",
                 choices={k: ("▸ " if k == language() else "") + v for k, v in LANGUAGES.items()}),
        TourStep("Willkommen bei KPMN Tracer",
                 "Diese kurze Tour zeigt dir, was wo ist. Der Ablauf ist immer gleich:<br><br>"
                 "<b>1.</b> Clip öffnen &nbsp;→&nbsp; <b>2.</b> Ball markieren &nbsp;→&nbsp; "
                 "<b>3.</b> automatisch tracken lassen &nbsp;→&nbsp; <b>4.</b> prüfen und nachbessern "
                 "&nbsp;→&nbsp; <b>5.</b> exportieren.<br><br>"
                 "Mit <b>→</b> / <b>Enter</b> weiter, <b>Esc</b> beendet die Tour. Du findest sie jederzeit "
                 "wieder unter <i>Hilfe › Einführungstour</i>."),
        TourStep("Vorschau",
                 "Hier siehst du den Clip mit dem Tracer. Öffnen mit <b>Strg+O</b> oder die Videodatei einfach "
                 "hierher ziehen.<br><br>"
                 "Mausrad = zoomen, rechte Maustaste ziehen = verschieben, <b>F</b> = einpassen. "
                 "Klicks ins Bild setzen Punkte – je nachdem, welches <i>Werkzeug</i> gerade aktiv ist.",
                 lambda: [w.view]),
        TourStep("Zeitleiste",
                 "Klicken oder ziehen, um durch den Clip zu springen.<br><br>"
                 "<span style='color:rgb(255,200,40)'>▲ gelb</span> = Impact eines Schlags, "
                 "<span style='color:rgb(80,170,255)'>│ blau</span> = Landung, "
                 "<span style='color:rgb(230,80,230)'>▲ magenta</span> = erkannter Impact-Kandidat, "
                 "<span style='color:rgb(230,70,60)'>rot</span> = Frames, in denen das Kamera-Tracking "
                 "unsicher ist.",
                 lambda: [w.timeline]),
        TourStep("Abspielen und Frame für Frame",
                 "<b>Leertaste</b> spielt ab, <b>← / →</b> gehen einen Frame, mit <b>Shift</b> zehn Frames. "
                 "Rechts daneben steht, wo du bist – auch relativ zum Impact („Impact +12“).",
                 lambda: [w.btn[k] for k in ("first", "prev10", "prev", "play", "next", "next10", "last")]
                 + [w.frame_label]),
        TourStep("Schläge",
                 "Ein Clip kann mehrere Schläge enthalten. Geh zu einem Frame, in dem der Ball noch ruhig "
                 "liegt, und drück <b>N</b> (<i>Neuer Schlag</i>). Danach klickst du in der Vorschau auf den "
                 "Ball – das ist der Startpunkt.",
                 lambda: [sp.shots_box]),
        TourStep("Automatik – der schnelle Weg",
                 "Ist der Ball markiert, macht <b>Ball tracken (B)</b> den Rest: Kamerabewegung, Golfer und "
                 "Ballflug werden analysiert, der Tracer entsteht von selbst.<br><br>"
                 "<i>Ganzen Clip analysieren</i> findet alle Schläge eines langen Clips (über das Schlaggeräusch) "
                 "und trackt jeden. Bei unsicherem Ergebnis sind Start, Apex und Landung vorbefüllt – "
                 "du ziehst sie nur noch zurecht.",
                 lambda: [sp.auto_box]),
        TourStep("Werkzeuge – von Hand setzen und korrigieren",
                 "<b>Start (S)</b>, <b>Apex (A)</b>, <b>Landung (L)</b>: die drei Punkte der Flugkurve. "
                 "<b>Punkt (P)</b> biegt die Kurve (Draw/Fade).<br>"
                 "<b>Ball hier (H)</b>: in einem Frame auf den Ball klicken – der Tracer-Kopf ist dann genau "
                 "dort. Ideal, wenn der Tracer hinter dem Ball herhängt.<br>"
                 "<b>Korrektur (K)</b>: verschiebt den Tracer nur in einzelnen Frames.<br>"
                 "Mit <b>Auswählen (V)</b> ziehst du vorhandene Punkte.",
                 lambda: [sp.tool_box]),
        TourStep("Kamera (aus der Hand gefilmt)",
                 "Wackelt die Kamera, rechnet <b>Kamera tracken (T)</b> die Bewegung heraus, damit der Tracer "
                 "am Himmel „klebt“. Vom Stativ wird das automatisch erkannt. „Ball tracken“ erledigt das "
                 "gleich mit.",
                 lambda: [sp.cam_box]),
        TourStep("Flugkurve feinjustieren",
                 "Flugzeit, wie steil der Ball startet und fällt und wie schnell er unterwegs ist. "
                 "Nur für den manuellen Weg nötig.<br><br>"
                 "<b>Tracer hinter Golfer</b> lässt den Tracer hinter dir verschwinden, wenn du vor der "
                 "Flugbahn stehst.",
                 lambda: [sp.curve_box]),
        TourStep("Aussehen",
                 "Farbe, Dicke, Glow, Schatten, ganzer Pfad oder nur ein Schweif. Eigene Looks speicherst "
                 "du als <b>Preset</b> und hast sie bei jedem Clip wieder.",
                 lambda: [w.style_panel]),
        TourStep("Text-Einblendung",
                 "Optional ein Text zum Schlag, z. B. „7-Eisen · 145 m“ – animiert am Apex, am Landepunkt "
                 "oder in einer Ecke.",
                 lambda: [w.text_panel]),
        TourStep("Exportieren",
                 "<b>Exportieren… (Strg+E)</b>: ProRes mit Transparenz für DaVinci Resolve (einfach über den "
                 "Originalclip legen) oder ein fertiges MP4 zum direkten Posten.<br>"
                 "<b>Bild… (Strg+Umschalt+E)</b>: der aktuelle Frame mit Tracer als Foto in voller Auflösung "
                 "– für Bild-Beiträge.",
                 lambda: [w.still_btn, w.export_btn]),
        TourStep("Menüs",
                 "<i>Datei</i>: Speichern (<b>Strg+S</b>), Batch für ganze Range-Sessions (<b>Strg+B</b>), "
                 "<i>Projekt zurücksetzen</i> für einen Neuanfang.<br>"
                 "<i>Extras</i>: das <b>Scorecard Studio</b> für Scorecard-Grafiken.<br>"
                 "<i>Hilfe</i>: alle Tastenkürzel (<b>F1</b>) und diese Tour.<br><br>"
                 "Viel Spaß – und schöne Schläge!",
                 lambda: [w.menuBar()]),
    ]
