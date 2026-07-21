"""Subscription checkout and the payment-provider callback.

Provider-agnostic: everything gateway-specific lives behind
services.payments.get_active_provider(). A successful, hash-verified callback
sets the user's plan + plan_expires_at and records a Payment; the worker's
expire_stale_plans() sweep downgrades it again when the period ends.
"""

import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from services.time_utils import datetime
from models import Payment, User, db
from services import send_email
from services.payments import get_active_provider
from services.plans import get_plan_config, plan_name, public_plan_slugs

billing_bp = Blueprint("billing", __name__)
logger = logging.getLogger(__name__)

_PERIOD_DAYS = {"monthly": 30, "yearly": 365}


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "0.0.0.0"


@billing_bp.route("/billing")
@login_required
def billing_home():
    payments = (
        Payment.query.filter_by(user_id=current_user.id)
        .order_by(Payment.created_at.desc())
        .limit(20)
        .all()
    )
    provider = get_active_provider()
    return render_template(
        "billing.html",
        plan=plan_name(current_user),
        plan_config=get_plan_config(plan_name(current_user)),
        plan_expires_at=current_user.plan_expires_at,
        public_plans={slug: get_plan_config(slug) for slug in public_plan_slugs()},
        payments=payments,
        checkout_enabled=bool(provider and provider.is_configured()),
        paid=request.args.get("paid") == "1",
        failed=request.args.get("failed") == "1",
    )


@billing_bp.route("/billing/checkout/<plan_slug>", methods=["POST"])
@login_required
def checkout(plan_slug):
    if plan_slug not in public_plan_slugs():
        flash("Unknown plan.", "error")
        return redirect(url_for("billing.billing_home"))
    cfg = get_plan_config(plan_slug)
    price = cfg.get("price") or 0
    if price <= 0:
        flash("This plan is free — no payment needed.", "error")
        return redirect(url_for("billing.billing_home"))
    provider = get_active_provider()
    if not provider or not provider.is_configured():
        flash("Online payment isn't available right now. Please contact us.", "error")
        return redirect(url_for("billing.billing_home"))

    merchant_oid = "arv" + secrets.token_hex(12)
    payment = Payment(
        user_id=current_user.id,
        plan=plan_slug,
        amount=Decimal(str(price)),
        currency=cfg.get("currency", "TRY"),
        status="pending",
        method="paytr",
        provider=provider.name,
        provider_ref=merchant_oid,
    )
    db.session.add(payment)
    db.session.commit()

    try:
        session = provider.create_checkout(
            payment, current_user,
            ok_url=url_for("billing.billing_home", paid=1, _external=True),
            fail_url=url_for("billing.billing_home", failed=1, _external=True),
            client_ip=_client_ip(),
            email=current_user.email,
            item_name=f"ARVision {cfg.get('display_name', plan_slug)} plan",
        )
    except RuntimeError as exc:
        payment.status = "failed"
        payment.note = str(exc)[:500]
        db.session.commit()
        logger.warning("Checkout failed for %s: %s", plan_slug, exc)
        flash("We couldn't start the payment. Please try again.", "error")
        return redirect(url_for("billing.billing_home"))

    return render_template(
        "billing_checkout.html",
        iframe_url=session.iframe_url,
        redirect_url=session.redirect_url,
        plan_name=cfg.get("display_name", plan_slug),
    )


@billing_bp.route("/billing/paytr/callback", methods=["POST"])
def paytr_callback():
    """PayTR server-to-server notification. Hash-verified, idempotent, and
    always answers with the literal body PayTR expects so it stops retrying.
    Registered CSRF-exempt + rate-limited in app.py (meshy_webhook pattern)."""
    provider = get_active_provider()
    if not provider:
        return "OK"
    result = provider.verify_callback(request.form)
    if not result.valid or not result.reference:
        logger.warning("Rejected payment callback (bad hash) ref=%s", result.reference)
        # Don't echo the ack for an unverified callback.
        return "PAYMENT_HASH_MISMATCH", 400

    payment = Payment.query.filter_by(provider_ref=result.reference).first()
    if payment is None:
        logger.warning("Payment callback for unknown ref=%s", result.reference)
        return provider.callback_ack()
    if payment.status == "paid":
        return provider.callback_ack()  # idempotent replay

    if result.paid:
        _apply_successful_payment(payment)
    else:
        payment.status = "failed"
        db.session.commit()
    return provider.callback_ack()


def _apply_successful_payment(payment):
    """Mark a Payment paid and grant its plan to the user for one period."""
    cfg = get_plan_config(payment.plan)
    period_days = _PERIOD_DAYS.get(cfg.get("billing_period", "monthly"), 30)
    now = datetime.utcnow()
    payment.status = "paid"
    payment.period_start = now.date()
    payment.period_end = (now + timedelta(days=period_days)).date()

    user = db.session.get(User, payment.user_id)
    if user is not None:
        user.plan = payment.plan
        # Stack onto remaining time if they're renewing early, else start now.
        base = user.plan_expires_at if (user.plan_expires_at and user.plan_expires_at > now) else now
        user.plan_expires_at = base + timedelta(days=period_days)
    db.session.commit()

    if user and user.email:
        send_email(
            user.email, "Your ARVision subscription is active",
            f"Thanks! Your {cfg.get('display_name', payment.plan)} plan is active "
            f"until {payment.period_end.isoformat()}.\n\n"
            f"Amount: {payment.amount} {payment.currency}",
        )
