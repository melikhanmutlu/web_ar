"""Faz 4: self-hosted frontend assets, prebuilt Tailwind, CSP."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"

REMOVED_HOSTS = ("cdn.tailwindcss.com", "unpkg.com", "www.gstatic.com")


def _text_sources():
    for path in list(TEMPLATES.rglob("*.html")) + [
        p for p in (ROOT / "static" / "js").rglob("*.js") if ".min." not in p.name
    ]:
        yield path, path.read_text(encoding="utf-8")


def test_no_runtime_cdn_references_in_our_ui():
    offenders = []
    for path, text in _text_sources():
        for host in ("cdn.tailwindcss.com", "unpkg.com"):
            if host in text:
                offenders.append(f"{path.relative_to(ROOT)} -> {host}")
    assert not offenders, offenders


def test_prebuilt_tailwind_and_vendored_assets_exist():
    for rel in (
        "static/css/tailwind-base.min.css",
        "static/css/tailwind-view.min.css",
        "static/vendor/lucide/lucide-1.17.0.min.js",
        "static/vendor/draco/draco_wasm_wrapper.js",
        "static/vendor/draco/draco_decoder.wasm",
        "static/vendor/basis/basis_transcoder.wasm",
    ):
        assert (ROOT / rel).stat().st_size > 1000, rel
    base = TEMPLATES / "base.html"
    assert "tailwind-base.min.css" in base.read_text(encoding="utf-8")
    assert "tailwind-view.min.css" in (TEMPLATES / "view.html").read_text(encoding="utf-8")


def test_every_model_viewer_page_self_hosts_draco():
    for path in TEMPLATES.glob("*.html"):
        text = path.read_text(encoding="utf-8")
        if "js/model-viewer.min.js" in text:
            assert "dracoDecoderLocation" in text, path.name
    vr = (TEMPLATES / "vr.html").read_text(encoding="utf-8")
    assert "dracoDecoderPath" in vr
    assert re.search(r"dracoDecoderLocation\s*=\s*'/static/vendor/draco/'", (ROOT / "static/js/my_models.js").read_text(encoding="utf-8"))


def test_csp_no_longer_lists_removed_cdn_hosts(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    for host in REMOVED_HOSTS:
        assert host not in policy
    assert "'wasm-unsafe-eval'" in policy
