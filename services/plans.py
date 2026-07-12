"""Plan/tier foundation for usage quotas and features (Faz 5: "Kullanım
kotaları ve plan/faturalama temeli").

PLAN_CONFIG below is the single source of truth for every tier's limits and
feature flags -- the enforcement hooks (upload guards, AI quota, API access)
and the user-facing surfaces (/pricing, profile) all read from it. Payment
processing itself is still out of scope: an admin sets User.plan directly
until a real billing provider is wired in, and that provider will only need
to write User.plan -- no new schema/migration (columns like plan_expires_at
or stripe_customer_id are deferred to that future billing phase).

Value conventions (shared with the enforcement sites):
- storage_mb / ai_monthly / max_models / max_upload_mb == None  -> no
  plan-imposed limit; fall through to the global admin default (storage/AI)
  or treat as unlimited (model count).
- ai_monthly is a per-user monthly (rolling 30-day) cap. 0 means "disabled
  entirely" (see app.py::_ai_quota_state), not unlimited. "free" leaves it
  None so it falls through to the global ai_monthly_limit setting (default 0
  -> AI generation off for free users unless an admin grants some); paid
  tiers set an explicit positive ceiling.
"""

import os

# PLANS is the public, self-serve tier list -- it drives /pricing and the admin
# set-plan validation. The "unlimited" plan below is deliberately NOT in it, so
# it never appears on the pricing page and can't be assigned to a user (nobody
# can upgrade to it); admins get it automatically (see _plan_name).
PLANS = ("free", "pro", "business")
DEFAULT_PLAN = "free"
# Internal, admin-only tier: fully authorized, no quotas. Not purchasable.
ADMIN_PLAN = "unlimited"
_UNLIMITED = 1_000_000_000

# Single source of truth. "free"'s None limits are load-bearing: they make the
# effective_* helpers fall through to the global admin-configured defaults,
# which is exactly what the existing behaviour (and tests) expect.
PLAN_CONFIG = {
    "free": {
        "display_name": "Free",
        "price": 0,
        "limits": {
            "storage_mb": None,       # -> global storage_quota_mb default (1 GB)
            "ai_monthly": None,       # -> global ai_monthly_limit default (0 = off)
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
            # Keep the existing env hooks so env-based tuning isn't dropped.
            "storage_mb": int(os.getenv("PLAN_PRO_STORAGE_QUOTA_MB", 10240)),  # 10 GB
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
            "storage_mb": int(os.getenv("PLAN_BUSINESS_STORAGE_QUOTA_MB", 102400)),  # 100 GB
            "ai_monthly": int(os.getenv("PLAN_BUSINESS_AI_MONTHLY_LIMIT", 200)),
            "max_models": None,       # unlimited
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
    # Admin-only, fully authorized. Every numeric limit is effectively unlimited
    # (huge sentinel, or None where None already means unlimited) and every
    # feature is on. Kept out of PLANS so it's never shown or self-assignable.
    ADMIN_PLAN: {
        "display_name": "Unlimited",
        "price": None,
        "limits": {
            "storage_mb": _UNLIMITED,
            "ai_monthly": _UNLIMITED,
            "max_models": None,          # unlimited
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


def _plan_name(user):
    """Resolve a user's plan name, normalizing unknown/None to DEFAULT_PLAN.

    Admins are always on the internal ADMIN_PLAN (fully authorized, no quotas)
    regardless of their stored plan -- so every plan_limit/plan_allows/quota
    check that flows through here treats them as unlimited in one place."""
    if user is not None and getattr(user, "is_admin", False):
        return ADMIN_PLAN
    plan = getattr(user, "plan", None) if user is not None else None
    return plan if plan in PLAN_CONFIG else DEFAULT_PLAN


def plan_name(user):
    """Public: the plan name in effect for `user` (admins -> ADMIN_PLAN)."""
    return _plan_name(user)


def plan_limit(user, key, global_default=None):
    """Effective numeric limit for `key`. A None value in the plan means "no
    plan-imposed limit" -> return global_default (which is None for callers
    that treat None as unlimited)."""
    value = PLAN_CONFIG[_plan_name(user)]["limits"].get(key)
    if value is None:
        return global_default
    return value


def plan_allows(user, feature):
    """Whether the user's plan unlocks a boolean feature flag."""
    return bool(PLAN_CONFIG[_plan_name(user)]["features"].get(feature, False))


# Backward-compatible thin wrappers over plan_limit -- signatures and
# semantics unchanged, so the existing call sites (services/storage_quota.py,
# blueprints/upload.py, app.py::_ai_quota_state, admin.py) stay untouched.
def effective_storage_quota_mb(user, global_default_mb):
    return plan_limit(user, "storage_mb", global_default_mb)


def effective_ai_monthly_limit(user, global_default_limit):
    return plan_limit(user, "ai_monthly", global_default_limit)
