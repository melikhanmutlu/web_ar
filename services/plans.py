"""Plan/tier foundation for usage quotas (Faz 5: "Kullanım kotaları ve
plan/faturalama temeli"). Payment processing itself is out of scope --
this only defines per-plan limit overrides and how they combine with the
existing global admin-configured defaults (storage_quota_mb, ai_daily_limit
in site_settings.py), so a real billing provider can drive User.plan later
without another migration.
"""

import os

PLANS = ("free", "pro")
DEFAULT_PLAN = "free"

# Only plans that override the global default need an entry here -- "free"
# always falls through to the existing site-wide setting.
_STORAGE_QUOTA_MB_OVERRIDES = {
    "pro": int(os.getenv("PLAN_PRO_STORAGE_QUOTA_MB", 10240)),
}
# Unlike storage_quota_mb, ai_daily_limit's own convention treats 0 as
# "disabled entirely" (see app.py::_ai_quota_state), not unlimited -- so
# "pro" gets a large practical ceiling instead of 0.
_AI_DAILY_LIMIT_OVERRIDES = {
    "pro": int(os.getenv("PLAN_PRO_AI_DAILY_LIMIT", 1000)),
}


def effective_storage_quota_mb(user, global_default_mb):
    if user is not None and user.plan in _STORAGE_QUOTA_MB_OVERRIDES:
        return _STORAGE_QUOTA_MB_OVERRIDES[user.plan]
    return global_default_mb


def effective_ai_daily_limit(user, global_default_limit):
    if user is not None and user.plan in _AI_DAILY_LIMIT_OVERRIDES:
        return _AI_DAILY_LIMIT_OVERRIDES[user.plan]
    return global_default_limit
