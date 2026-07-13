"""Site root / homepage."""

from flask import Blueprint, render_template
from flask_login import current_user

from config import WORKER_POLL_INTERVAL

main_bp = Blueprint("main", __name__)


@main_bp.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@main_bp.route("/app", methods=["GET"])
def studio():
    import ai_generator
    import app as app_module

    ai_remove_lighting_supported = ai_generator.supports_remove_lighting()
    ai_quota = None
    if current_user.is_authenticated:
        exceeded, used, limit = app_module._ai_quota_state(current_user.id)
        ai_quota = {"used": used, "limit": limit, "remaining": max(0, limit - used)}
    return render_template("app.html",
                            ai_remove_lighting_supported=ai_remove_lighting_supported,
                            ai_quota=ai_quota,
                            worker_poll_interval_ms=int(WORKER_POLL_INTERVAL * 1000))


@main_bp.route("/pricing", methods=["GET"])
def pricing():
    from services.plans import PLANS, plan_name, all_plan_configs

    from services.credits import CREDIT_PACKS

    # Admins resolve to the internal "unlimited" plan (not in PLANS), so it
    # highlights nothing on the tier grid -- the template shows a note instead.
    current_plan = plan_name(current_user) if current_user.is_authenticated else None

    return render_template(
        "pricing.html",
        plans=PLANS,
        plan_config=all_plan_configs(),
        credit_packs=CREDIT_PACKS,
        current_plan=current_plan,
    )
