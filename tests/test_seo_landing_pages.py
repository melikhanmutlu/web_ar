"""Comparison (/vs) and format (/convert) SEO landing pages (growth F3.3)."""


def test_vs_pages_render_known_slugs(client):
    for slug, marker in (
        ("sketchfab", "Sketchfab"),
        ("meshy", "Meshy"),
        ("model-viewer", "model-viewer"),
    ):
        resp = client.get(f"/vs/{slug}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert marker in body
        assert "Where ARVision wins" in body
    assert client.get("/vs/nonsense").status_code == 404


def test_convert_pages_render_known_slugs(client):
    resp = client.get("/convert/fbx-to-glb")
    assert resp.status_code == 200
    assert "Convert FBX to GLB" in resp.get_data(as_text=True)

    ar = client.get("/convert/stl-to-ar")
    assert ar.status_code == 200
    assert "view a stl file in ar" in ar.get_data(as_text=True).lower()

    assert client.get("/convert/png-to-mp3").status_code == 404


def test_landing_pages_in_sitemap(client):
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/vs/sketchfab" in body
    assert "/vs/meshy" in body
    assert "/convert/fbx-to-glb" in body
    assert "/convert/stl-to-ar" in body
