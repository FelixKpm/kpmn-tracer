"""Scorecard Studio: files present, designs well-formed, no single brand hard-wired into the page."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from kpmn_tracer.scorecard import studio_path

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _themes() -> list[dict]:
    js = studio_path().with_name("themes.js").read_text(encoding="utf-8")
    body = js[js.index("window.SCORECARD_THEMES = ") + len("window.SCORECARD_THEMES = "):].strip().rstrip(";")
    # the file is JS, but written as JSON-compatible data apart from unquoted keys
    body = re.sub(r"([{,]\s*)([A-Za-z]\w*)\s*:", r'\1"\2":', body)
    return json.loads(body)


def test_studio_files_exist() -> None:
    p = studio_path()
    assert p.is_file() and p.with_name("themes.js").is_file()
    html = p.read_text(encoding="utf-8")
    assert '<script src="themes.js"></script>' in html


def test_builtin_designs_are_complete() -> None:
    themes = _themes()
    ids = [t["id"] for t in themes]
    assert len(ids) == len(set(ids)) >= 4
    for t in themes:
        for k in ("bgTop", "bgBottom", "header", "accent", "text", "muted"):
            assert HEX.match(t["colors"][k]), (t["id"], k)
        assert t["background"] in ("fairway", "stripes", "plain")
        assert t["logo"] is None or t["logo"].startswith("data:image/")
    # the original NightRange colours stay available as a template (without the channel logo)
    nr = next(t for t in themes if t["id"] == "nightrange")
    assert nr["handle"] == "@teeoff.kpmn" and nr["colors"]["accent"] == "#C6F432"
    assert all(t["logo"] is None for t in themes)  # no logos are shipped
    # ... and the other templates are brand-neutral
    assert all(not t["brand"] and not t["handle"] for t in themes if t["id"] != "nightrange")


def test_page_has_no_hard_wired_brand() -> None:
    html = studio_path().read_text(encoding="utf-8")
    script = html[html.index("<script>"):]
    lines = [ln for ln in script.splitlines() if "OLD_KEY = " not in ln]  # old storage key may stay
    assert "teeoff" not in "\n".join(lines)
    assert re.search(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/]{100}", html) is None  # logos belong to designs


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_studio_javascript_parses(tmp_path) -> None:
    html = studio_path().read_text(encoding="utf-8")
    main = re.findall(r"<script>(.*?)</script>", html, re.S)[-1]
    f = tmp_path / "studio.js"
    f.write_text(main, encoding="utf-8")
    for js in (f, studio_path().with_name("themes.js")):
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
