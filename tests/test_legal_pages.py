"""Public legal pages: /privacy and /terms."""
import pytest


@pytest.mark.parametrize("path,title", [("/privacy", "Privacy Policy"), ("/terms", "Terms of Service")])
def test_legal_page_renders_with_placeholders_and_date(client, path, title):
    resp = client.get(path)
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert title in html
    assert "Last updated:" in html
    assert 'name="robots" content="index, follow"' in html
    # Default operator details are obvious bracketed placeholders.
    assert "[Legal entity name]" in html and "[Registered address]" in html
    # The "draft, needs legal review" Jinja comment must not be rendered.
    assert "DRAFT" not in html and "reviewed by a lawyer" not in html


def test_legal_details_come_from_config(client, monkeypatch):
    import config
    monkeypatch.setattr(config, "LEGAL_ENTITY_NAME", "Acme Bilisim A.S.")
    monkeypatch.setattr(config, "LEGAL_ADDRESS", "Istanbul, Turkiye")
    monkeypatch.setattr(config, "LEGAL_CONTACT_EMAIL", "legal@acme.test")
    for path in ("/privacy", "/terms"):
        html = client.get(path).get_data(as_text=True)
        assert "Acme Bilisim A.S." in html
        assert "legal@acme.test" in html
        assert "[Legal entity name]" not in html


def test_privacy_covers_required_topics(client):
    html = client.get("/privacy").get_data(as_text=True)
    for needle in ("KVKK", "GDPR", "Railway", "Meshy", "PayTR", "Lemon Squeezy",
                   "we do not receive or store your card number".lower()):
        assert needle.lower() in html.lower(), needle


def test_footer_and_register_link_to_legal_pages(client):
    for path in ("/", "/pricing"):
        html = client.get(path).get_data(as_text=True)
        assert 'href="/privacy"' in html and 'href="/terms"' in html, path
    reg = client.get("/register").get_data(as_text=True)
    assert "By creating an account you agree to our" in reg
    assert 'href="/terms"' in reg and 'href="/privacy"' in reg
