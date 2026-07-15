"""Site root / marketing pages / studio."""

from datetime import datetime
from types import SimpleNamespace

from flask import Blueprint, render_template, url_for
from flask_login import current_user

from config import WORKER_POLL_INTERVAL

main_bp = Blueprint("main", __name__)


@main_bp.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@main_bp.route("/demo/viewer", methods=["GET"])
def demo_viewer():
    """Read-only, homepage-safe rendering of the real Viewer chrome."""
    demo_model = SimpleNamespace(
        id="homepage-demo",
        original_filename="track_guideMirror.glb",
        file_type="GLB",
        file_size=83840,
        vertices=2040,
        faces=4100,
        color="#8f85e8",
        description="",
        upload_date=datetime(2026, 7, 15),
        view_count=0,
        download_count=0,
        cumulative_scale=1.0,
    )
    viewer_settings = {
        "background_color": "#111318",
        "shadow_intensity": 1.2,
        "shadow_softness": 0.7,
        "exposure": 1.0,
        "environment": "neutral",
        "camera_orbit": "36deg 70deg auto",
        "field_of_view": "24deg",
        "auto_rotate": False,
        "auto_rotate_delay": 0,
        "ar_placement": "floor",
        "show_ar": False,
        "show_dimensions": False,
        "section_presets": [],
    }
    return render_template(
        "view.html",
        marketing_demo=True,
        model_id="homepage-demo",
        model=demo_model,
        model_unique_id=None,
        actual_filename="track_guideMirror.glb",
        usdz_filename=None,
        model_dimensions=SimpleNamespace(x=128.68, y=8.1, z=292.82, max=292.82),
        owner_username="ARVision",
        owner_models=[],
        display_name="Track guide mirror",
        like_count=0,
        is_liked=False,
        is_saved=False,
        is_owner=False,
        can_edit=False,
        initial_tools_section=None,
        viewer_settings=viewer_settings,
        viewer_model_src=url_for("static", filename="marketing/home-track-guide-mirror.glb"),
        seo_robots="noindex, nofollow",
    )


@main_bp.route("/studio", methods=["GET"])
def studio():
    import ai_generator
    import app as app_module

    ai_remove_lighting_supported = ai_generator.supports_remove_lighting()
    ai_quota = None
    if current_user.is_authenticated:
        exceeded, used, limit = app_module._ai_quota_state(current_user.id)
        ai_quota = {"used": used, "limit": limit, "remaining": max(0, limit - used)}
    return render_template("studio.html",
                            ai_remove_lighting_supported=ai_remove_lighting_supported,
                            ai_quota=ai_quota,
                            worker_poll_interval_ms=int(WORKER_POLL_INTERVAL * 1000))


@main_bp.route("/features", methods=["GET"])
def features():
    return render_template("features.html")


@main_bp.route("/workflow", methods=["GET"])
def workflow():
    return render_template("workflow.html")


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
