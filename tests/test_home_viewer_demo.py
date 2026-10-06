"""Homepage's isolated, live Viewer demonstration."""


def test_homepage_embeds_the_live_viewer_demo(client):
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-home-viewer-demo' in body
    # Deferred: the iframe has no src until the visitor clicks the poster.
    assert 'data-src="/demo/viewer"' in body
    assert ' src="/demo/viewer"' not in body
    assert 'data-home-viewer-load' in body and 'Try the 3D demo' in body
    assert 'tabindex="-1"' in body
    assert 'data-home-viewer-shell' in body
    assert 'browser-shot-loader' in body
    assert 'Loading Viewer' in body
    assert 'home-viewer-bring-model.png' not in body


def test_demo_viewer_is_static_read_only_and_not_indexable(client):
    response = client.get("/demo/viewer")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in body
    assert 'home-track-guide-mirror.glb' in body
    assert 'marketing-demo' in body
    assert '"openToolsOnDesktop": true' in body
    assert '"initialToolsSection": null' in body
    assert 'js/viewer/ar-slicer-layers.js' not in body
    assert 'js/viewer/save-flow.js' not in body


def test_homepage_images_are_webp_and_below_fold_ones_lazy(client):
    import re
    body = client.get("/").get_data(as_text=True)
    assert "marketing/" in body and ".png" not in body
    imgs = re.findall(r"<img [^>]*marketing/[^>]*>", body)
    assert imgs
    for tag in imgs:
        assert 'width="' in tag and 'height="' in tag, tag
        assert 'decoding="async"' in tag, tag
    # The hero visual and every capability card are below the first screen.
    assert all('loading="lazy"' in t for t in imgs if "capability-" in t or "hero-3d" in t)
    assert "srcset=" in next(t for t in imgs if "hero-3d" in t)
