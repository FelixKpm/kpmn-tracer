"""UI language: German (original texts) or English.

The German UI texts are the keys: ``tr("Clip öffnen…")`` returns the text in the
current language (English from :mod:`kpmn_tracer.i18n_en`, German unchanged), so
the code stays readable and a missing translation falls back to German.
Placeholders use ``str.format``: ``tr("{n} Schläge", n=3)``.
"""

from __future__ import annotations

LANGUAGES = {"de": "Deutsch", "en": "English"}

_lang = "de"


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else "de"


def language() -> str:
    return _lang


def system_language() -> str:
    """German for German systems, English for everything else."""
    try:
        from PySide6.QtCore import QLocale

        return "de" if QLocale.system().language() == QLocale.Language.German else "en"
    except ImportError:  # CLI without Qt
        return "de"


def tr(text: str, **kw: object) -> str:
    if _lang == "en":
        from kpmn_tracer.i18n_en import EN

        text = EN.get(text, text)
    return text.format(**kw) if kw else text
