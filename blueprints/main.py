"""Site root / homepage."""

from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_login import current_user

from config import WORKER_POLL_INTERVAL
from services.i18n import SUPPORTED_LANGUAGES

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
                            ai_quota=ai_quota,
                            worker_poll_interval_ms=int(WORKER_POLL_INTERVAL * 1000))


@main_bp.route("/set-language/<lang>")
def set_language(lang):
    """i18n language switch (services/i18n.py) -- persists for the session
    and returns to wherever the link was clicked from."""
    if lang in SUPPORTED_LANGUAGES:
        session["lang"] = lang
    referrer = request.referrer
    if referrer and referrer.startswith(request.host_url):
        return redirect(referrer)
    return redirect(url_for("main.index"))
