"""Faz 4: self-hosted frontend assets, prebuilt Tailwind, compression, CSP."""

import io
import json
import re
from pathlib import Path

import app as app_module
from services import upload_pipeline
import trimesh
from models import ConversionJob, UserModel, db

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
            # view.html -> js/viewer/decoders.js, studio.html -> js/studio/generate.js (checked below).
            assert "dracoDecoderLocation" in text or "js/viewer/decoders.js" in text or '"dracoDecoder"' in text, path.name
    assert "dracoDecoderLocation" in (ROOT / "static/js/viewer/decoders.js").read_text(encoding="utf-8")
    assert "dracoDecoderLocation" in (ROOT / "static/js/studio/generate.js").read_text(encoding="utf-8")
    vr = (TEMPLATES / "vr.html").read_text(encoding="utf-8")
    assert "dracoDecoderPath" in vr
    assert re.search(r"dracoDecoderLocation\s*=\s*'/static/vendor/draco/'", (ROOT / "static/js/my_models.js").read_text(encoding="utf-8"))


def test_csp_no_longer_lists_removed_cdn_hosts(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    for host in REMOVED_HOSTS:
        assert host not in policy
    assert "'wasm-unsafe-eval'" in policy


def test_text_assets_are_compressed(client):
    # Static files are streamed responses; Flask-Compress only encodes those
    # with br/zstd (no streaming gzip), so ask for br here.
    resp = client.get("/static/css/arvision.css", headers={"Accept-Encoding": "br"})
    assert resp.status_code == 200
    assert resp.headers.get("Content-Encoding") == "br"
    assert "Accept-Encoding" in resp.headers.get("Vary", "")
    resp = client.get("/login", headers={"Accept-Encoding": "gzip"})
    assert resp.headers.get("Content-Encoding") == "gzip"


def test_glb_and_event_stream_are_not_compressed(client, monkeypatch):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    source = trimesh.creation.box(extents=(0.1, 0.2, 0.3)).export(file_type="glb")
    response = client.post(
        "/upload_model",
        data={"file": (io.BytesIO(source), "box.glb"), "compression": "none"},
        content_type="multipart/form-data",
    )
    payload = response.get_json()
    job = db.session.get(ConversionJob, payload["job_id"])
    upload_pipeline.run_conversion_job(job, allow_retry=False)
    db.session.refresh(job)
    assert job.status == "completed"

    gzip_headers = {"Accept-Encoding": "gzip, br"}
    stream = client.get(
        f"/api/upload-jobs/{job.id}/stream",
        query_string={"status_token": payload["status_token"]},
        headers=gzip_headers,
    )
    assert stream.status_code == 200
    assert stream.mimetype == "text/event-stream"
    assert "Content-Encoding" not in stream.headers
    events = [l[6:] for l in stream.get_data(as_text=True).splitlines() if l.startswith("data: ")]
    assert json.loads(events[-1])["status"] == "completed"

    model = db.session.get(UserModel, payload["job_id"])
    glb = client.get(
        f"/converted_files/{model.id}/{Path(model.filename).name}", headers=gzip_headers
    )
    assert glb.status_code == 200
    assert "Content-Encoding" not in glb.headers
    app_module.shutil.rmtree(Path(model.filename).parent, ignore_errors=True)
