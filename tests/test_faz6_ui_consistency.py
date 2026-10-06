"""Faz 6 UI consistency items (UIA-25 save bar, mobile download menu, card radius tokens)."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_embed_section_hides_the_model_save_bar():
    js = _read("static/js/viewer/panel-nav.js")
    match = re.search(r"NO_MODEL_SAVE\s*=\s*\[([^\]]*)\]", js)
    assert match
    for section in ("embedContainer", "analyticsContainer", "historyContainer"):
        assert section in match.group(1)
    # the bar is restored on the menu and toggled when a section opens
    assert js.count("syncSaveBar(") >= 3
    assert "saveChangesWrapper" in _read("templates/view.html")


def test_mobile_download_popup_reuses_the_labelled_menu_items():
    js = _read("static/js/viewer/fullscreen-modal.js")
    assert ".download-fanout-btn[data-format=" in js
    assert "cloneNode(true)" in js
    assert "'Download ' + format.toUpperCase()" not in js
    html = _read("templates/view.html")
    # every format button carries a label and a description for the popup to clone
    for fmt in ("glb", "stl", "obj", "ply"):
        assert re.search(r'class="download-fanout-btn format-%s"[^>]*><strong>[^<]+</strong><span>' % fmt, html)


def test_card_radii_use_one_token_set():
    css = _read("static/css/arvision.css")
    assert re.search(r"--radius-card:\s*12px", css)
    assert re.search(r"--radius-card-sm:\s*10px", css)
    for selector in (r"\.library-model", r"\.library-storage", r"\.profile-panel",
                     r"\.pricing-compare-wrap", r"\.discover-empty", r"\.billing-plan-grid article"):
        blocks = re.findall(selector + r"\s*\{[^{}]*\}", css)
        radii = [r for block in blocks for r in re.findall(r"border-radius:\s*([^;}]+)", block)]
        assert radii and all("var(--radius-card" in r for r in radii), (selector, radii)
    assert "border-radius: 0 0 var(--radius-card) var(--radius-card)" in css
