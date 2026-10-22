"""English UI: every German text is translated, the English window shows no German, the tour switches."""

from __future__ import annotations

import os
import re
import string
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from i18n_keys import all_keys  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractButton,
    QApplication,
    QComboBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QWidget,
)

from kpmn_tracer.i18n import language, set_language, tr  # noqa: E402
from kpmn_tracer.i18n_en import EN  # noqa: E402

GERMAN = re.compile(r"[äöüßÄÖÜ]|\b(der|die|das|und|nicht|mit|für|wird|werden|Schlag|Schläge|Ordner|Bild|"
                    r"zurück|Speichern|Einstellungen|Landung|Kamera|Werkzeug|Datei|Hilfe|Ansicht)\b")


@pytest.fixture(scope="module")
def app_qt() -> QApplication:
    return QApplication.instance() or QApplication([])


def fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def test_every_german_text_has_an_english_translation() -> None:
    keys = all_keys()
    missing = sorted(k for k in keys if k not in EN)
    assert not missing, missing
    assert not sorted(set(EN) - keys), "unused translations"
    for de, en in EN.items():
        assert fields(de) == fields(en), de
        assert not GERMAN.search(re.sub(r"Sprache", "", en)), en


@pytest.fixture()
def english():
    old = language()
    set_language("en")
    yield
    set_language(old)


def test_tr_formats_and_falls_back(english) -> None:
    assert tr("{n} Schläge angelegt", n=3) == "3 shots created"
    assert tr("Kein Text mit Übersetzung") == "Kein Text mit Übersetzung"
    set_language("de")
    assert tr("{n} Schläge angelegt", n=3) == "3 Schläge angelegt"


def visible_texts(root: QWidget) -> list[str]:
    out = []
    for w in [root, *root.findChildren(QWidget)]:
        out.append(w.toolTip())
        if isinstance(w, (QLabel, QAbstractButton)):
            out.append(w.text())
        elif isinstance(w, QGroupBox):
            out.append(w.title())
        elif isinstance(w, QLineEdit):
            out.append(w.placeholderText())
        elif isinstance(w, QComboBox):
            out += [w.itemText(i) for i in range(w.count())]
        out += [a.text() for a in w.actions()]
    return [t for t in out if t]


def test_english_window_shows_no_german(english, app_qt: QApplication) -> None:
    from kpmn_tracer.gui.batch_window import BatchWindow
    from kpmn_tracer.gui.dialogs import SettingsDialog, ShortcutDialog
    from kpmn_tracer.gui.main_window import MainWindow

    w = MainWindow()
    try:
        assert [a.text() for a in w.menuBar().actions()] == ["&File", "&Edit", "&View", "E&xtras", "&Help"]
        dialogs = [w, BatchWindow(w), SettingsDialog(w.defaults, w), ShortcutDialog(w.actions(), w)]
        german = [t for d in dialogs for t in visible_texts(d) if GERMAN.search(t)]
        assert not german, german
    finally:
        w.close()


def test_tour_asks_for_the_language_and_continues_in_english(app_qt: QApplication) -> None:
    from kpmn_tracer.gui.main_window import MainWindow

    set_language("de")
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    app_qt.processEvents()
    w.maybe_start_tour()
    t = w._tour
    assert t.steps[0].choices and not t.next_btn.isVisible()
    assert [b.text().lstrip("▸ ") for b in t.choice_btns] == ["Deutsch", "English"]
    try:
        t.choice_btns[1].click()  # English: the window is rebuilt, the tour goes on there
        app_qt.processEvents()
        assert language() == "en"
        new = next(x for x in app_qt.topLevelWidgets() if isinstance(x, MainWindow) and x.isVisible())
        assert new is not w and new.menuBar().actions()[0].text() == "&File"
        for _ in range(50):  # the tour restarts after a short delay
            app_qt.processEvents()
            if getattr(new, "_tour", None) is not None:
                break
            QApplication.instance().thread().msleep(10)
        assert new._tour is not None and new._tour.index == 1
        assert new._tour.title.text() == "Welcome to KPMN Tracer"
        new._tour.finish(True)
        assert new.store.load_defaults().language == "en"
        new.close()
    finally:
        set_language("de")


def test_switching_language_keeps_the_open_clip(app_qt: QApplication, tripod_clip, tmp_path: Path) -> None:
    from kpmn_tracer.gui.main_window import MainWindow
    from kpmn_tracer.session import ClipSession

    set_language("de")
    w = MainWindow()
    sess = ClipSession.open(tripod_clip[0], cache_root=tmp_path / "cache")
    sess.project.shots.clear()
    w.set_session(sess)
    w.goto(15)
    w.add_shot()
    try:
        new = w.switch_language("en")
        assert new is not None and new.session is sess and new.frame == 15 and new.dirty
        assert len(new.project.shots) == 1 and new._undo
        assert new.shot_panel.list.item(0).text().startswith("Shot 1")
        new.undo()
        assert not new.project.shots
    finally:
        set_language("de")
        new.dirty = False
        new.session = None
        new.close()
        sess.close()
        Path(str(tripod_clip[0]) + ".kpmntrace.json").unlink(missing_ok=True)


def studio_en() -> dict[str, str]:
    from kpmn_tracer.scorecard import studio_path

    html = studio_path().read_text(encoding="utf-8")
    block = html[html.index("const EN = {"):html.index("const LANG_KEY")]
    return dict(re.findall(r"'([^']*)':\s*'([^']*)'", block))


def test_scorecard_studio_is_translated() -> None:
    from i18n_keys import studio_keys

    en = studio_en()
    missing = sorted(studio_keys() - set(en))
    assert not missing, missing
    for de, val in en.items():
        assert fields(de) == fields(val), de


def test_scorecard_studio_opens_in_the_ui_language(tmp_path: Path, monkeypatch) -> None:
    import webbrowser

    from kpmn_tracer import scorecard

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr(scorecard.tempfile, "gettempdir", lambda: str(tmp_path))
    set_language("en")
    try:
        assert scorecard.open_studio()
    finally:
        set_language("de")
    page = Path(opened[0].removeprefix("file:///")) if os.name == "nt" else Path(opened[0].removeprefix("file://"))
    html = page.read_text(encoding="utf-8")
    assert scorecard.studio_path().resolve().as_uri() + "#lang=en" in html
