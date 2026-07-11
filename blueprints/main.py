"""Site root / homepage."""

from flask import Blueprint, render_template
from flask_login import current_user

main_bp = Blueprint("main", __name__)


@main_bp.route("/", methods=["GET"])
def index():
    import ai_generator
    import app as app_module

    ai_remove_lighting_supported = ai_generator.supports_remove_lighting()
    ai_quota = None
    if current_user.is_authenticated:
        exceeded, used, limit = app_module._ai_quota_state(current_user.id)
        ai_quota = {"used": used, "limit": limit, "remaining": max(0, limit - used)}
    return render_template("index.html",
                            ai_remove_lighting_supported=ai_remove_lighting_supported,
                            ai_quota=ai_quota)
