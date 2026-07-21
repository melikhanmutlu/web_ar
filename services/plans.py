"""Plan/tier foundation for usage quotas and features.

Plans are now stored in the DB (``Plan`` model) and fully admin-editable
(create/edit/delete/reorder + per-limit/feature toggles). ``PLAN_CONFIG`` below
is no longer the live source of truth -- it is the **seed** (first-boot values
for Free/Pro/Business/Unlimited) and the **fallback** used when there is no app
context (pure-function callers like tests/test_plans.py) or the table is empty.

The public API (``plan_allows`` / ``plan_limit`` / ``plan_name`` /
``get_plan_config`` / ``all_plan_configs`` / ``effective_*``) is unchanged, so
every enforcement site keeps working; those helpers now read the DB via
``_load_plans`` (cached per-request on ``flask.g``).

Value conventions (shared with the enforcement sites):
- storage_mb / ai_monthly / max_models / max_upload_mb / None -> no
  plan-imposed limit; fall through to the global admin default or unlimited.
- ai_monthly 0 means "disabled entirely" (see app.py::_ai_quota_state).
"""

import os
from datetime import datetime

# Seed / self-serve identity. The Plan table is seeded from these on first boot
# (seed_plans_if_empty); after that the DB is authoritative and admins can add
# more tiers. ADMIN_PLAN stays synthetic + system (never deletable/editable).
PLANS = ("free", "pro", "business")
DEFAULT_PLAN = "free"
ADMIN_PLAN = "unlimited"
_UNLIMITED = 1_000_000_000
DEFAULT_CURRENCY = os.getenv("BILLING_CURRENCY", "TRY")

# The editable field names inside a plan's "limits"/"features" dict -- shared by
# the admin Plans editor (parsing + rendering) so the field list lives once.
LIMIT_KEYS = (
    "storage_mb", "ai_monthly", "max_models", "max_upload_mb",
    "batch_size", "analytics_retention_days",
)
FEATURE_KEYS = (
    "api_access", "advanced_ai_options", "password_protected_shares",
    "organizations", "custom_domains", "white_label", "webhooks",
)

# Config keys every effective plan dict carries beyond limits/features.
_PLAN_DEFAULTS = {"currency": DEFAULT_CURRENCY, "billing_period": "monthly"}

# Seed + no-context fallback. "free"'s None limits are load-bearing: they make
# the effective_* helpers fall through to the global admin-configured defaults.
PLAN_CONFIG = {
    "free": {
        "display_name": "Free",
        "price": 0,
        "limits": {
            "storage_mb": None,
            "ai_monthly": None,
            "max_models": 10,
            "max_upload_mb": 50,
            "batch_size": 3,
            "analytics_retention_days": 7,
        },
        "features": {
            "api_access": False,
            "advanced_ai_options": False,
            "password_protected_shares": False,
            "organizations": False,
            "custom_domains": False,
            "white_label": False,
            "webhooks": False,
        },
    },
    "pro": {
        "display_name": "Pro",
        "price": 19,
        "limits": {
            "storage_mb": int(os.getenv("PLAN_PRO_STORAGE_QUOTA_MB", 10240)),
            "ai_monthly": int(os.getenv("PLAN_PRO_AI_MONTHLY_LIMIT", 20)),
            "max_models": 200,
            "max_upload_mb": 100,
            "batch_size": 10,
            "analytics_retention_days": 90,
        },
        "features": {
            "api_access": True,
            "advanced_ai_options": True,
            "password_protected_shares": True,
            "organizations": False,
            "custom_domains": False,
            "white_label": False,
            "webhooks": False,
        },
    },
    "business": {
        "display_name": "Business",
        "price": 99,
        "limits": {
            "storage_mb": int(os.getenv("PLAN_BUSINESS_STORAGE_QUOTA_MB", 102400)),
            "ai_monthly": int(os.getenv("PLAN_BUSINESS_AI_MONTHLY_LIMIT", 200)),
            "max_models": None,
            "max_upload_mb": 100,
            "batch_size": 25,
            "analytics_retention_days": 365,
        },
        "features": {
            "api_access": True,
            "advanced_ai_options": True,
            "password_protected_shares": True,
            "organizations": True,
            "custom_domains": True,
            "white_label": True,
            "webhooks": True,
        },
    },
    ADMIN_PLAN: {
        "display_name": "Unlimited",
        "price": None,
        "limits": {
            "storage_mb": _UNLIMITED,
            "ai_monthly": _UNLIMITED,
            "max_models": None,
            "max_upload_mb": _UNLIMITED,
            "batch_size": _UNLIMITED,
            "analytics_retention_days": _UNLIMITED,
        },
        "features": {
            "api_access": True,
            "advanced_ai_options": True,
            "password_protected_shares": True,
            "organizations": True,
            "custom_domains": True,
            "white_label": True,
            "webhooks": True,
        },
    },
}


