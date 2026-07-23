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
from services.credits import CREDIT_PACKS, grant_ai_credits
from services.payments import get_active_provider
from services.plans import DEFAULT_CURRENCY, get_plan_config, plan_name, public_plan_slugs

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
        credit_packs=CREDIT_PACKS,
        credit_balance=current_user.ai_credit_balance or 0,
        trial_available=(
            not getattr(current_user, "is_admin", False)
            and current_user.business_trial_used_at is None
            and plan_name(current_user) == "free"
        ),
        trial_days=TRIAL_DAYS,
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

    charge_amount = Decimal(str(price))
    charge_currency = cfg.get("currency", DEFAULT_CURRENCY)
    # Plan prices are USD-denominated, but PayTR (our Turkish gateway)
    # settles in TRY -- convert at the current rate so the amount PayTR
    # actually charges the card matches what's displayed as USD on
    # /pricing, instead of charging the raw USD number mislabeled as TRY.
    if provider.name == "paytr" and charge_currency != "TRY":
        from services.fx import usd_to_try
        charge_amount = usd_to_try(price)
        charge_currency = "TRY"

    merchant_oid = "arv" + secrets.token_hex(12)
    payment = Payment(
        user_id=current_user.id,
        plan=plan_slug,
        amount=charge_amount,
        currency=charge_currency,
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


TRIAL_PLAN = "business"
TRIAL_DAYS = 14


@billing_bp.route("/billing/trial", methods=["POST"])
@login_required
def start_trial():
    """Grant a one-time 14-day Business trial. Refused if the user already
    used it, is already on a paid plan, or is an admin. The plan lapses back
    to Free via the worker's expire_stale_plans() sweep like any paid period."""
    user = current_user
    if getattr(user, "is_admin", False):
        flash("Admin accounts already have full access.", "error")
        return redirect(url_for("billing.billing_home"))
    if user.business_trial_used_at is not None:
        flash("You've already used your free Business trial.", "error")
        return redirect(url_for("billing.billing_home"))
    if plan_name(user) != "free":
        flash("Trials are only available on the Free plan.", "error")
        return redirect(url_for("billing.billing_home"))

    now = datetime.utcnow()
    user.plan = TRIAL_PLAN
    user.plan_expires_at = now + timedelta(days=TRIAL_DAYS)
    user.business_trial_used_at = now
    db.session.commit()
    flash(f"Your {TRIAL_DAYS}-day Business trial is active. Enjoy!", "success")
    return redirect(url_for("billing.billing_home"))


@billing_bp.route("/billing/topup/<pack>", methods=["POST"])
@login_required
def topup(pack):
    """Buy a prepaid AI-credit pack through the same hosted-checkout flow as a
    plan. The verified callback grants the credits (_apply_successful_payment);
    the plan itself is never touched."""
    pack_cfg = CREDIT_PACKS.get(pack)
    if pack_cfg is None:
        flash("Unknown credit pack.", "error")
        return redirect(url_for("billing.billing_home"))
    provider = get_active_provider()
    if not provider or not provider.is_configured():
        flash("Online payment isn't available right now. Please contact us.", "error")
        return redirect(url_for("billing.billing_home"))

    charge_amount = Decimal(str(pack_cfg["price"]))
    charge_currency = DEFAULT_CURRENCY
    # Same USD -> TRY conversion as the plan checkout above: credit pack
    # prices are USD-denominated, PayTR settles in TRY.
    if provider.name == "paytr" and charge_currency != "TRY":
        from services.fx import usd_to_try
        charge_amount = usd_to_try(pack_cfg["price"])
        charge_currency = "TRY"

    merchant_oid = "arv" + secrets.token_hex(12)
    payment = Payment(
        user_id=current_user.id,
        plan="credits",
        kind="topup",
        credits=pack_cfg["credits"],
        amount=charge_amount,
        currency=charge_currency,
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
            item_name=f"ARVision {pack_cfg['credits']} AI credits",
        )
    except RuntimeError as exc:
        payment.status = "failed"
        payment.note = str(exc)[:500]
        db.session.commit()
        logger.warning("Top-up checkout failed for %s: %s", pack, exc)
        flash("We couldn't start the payment. Please try again.", "error")
        return redirect(url_for("billing.billing_home"))

    return render_template(
        "billing_checkout.html",
        iframe_url=session.iframe_url,
        redirect_url=session.redirect_url,
        plan_name=f"{pack_cfg['credits']} AI credits",
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


@billing_bp.route("/billing/lemonsqueezy/webhook", methods=["POST"])
def lemonsqueezy_webhook():
    """Lemon Squeezy webhook (signature-verified, idempotent). Registered
    CSRF-exempt + rate-limited in app.py (paytr_callback pattern).

    Event handling, designed so the first subscription payment is never
    granted twice (LS fires both order_created and
    subscription_payment_success for it):
    - order_created        -> applies the pending Payment only for one-time
                              purchases (credit top-ups).
    - subscription_payment_success -> applies the pending plan Payment on the
                              first invoice; later invoices (renewals) create
                              a fresh Payment row keyed to the LS invoice id
                              and extend the plan for another period.
    """
    from services.payments.lemonsqueezy import LemonSqueezyProvider

    provider = get_active_provider()
    if not isinstance(provider, LemonSqueezyProvider) or not provider.is_configured():
        return "NOT ACTIVE", 404
    if not provider.verify_webhook(request.get_data(), request.headers.get("X-Signature", "")):
        logger.warning("Rejected Lemon Squeezy webhook (bad signature)")
        return "BAD_SIGNATURE", 400

    event = request.get_json(silent=True) or {}
    meta = event.get("meta", {}) or {}
    event_name = meta.get("event_name")
    ref = (meta.get("custom_data") or {}).get("payment_ref")
    attributes = (event.get("data", {}) or {}).get("attributes", {}) or {}
    payment = Payment.query.filter_by(provider_ref=ref).first() if ref else None
    if payment is None:
        logger.warning("Lemon Squeezy webhook %s for unknown ref=%s", event_name, ref)
        return "OK"

    if event_name == "order_created":
        if payment.kind == "topup" and payment.status == "pending" \
                and attributes.get("status") == "paid":
            _apply_successful_payment(payment)
    elif event_name == "subscription_payment_success":
        invoice_id = str((event.get("data") or {}).get("id") or "")
        invoice_tag = f"lsinv:{invoice_id}" if invoice_id else None
        invoice_ref = f"lsinv-{invoice_id}" if invoice_id else None
        if payment.status == "pending":
            # First paid invoice: grant the first period against the checkout
            # row, stamping this invoice's id so a DUPLICATE delivery of the
            # same first invoice dedupes instead of granting a second period.
            if invoice_tag:
                payment.note = invoice_tag
            _apply_successful_payment(payment)
        elif invoice_tag and payment.note == invoice_tag:
            # Duplicate delivery of the already-applied first invoice.
            return "OK"
        elif invoice_ref:
            # A renewal invoice: fresh period, deduped on its own invoice id.
            existing = Payment.query.filter_by(provider_ref=invoice_ref).first()
            if existing is None:
                renewal = Payment(
                    user_id=payment.user_id,
                    plan=payment.plan,
                    kind="plan",
                    amount=Decimal(attributes.get("total") or 0) / 100,
                    currency=(attributes.get("currency") or payment.currency or "USD"),
                    status="pending",
                    method="lemonsqueezy",
                    provider=provider.name,
                    provider_ref=invoice_ref,
                )
                db.session.add(renewal)
                # Create + apply in ONE transaction (_apply_successful_payment
                # commits). Committing the pending row first risked a crash that
                # left it stranded — redelivery then saw the row and skipped it
                # forever, so the renewal was never granted.
                _apply_successful_payment(renewal)
            elif existing.status == "pending":
                # A prior delivery created the row but crashed before applying;
                # re-apply instead of treating its existence as "done".
                _apply_successful_payment(existing)
            # else already paid -> duplicate delivery, nothing to do.
    return "OK"


def _apply_successful_payment(payment):
    """Mark a Payment paid and grant what it bought: a credit top-up loads the
    balance, a plan purchase grants the plan for one period."""
    if payment.kind == "topup":
        payment.status = "paid"
        user = db.session.get(User, payment.user_id)
        if user is not None:
            grant_ai_credits(user, payment.credits or 0)
        db.session.commit()
        if user and user.email:
            send_email(
                user.email, "Your ARVision AI credits are ready",
                f"Thanks! {payment.credits} AI credits were added to your "
                f"account — your balance is now {user.ai_credit_balance}.\n\n"
                f"Amount: {payment.amount} {payment.currency}",
            )
        return

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

    # Best-effort e-invoice (F3.8). No-op unless a provider is configured;
    # never raises, so it can't affect the payment confirmation.
    if user is not None:
        from services.invoicing import issue_invoice
        issue_invoice(payment, user)
