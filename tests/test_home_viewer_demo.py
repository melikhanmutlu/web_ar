"""Homepage's isolated, live Viewer demonstration."""


def test_homepage_embeds_the_live_viewer_demo(client):
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-home-viewer-demo' in body
    assert 'src="/demo/viewer"' in body
    assert 'data-home-viewer-shell' in body
    assert 'home-viewer-bring-model.png' in body  # loading poster/fallback


def test_demo_viewer_is_static_read_only_and_not_indexable(client):
    response = client.get("/demo/viewer")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in body
    assert 'home-track-guide-mirror.glb' in body
    assert 'marketing-demo' in body
    assert 'openToolsOnDesktop: true' in body
    assert 'initialToolsSection: null' in body
    assert 'js/viewer/ar-slicer-layers.js' not in body
    assert 'js/viewer/save-flow.js' not in body
