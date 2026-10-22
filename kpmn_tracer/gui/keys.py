"""Shortcut names in UI texts: written as on Windows ("Strg+E", "Ctrl+E"), shown natively on macOS ("⌘E").

Qt maps Ctrl to the Command key on macOS, so the shortcuts themselves need no change.
"""

from __future__ import annotations

import sys

IS_MAC = sys.platform == "darwin"


def native(text: str) -> str:
    if not IS_MAC:
        return text
    for win, mac in (("Strg+Umschalt+", "⇧⌘"), ("Ctrl+Shift+", "⇧⌘"), ("Strg+", "⌘"), ("Ctrl+", "⌘"),
                     ("Umschalt+", "⇧"), ("Shift+", "⇧")):
        text = text.replace(win, mac)
    return text
