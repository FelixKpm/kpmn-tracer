"""All German UI texts that go through :func:`kpmn_tracer.i18n.tr` (used by test_i18n)."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "kpmn_tracer"


def literal_keys() -> set[str]:
    """First arguments of ``tr("...")`` calls written as string literals."""
    keys = set()
    for p in ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return keys


def tuple_strings(path: str, *var_names: str) -> set[str]:
    """String constants inside module-level assignments or for-loops over literal tuples in ``path``.

    Used for texts translated through a variable (``tr(label)``): tables like TOOLS,
    ``for k, label in (("a", "Text"), ...)`` and ``self._spin(f, "Label", ...)``.
    """
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    out: set[str] = set()

    def strings(node: ast.AST) -> None:
        for n in ast.walk(node):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                out.add(n.value)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in var_names for t in node.targets):
            strings(node.value)
        elif isinstance(node, ast.For):
            it = node.iter
            if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == "enumerate":
                it = it.args[0]
            if isinstance(it, ast.Tuple):
                strings(it)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("_spin", "_check") and len(node.args) > 1):
            strings(node.args[1])
    return out


def indirect_keys() -> set[str]:
    """Texts translated through variables (tables, loops)."""
    from kpmn_tracer.project.presets import BUILTIN_STYLES

    keys = set(BUILTIN_STYLES)
    keys |= tuple_strings("gui/main_window.py", "VIDEO_FILTER", "KIND_LABELS", "TOOL_HINTS")
    keys |= tuple_strings("gui/panels.py", "TOOLS")
    keys |= tuple_strings("gui/dialogs.py", "EXPORT_LABELS")
    keys |= tuple_strings("gui/batch_window.py")
    return keys


def tour_keys() -> set[str]:
    from types import SimpleNamespace

    from kpmn_tracer.gui.tour import main_window_steps

    steps = main_window_steps(SimpleNamespace(shot_panel=None))
    return {s for st in steps if not st.choices for s in (st.title, st.text)}


def is_text(s: str) -> bool:
    """Identifier-like strings (keys, codes, symbols) are not UI texts."""
    return (len(s) > 1 and any(c.isalpha() for c in s) and not (s.isascii() and s.isidentifier() and s.islower())
            and not s.startswith("#"))


def all_keys() -> set[str]:
    return {k for k in literal_keys() | indirect_keys() | tour_keys() if is_text(k) or k in literal_keys()}


# ---------------------------------------------------------------- Scorecard Studio (studio.html)
STUDIO_NEUTRAL = {  # the same in both languages
    "Scorecard", "Studio", "Design", "Name", "Logo", "Par", "HCP", "Score", "Stableford", "Scramble", "Team",
    "Format", "Story / Reel", "Orange", "DE", "EN", "Sprache / Language", "Scorecard Studio",
}


def studio_static_texts(html: str) -> set[str]:
    """Text nodes, placeholders and aria-labels of the page markup (outside scripts and styles)."""
    from html.parser import HTMLParser

    out: set[str] = set()

    class P(HTMLParser):
        skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self.skip += 1
            for k, v in attrs:
                if k in ("placeholder", "aria-label") and v:
                    out.add(v.strip())

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip and data.strip():
                out.add(data.strip())

    P().feed(html)
    return {s for s in out if any(c.isalpha() for c in s)}


def studio_keys() -> set[str]:
    import re

    from kpmn_tracer.scorecard import studio_path

    html = studio_path().read_text(encoding="utf-8")
    script = re.findall(r"<script>(.*?)</script>", html, re.S)[-1]
    keys = set(re.findall(r"\bt\('([^']*)'", script))
    keys |= studio_static_texts(html) - STUDIO_NEUTRAL
    themes = studio_path().with_name("themes.js").read_text(encoding="utf-8")
    keys |= {n for n in re.findall(r'name: "([^"]*)"', themes) if "teeoff" not in n}
    return keys
