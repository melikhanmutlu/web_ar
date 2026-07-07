"""SEO surface: robots.txt, sitemap.xml, and per-page meta tags."""
import os
import shutil
import uuid

import pytest
import trimesh

import site_settings
from app import app, db
from models import UserModel


@pytest.fixture
def viewable_model(client):
    """Factory for a UserModel with a real GLB on disk at the absolute path
    view_model() checks via os.path.exists(model.filename) — must be
    absolute, mirroring how the real upload flow stores `filename`
    (output_path), unlike other tests' helpers whose relative paths never
    exercise a route that calls os.path.exists(model.filename)."""
    created = []

    def _make(**overrides):
        model_id = overrides.pop("id", None) or ("seo-" + uuid.uuid4().hex[:8])
        model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
        os.makedirs(model_dir, exist_ok=True)
        glb_path = os.path.join(model_dir, "model.glb")
        box = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
        with open(glb_path, "wb") as f:
            f.write(trimesh.Scene(box).export(file_type="glb"))
        defaults = dict(id=model_id, filename=glb_path, file_type="glb", cumulative_scale=1.0)
        defaults.update(overrides)
        model = UserModel(**defaults)
        db.session.add(model)
        db.session.commit()
        created.append(model_dir)
        return model_id

    yield _make
    for d in created:
        shutil.rmtree(d, ignore_errors=True)


def test_robots_txt_is_permissive_and_points_to_sitemap(client):
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    assert resp.mimetype == "text/plain"
    body = resp.get_data(as_text=True)
    assert "User-agent: *" in body
    assert "Allow: /" in body
    assert "Disallow: /admin/" in body
    assert "Sitemap: " in body and "/sitemap.xml" in body


def test_sitemap_xml_lists_homepage(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert resp.mimetype == "application/xml"
    body = resp.get_data(as_text=True)
    assert "<urlset" in body
    assert "<loc>" in body and "</loc>" in body


def test_robots_and_sitemap_survive_maintenance_mode(client):
    """The maintenance-mode gate must not 503 Googlebot on these two paths."""
    site_settings.set_setting("maintenance_mode", "true")
    try:
        assert client.get("/").status_code == 503  # sanity: maintenance really is on
        assert client.get("/robots.txt").status_code == 200
        assert client.get("/sitemap.xml").status_code == 200
    finally:
        site_settings.set_setting("maintenance_mode", "false")


def test_homepage_has_core_seo_tags(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert 'name="description"' in body
    assert 'name="robots" content="index, follow"' in body
    assert 'rel="canonical"' in body
    assert 'property="og:title"' in body
    assert "application/ld+json" in body


def test_view_model_has_dynamic_title_and_meta_description(client, viewable_model):
    model_id = viewable_model(display_name="Test Widget", description="A widget for testing.")
    resp = client.get(f"/view/{model_id}")
    body = resp.get_data(as_text=True)
    assert "<title>Test Widget — ARVision</title>" in body
    assert "A widget for testing." in body
    assert 'rel="canonical"' in body and f"/view/{model_id}" in body
    assert "noindex" in body  # SEO_INDEX_MODEL_PAGES defaults to False


def test_view_model_description_falls_back_when_unset(client, viewable_model):
    model_id = viewable_model(display_name="Bare Model")
    resp = client.get(f"/view/{model_id}")
    body = resp.get_data(as_text=True)
    assert "Bare Model" in body  # fallback description still mentions the model by name


def test_login_page_inherits_noindex_from_base_html(client):
    resp = client.get("/login")
    body = resp.get_data(as_text=True)
    assert 'name="robots" content="noindex, nofollow"' in body
