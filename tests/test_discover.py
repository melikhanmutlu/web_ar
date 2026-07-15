"""Public discover/gallery page: lists public models, hides private/unlisted
ones, supports search and a most-liked sort."""
from models import ModelLike, User, UserModel, db


def _model(id_, **kwargs):
    defaults = dict(filename="m.glb", visibility="unlisted")
    defaults.update(kwargs)
    return UserModel(id=id_, **defaults)


def test_community_is_the_canonical_public_gallery_route(client):
    response = client.get("/community")

    assert response.status_code == 200
    assert "<title>Community - arvision</title>" in response.get_data(as_text=True)
    # Retain the previous public URL for existing shared links.
    assert client.get("/discover").status_code == 200


def test_discover_lists_only_public_models(client):
    db.session.add_all([
        _model("pub-1", visibility="public", display_name="Public Robot"),
        _model("unl-1", visibility="unlisted", display_name="Unlisted Thing"),
        _model("priv-1", visibility="private", display_name="Private Thing"),
        _model("deleted-pub", visibility="public", display_name="Deleted Public",
               deleted_at=db.func.now()),
    ])
    db.session.commit()

    page = client.get("/discover").get_data(as_text=True)
    assert "Public Robot" in page
    assert "Unlisted Thing" not in page
    assert "Private Thing" not in page
    assert "Deleted Public" not in page


def test_discover_search_matches_name_and_tags(client):
    db.session.add_all([
        _model("pub-a", visibility="public", display_name="Alpha Vase", tags="pottery"),
        _model("pub-b", visibility="public", display_name="Beta Chair", tags="furniture"),
    ])
    db.session.commit()

    by_name = client.get("/discover?q=Vase").get_data(as_text=True)
    assert "Alpha Vase" in by_name
    assert "Beta Chair" not in by_name

    by_tag = client.get("/discover?q=furniture").get_data(as_text=True)
    assert "Beta Chair" in by_tag
    assert "Alpha Vase" not in by_tag


def test_discover_popular_sort_orders_by_like_count(client):
    db.session.add_all([
        _model("pub-least", visibility="public", display_name="Least Liked"),
        _model("pub-most", visibility="public", display_name="Most Liked"),
    ])
    db.session.commit()
    db.session.add_all([
        ModelLike(model_id="pub-most", session_id="s1"),
        ModelLike(model_id="pub-most", session_id="s2"),
        ModelLike(model_id="pub-least", session_id="s3"),
    ])
    db.session.commit()

    page = client.get("/discover?sort=popular").get_data(as_text=True)
    assert page.index("Most Liked") < page.index("Least Liked")


def test_discover_pagination_has_more_flag(client, monkeypatch):
    import blueprints.discover as discover_module
    monkeypatch.setattr(discover_module, "PAGE_SIZE", 1)
    db.session.add_all([
        _model("pub-x", visibility="public", display_name="Model X"),
        _model("pub-y", visibility="public", display_name="Model Y"),
    ])
    db.session.commit()

    page1 = client.get("/discover")
    assert page1.status_code == 200
    body1 = page1.get_data(as_text=True)
    assert "Model X" in body1 or "Model Y" in body1
    assert "page=2" in body1

    page2 = client.get("/discover?page=2").get_data(as_text=True)
    assert "page=3" not in page2
