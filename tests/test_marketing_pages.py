"""Segment landing pages, /security, /contact-sales and the admin lead list
(growth F2.1 / F2.2 / F2.3)."""

from models import SalesLead, User, db


def _admin(client, username="lead_admin"):
    user = User(username=username, email=f"{username}@test.com", is_admin=True)
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": username, "password": "testpassword123"})
    return user


def test_segment_pages_render_and_known_slugs_only(client):
    for slug, marker in (
        ("ecommerce", "e-commerce"),
        ("architecture", "architecture"),
        ("agencies", "agencies"),
    ):
        resp = client.get(f"/for/{slug}")
        assert resp.status_code == 200
        assert marker in resp.get_data(as_text=True).lower()
    assert client.get("/for/nonsense").status_code == 404


def test_security_page_renders(client):
    resp = client.get("/security")
    assert resp.status_code == 200
    assert "Security" in resp.get_data(as_text=True)


def test_segment_and_static_pages_are_in_sitemap(client):
    body = client.get("/sitemap.xml").get_data(as_text=True)
    assert "/for/ecommerce" in body
    assert "/security" in body
    assert "/contact-sales" in body


def test_contact_sales_form_creates_lead(client):
    resp = client.post("/contact-sales", data={
        "name": "Dana", "email": "dana@studio.com", "company": "Studio Co",
        "message": "We sell furniture and want AR.", "reason": "ecommerce",
    }, follow_redirects=True)
    assert resp.status_code == 200
    lead = SalesLead.query.filter_by(email="dana@studio.com").one()
    assert lead.company == "Studio Co"
    assert lead.source == "ecommerce"
    assert lead.status == "new"


def test_contact_sales_rejects_bad_email(client):
    client.post("/contact-sales", data={"email": "not-an-email", "reason": "general"})
    assert SalesLead.query.count() == 0


def test_contact_sales_honeypot_silently_drops_bots(client):
    client.post("/contact-sales", data={
        "email": "bot@spam.com", "website": "http://spam.example", "reason": "general",
    })
    assert SalesLead.query.count() == 0


def test_admin_can_list_and_update_lead_status(client):
    _admin(client)
    db.session.add(SalesLead(email="prospect@corp.com", company="Corp", source="agencies"))
    db.session.commit()
    lead = SalesLead.query.filter_by(email="prospect@corp.com").one()

    listing = client.get("/admin/leads")
    assert listing.status_code == 200
    assert "prospect@corp.com" in listing.get_data(as_text=True)

    client.post(f"/admin/leads/{lead.id}/status", data={"status": "contacted"})
    assert db.session.get(SalesLead, lead.id).status == "contacted"
    # Unknown status is rejected.
    client.post(f"/admin/leads/{lead.id}/status", data={"status": "bogus"})
    assert db.session.get(SalesLead, lead.id).status == "contacted"


def test_leads_page_is_admin_only(client):
    user = User(username="lead_plain", email="lead_plain@test.com")
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "lead_plain", "password": "testpassword123"})
    assert client.get("/admin/leads").status_code == 404
