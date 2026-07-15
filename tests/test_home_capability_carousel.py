"""Homepage capability carousel markup and linked visual assets."""


def test_homepage_renders_the_capability_carousel(client):
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-cap-carousel' in body
    assert body.index('workflow-section') < body.index('capability-section') < body.index('create-section')
    assert body.count('<a class="capability-card') == 5
    for asset in (
        "home-upload-3d.png",
        "ar-studio-scene.png",
        "home-viewer-workspace.png",
        "hero-3d-maker-world.png",
        "home-mobile-ar.png",
    ):
        assert asset in body
    assert 'data-cap-prev' in body
    assert 'data-cap-next' in body
