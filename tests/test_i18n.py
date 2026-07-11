"""Faz 5: TR/EN dil tutarlılığı ve i18n katmanı (services/i18n.py)."""


def test_homepage_defaults_to_english_nav_labels(client):
    body = client.get("/").get_data(as_text=True)
    assert ">home<" in body
    assert ">discover<" in body


def test_session_lang_tr_renders_turkish_nav_labels(client):
    with client.session_transaction() as sess:
        sess["lang"] = "tr"
    body = client.get("/").get_data(as_text=True)
    assert "anasayfa" in body
    assert "keşfet" in body


def test_set_language_route_persists_to_session_and_redirects_home(client):
    resp = client.get("/set-language/tr", follow_redirects=False)
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["lang"] == "tr"


def test_set_language_ignores_unsupported_language(client):
    with client.session_transaction() as sess:
        sess["lang"] = "en"
    client.get("/set-language/fr", follow_redirects=False)
    with client.session_transaction() as sess:
        assert sess["lang"] == "en"


def test_set_language_redirects_back_to_referrer(client):
    resp = client.get(
        "/set-language/tr",
        headers={"Referer": "http://localhost/discover"},
        follow_redirects=False,
    )
    assert resp.headers["Location"] == "http://localhost/discover"
