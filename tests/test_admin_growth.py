"""Growth dashboard (/admin/growth) and services/growth_metrics.py."""

import uuid
from datetime import timedelta
from decimal import Decimal

from app import db
from models import Payment, User, UserModel
from services.growth_metrics import collect_growth_metrics
from services.time_utils import datetime


def _user(username, plan="free", is_admin=False, expires_in_days=None):
    user = User(username=username, email=f"{username}@test.com", plan=plan, is_admin=is_admin)
    user.set_password("testpassword123")
    if expires_in_days is not None:
        user.plan_expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    db.session.add(user)
    db.session.commit()
    return user


def _model(user, share_count=0, visibility="unlisted"):
    model = UserModel(
        id=str(uuid.uuid4()), filename="m/model.glb", user_id=user.id,
        share_count=share_count, visibility=visibility,
    )
    db.session.add(model)
    db.session.commit()
    return model


def test_funnel_breakdown_and_mrr(client):
    _user("gm_idle")                                   # registered only
    uploader = _user("gm_upload")
    _model(uploader)                                   # uploaded, never shared
    payer = _user("gm_payer", plan="pro", expires_in_days=20)
    _model(payer, share_count=1)                       # shared + paid
    db.session.add(Payment(                            # a real paid subscription
        user_id=payer.id, plan="pro", kind="plan", amount=Decimal("19"),
        status="paid", period_end=datetime.utcnow().date(),
    ))
    # A user on Business via trial/comp (plan set, but NO Payment) must NOT
    # count toward MRR/subscribers.
    _user("gm_trial", plan="business", expires_in_days=10)
    _user("gm_expired", plan="pro", expires_in_days=None).plan_expires_at = (
        datetime.utcnow() - timedelta(days=1)          # lapsed -> not "paid"
    )
    _user("gm_admin", plan="free", is_admin=True)      # admins never count as paid
    db.session.commit()

    metrics = collect_growth_metrics()
    assert metrics["funnel"]["registered"] == 6
    assert metrics["funnel"]["uploaded"] == 2
    assert metrics["funnel"]["shared"] == 1
    assert metrics["funnel"]["paid"] == 1               # only the real payer
    assert metrics["plan_breakdown"] == {"pro": 1}      # trial Business excluded
    assert metrics["mrr"] == 19  # seeded Pro monthly price, trial not added


def test_renewal_rate_counts_only_ended_plan_periods(client):
    renewed = _user("gm_renewed", plan="pro", expires_in_days=25)
    lapsed = _user("gm_lapsed", plan="free")
    for user, days_ago in ((renewed, 10), (lapsed, 5)):
        db.session.add(Payment(
            user_id=user.id, plan="pro", amount=Decimal("19"), status="paid",
            period_end=(datetime.utcnow() - timedelta(days=days_ago)).date(),
        ))
    # A topup in the same window must not enter the renewal denominator.
    db.session.add(Payment(
        user_id=lapsed.id, plan="credits", kind="topup", credits=10,
        amount=Decimal("9"), status="paid",
        period_end=(datetime.utcnow() - timedelta(days=2)).date(),
    ))
    db.session.commit()

    renewal = collect_growth_metrics()["renewal"]
    assert renewal["ended"] == 2
    assert renewal["renewed"] == 1
    assert renewal["rate"] == 0.5


def test_credits_sold_counts_recent_paid_topups(client):
    buyer = _user("gm_buyer")
    db.session.add(Payment(
        user_id=buyer.id, plan="credits", kind="topup", credits=50,
        amount=Decimal("39"), status="paid",
    ))
    db.session.add(Payment(  # pending -> not counted
        user_id=buyer.id, plan="credits", kind="topup", credits=200,
        amount=Decimal("139"), status="pending",
    ))
    db.session.commit()
    assert collect_growth_metrics()["credits_sold_30d"] == 50


def test_growth_page_admin_only(client):
    _user("gm_plain")
    client.post("/login", data={"username": "gm_plain", "password": "testpassword123"})
    assert client.get("/admin/growth").status_code == 404  # hidden from non-admins
    client.post("/logout")

    _user("gm_boss", is_admin=True)
    client.post("/login", data={"username": "gm_boss", "password": "testpassword123"})
    resp = client.get("/admin/growth")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Activation funnel" in body
    assert "renewal rate (30d)" in body
