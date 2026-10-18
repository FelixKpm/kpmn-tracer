"""Shortcut names in UI texts: written as on Windows ("Strg+E"), shown natively on macOS ("⌘E").

Qt maps Ctrl to the Command key on macOS, so the shortcuts themselves need no change.
"""

from __future__ import annotations

import sys

IS_MAC = sys.platform == "darwin"


def native(text: str) -> str:
    if not IS_MAC:
        return text
    return text.replace("Strg+Umschalt+", "⇧⌘").replace("Strg+", "⌘").replace("Umschalt+", "⇧")
