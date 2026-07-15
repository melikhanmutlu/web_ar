"""Homepage capability carousel markup and linked visual assets."""


def test_homepage_renders_the_capability_carousel(client):
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-cap-carousel' in body
    assert (
        body.index('create-section')
        < body.index('hero--path')
        < body.index('workflow-section')
        < body.index('capability-section')
        < body.index('outcome')
        < body.index('class="cta"')
    )
    assert body.count('<a class="capability-card') == 5
    for asset in (
        "capability-upload-convert.png",
        "capability-build-scene.png",
        "capability-review-viewer.png",
        "capability-prepare-assets.png",
        "capability-place-ar.png",
    ):
        assert asset in body
    assert 'data-cap-prev' in body
    assert 'data-cap-next' in body


def test_homepage_model_experience_tabs_have_expected_content_and_routes(client):
    response = client.get("/")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    for copy in (
        "One model. Three ways to experience it.",
        "Turn a 3D asset into an experience people can inspect, understand and place in their own space.",
        "Explore</b><small>Inspect every detail",
        "Present</b><small>Tell its story",
        "Place</b><small>See it in context",
        "Give people a model they can actually inspect.",
        "Give every object the context it deserves.",
        "Let it exist in the real world.",
    ):
        assert copy in body

    assert 'href="/demo/viewer">Open the Viewer' in body
    assert 'href="/features">Explore presentation tools' in body
    assert 'href="/studio">Open Studio' in body