def _fallback_plans():
    """{slug: full config} straight from PLAN_CONFIG (seed/no-context path)."""
    return {slug: {**_PLAN_DEFAULTS, **cfg} for slug, cfg in PLAN_CONFIG.items()}


def _load_plans():
    """Resolve the live plan set: {"configs": {slug: cfg}, "public": [...],
    "assignable": [...]}.

    Reads the DB ``Plan`` table when an app context is active, cached for the
    duration of the request on ``flask.g`` (so the many per-request plan_allows/
    plan_limit calls hit the DB once). Falls back to PLAN_CONFIG with no app
    context (pure-function tests) or if the table is empty/unavailable.
    ADMIN_PLAN is always present and never listed as public/assignable.
    """
    from flask import has_app_context, has_request_context, g

    if not has_app_context():
        fb = _fallback_plans()
        return {"configs": fb, "public": list(PLANS), "assignable": list(PLANS)}
    if has_request_context():
        cached = getattr(g, "_plans_bundle", None)
        if cached is not None:
            return cached
    try:
        from models import Plan
        rows = Plan.query.order_by(Plan.sort_order, Plan.id).all()
    except Exception:
        rows = None
    if not rows:
        fb = _fallback_plans()
        bundle = {"configs": fb, "public": list(PLANS), "assignable": list(PLANS)}
    else:
        configs, public, assignable = {}, [], []
        for row in rows:
            configs[row.slug] = {**_PLAN_DEFAULTS, **row.to_config()}
            if row.slug != ADMIN_PLAN:
                assignable.append(row.slug)
                if row.is_public:
                    public.append(row.slug)
        configs.setdefault(ADMIN_PLAN, _fallback_plans()[ADMIN_PLAN])
        bundle = {"configs": configs, "public": public, "assignable": assignable}
    if has_request_context():
        g._plans_bundle = bundle
    return bundle


def invalidate_plan_cache():
    """Drop the per-request plan cache after a write within the same request."""
    from flask import has_request_context, g
    if has_request_context():
        g._plans_bundle = None


def _plan_name(user):
    """Effective plan name for `user`. Admins -> ADMIN_PLAN. A paid plan past
    its plan_expires_at falls back to DEFAULT_PLAN (safe downgrade even before
    the worker sweep resets the stored value). Unknown plan -> DEFAULT_PLAN."""
    if user is not None and getattr(user, "is_admin", False):
        return ADMIN_PLAN
    if user is None:
        return DEFAULT_PLAN
    expires = getattr(user, "plan_expires_at", None)
    if expires is not None and expires < datetime.utcnow():
        return DEFAULT_PLAN
    plan = getattr(user, "plan", None)
    configs = _load_plans()["configs"]
    return plan if plan in configs else DEFAULT_PLAN


def plan_name(user):
    """Public: the plan name in effect for `user` (admins -> ADMIN_PLAN)."""
    return _plan_name(user)


def public_plan_slugs():
    """Ordered slugs of the plans shown on /pricing (excludes ADMIN_PLAN)."""
    return tuple(_load_plans()["public"])


