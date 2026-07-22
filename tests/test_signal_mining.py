"""B2B signal mining sweep (growth F3.6)."""

import uuid

from app import db
from models import ModelAnalyticsEvent, Organization, OrganizationMember, SalesLead, User, UserModel
from services import signal_mining


def _user(username, email=None, is_admin=False):
    user = User(username=username, email=email or f"{username}@test.com", is_admin=is_admin)
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def test_domain_cluster_creates_one_lead(client):
    for i in range(3):
        _user(f"corp{i}", email=f"corp{i}@acmecorp.com")
    _user("solo", email="solo@acmecorp.com")  # 4th too, same domain

    assert signal_mining.run_signal_mining() >= 1
    leads = SalesLead.query.filter_by(source="signal:domain_cluster").all()
    assert len(leads) == 1
    assert leads[0].company == "acmecorp.com"


def test_free_email_domains_are_excluded(client):
    for i in range(4):
        _user(f"g{i}", email=f"g{i}@gmail.com")
    signal_mining.run_signal_mining()
    assert SalesLead.query.filter_by(source="signal:domain_cluster").count() == 0


def test_below_threshold_domain_ignored(client):
    for i in range(2):  # only 2, need 3
        _user(f"sm{i}", email=f"sm{i}@smallco.com")
    signal_mining.run_signal_mining()
    assert SalesLead.query.filter_by(source="signal:domain_cluster").count() == 0


def test_org_owner_becomes_lead(client):
    owner = _user("org_owner", email="boss@studio.io")
    org = Organization(name="Studio", slug="studio-x", created_by=owner.id)
    db.session.add(org)
    db.session.commit()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    db.session.commit()

    signal_mining.run_signal_mining()
    lead = SalesLead.query.filter_by(source="signal:org_owner").one()
    assert lead.email == "boss@studio.io"
    assert lead.company == "Studio"


def test_high_ar_views_becomes_lead(client):
    user = _user("viral", email="viral@brand.co")
    model = UserModel(id=str(uuid.uuid4()), filename="m/model.glb", user_id=user.id)
    db.session.add(model)
    db.session.commit()
    for _ in range(100):
        db.session.add(ModelAnalyticsEvent(model_id=model.id, event_type="ar_launch"))
    db.session.commit()

    signal_mining.run_signal_mining()
    assert SalesLead.query.filter_by(source="signal:high_ar_views", email="viral@brand.co").count() == 1


def test_sweep_is_idempotent(client):
    for i in range(3):
        _user(f"dup{i}", email=f"dup{i}@dupco.com")
    first = signal_mining.run_signal_mining()
    second = signal_mining.run_signal_mining()
    assert first == 1
    assert second == 0  # dedupe by (email, source)
    assert SalesLead.query.filter_by(source="signal:domain_cluster").count() == 1


def test_admins_excluded_from_signals(client):
    # An admin org owner should not be surfaced as a lead.
    admin = _user("adminowner", email="a@internal.co", is_admin=True)
    org = Organization(name="Internal", slug="internal-x", created_by=admin.id)
    db.session.add(org)
    db.session.commit()
    signal_mining.run_signal_mining()
    assert SalesLead.query.count() == 0