def assignable_plan_slugs():
    """Slugs an admin can assign to a user (every plan except ADMIN_PLAN)."""
    return tuple(_load_plans()["assignable"])


def plan_exists(slug):
    return slug in _load_plans()["configs"]


def get_plan_config(plan):
    """Effective config for one plan, or {} for an unknown plan (matches the
    old PLAN_CONFIG.get(plan, {}) fallback some callers relied on)."""
    return _load_plans()["configs"].get(plan, {})


def all_plan_configs():
    """{slug: effective_config} for every public plan, in display order."""
    bundle = _load_plans()
    return {slug: bundle["configs"][slug] for slug in bundle["public"]}


def plan_limit(user, key, global_default=None):
    """Effective numeric limit for `key`. A None value in the plan means "no
    plan-imposed limit" -> return global_default."""
    value = get_plan_config(_plan_name(user)).get("limits", {}).get(key)
    if value is None:
        return global_default
    return value


def plan_allows(user, feature):
    """Whether the user's plan unlocks a boolean feature flag."""
    return bool(get_plan_config(_plan_name(user)).get("features", {}).get(feature, False))


def effective_storage_quota_mb(user, global_default_mb):
    return plan_limit(user, "storage_mb", global_default_mb)


def effective_ai_monthly_limit(user, global_default_limit):
    return plan_limit(user, "ai_monthly", global_default_limit)


# ---------------------------------------------------------------------------
# Admin CRUD + seeding
# ---------------------------------------------------------------------------

def seed_plans_if_empty():
    """Populate the Plan table from PLAN_CONFIG on first boot. Idempotent: does
    nothing once any plan row exists."""
    from models import Plan, db
    if Plan.query.first() is not None:
        return
    for order, slug in enumerate([*PLANS, ADMIN_PLAN]):
        cfg = PLAN_CONFIG[slug]
        db.session.add(Plan(
            slug=slug,
            display_name=cfg["display_name"],
            price=cfg["price"],
            currency=DEFAULT_CURRENCY,
            billing_period="monthly",
            is_public=(slug in PLANS),
            is_system=(slug in (DEFAULT_PLAN, ADMIN_PLAN)),
            sort_order=order,
            limits=dict(cfg["limits"]),
            features=dict(cfg["features"]),
        ))
    db.session.commit()


def save_plan(slug, *, display_name, price, currency, billing_period,
              is_public, sort_order, limits, features):
    """Create or update a plan by slug. Only LIMIT_KEYS/FEATURE_KEYS are kept
    from the given dicts. ADMIN_PLAN can't be created/renamed this way. Returns
    the Plan row."""
    from models import Plan, db
    if slug == ADMIN_PLAN:
        raise ValueError("The unlimited/admin plan is managed internally.")
    plan = Plan.query.filter_by(slug=slug).first()
    clean_limits = {key: limits[key] for key in LIMIT_KEYS if key in limits}
    clean_features = {key: bool(features[key]) for key in FEATURE_KEYS if key in features}
    if plan is None:
        plan = Plan(slug=slug, is_system=False)
        db.session.add(plan)
    plan.display_name = display_name
    plan.price = price
    plan.currency = currency or DEFAULT_CURRENCY
    plan.billing_period = billing_period if billing_period in ("monthly", "yearly") else "monthly"
    plan.is_public = bool(is_public)
    plan.sort_order = sort_order
    plan.limits = clean_limits
    plan.features = clean_features
    db.session.commit()
    invalidate_plan_cache()
    return plan


def delete_plan(slug):
    """Delete a non-system plan. Refuses system plans (free/unlimited)."""
    from models import Plan, db
    plan = Plan.query.filter_by(slug=slug).first()
    if plan is None:
        return False
    if plan.is_system:
        raise ValueError("System plans can't be deleted.")
    db.session.delete(plan)
    db.session.commit()
    invalidate_plan_cache()
    return True
