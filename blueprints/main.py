"""Site root / marketing pages / studio."""

from datetime import datetime
from types import SimpleNamespace

import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from config import WORKER_POLL_INTERVAL

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

main_bp = Blueprint("main", __name__)

# Segment landing pages (F2.1): one template, per-segment copy. Slugs are the
# URL (/for/<slug>) and feed the sitemap (SEGMENT_SLUGS below).
SEGMENT_PAGES = {
    "ecommerce": {
        "eyebrow": "For e-commerce",
        "headline": "Let shoppers place your product in their room",
        "subhead": "Turn any 3D file into an AR-ready link and an embeddable viewer "
                   "for your product pages — no app, no code, works on iPhone and Android.",
        "pains": [
            "High return rates because customers can't judge size or fit online.",
            "\"View in your space\" needs USDZ, GLB, hosting and a viewer you don't want to build.",
            "Marketplace product photos don't convey scale or material.",
        ],
        "benefits": [
            ("In-page AR viewer", "Drop a copy-paste embed on any product page — Shopify, WooCommerce or custom."),
            ("iOS + Android AR", "Quick Look on iPhone, Scene Viewer on Android, generated automatically."),
            ("QR for print & store", "Put a code on packaging or a shelf; customers open AR instantly."),
            ("Analytics", "See views, unique visitors and AR opens per product."),
        ],
        "cta_reason": "ecommerce",
    },
    "architecture": {
        "eyebrow": "For architecture & interior design",
        "headline": "Walk clients through the design before it's built",
        "subhead": "Share models as private, versioned AR links your clients open on their "
                   "phone — with annotations, review rounds and your own branding.",
        "pains": [
            "Clients struggle to read plans and renders; sign-off drags.",
            "Revision rounds get lost across email attachments.",
            "You want client-facing links under your studio's brand, not a generic tool's.",
        ],
        "benefits": [
            ("Private, versioned links", "Every revision is a version; compare and restore any of them."),
            ("Annotations & hotspots", "Pin notes to exact points for structured review rounds."),
            ("White-label", "Custom domain and your branding on client-facing galleries."),
            ("Organizations & roles", "Owner/admin/editor/viewer so the whole studio works safely."),
        ],
        "cta_reason": "architecture",
    },
    "agencies": {
        "eyebrow": "For agencies & 3D studios",
        "headline": "The delivery layer for every 3D asset you produce",
        "subhead": "Convert, host, brand and hand off client 3D/AR under your own domain — "
                   "and automate it all through the API.",
        "pains": [
            "You rebuild the same hosting/AR delivery for every client project.",
            "Clients want a branded experience, not a link to someone else's product.",
            "Manual conversion and USDZ export eats billable hours.",
        ],
        "benefits": [
            ("White-label + custom domains", "Every client gallery on your brand and your domain."),
            ("Full REST API + webhooks", "Automate ingestion, conversion and publishing in your pipeline."),
            ("Organizations", "Separate client workspaces with per-seat roles."),
            ("Batch conversion", "Push many assets through at once instead of one by one."),
        ],
        "cta_reason": "agencies",
    },
}
SEGMENT_SLUGS = tuple(SEGMENT_PAGES)


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


@main_bp.route("/for/<segment>", methods=["GET"])
def segment_landing(segment):
    page = SEGMENT_PAGES.get(segment)
    if page is None:
        abort(404)
    return render_template("segment_landing.html", slug=segment, page=page)


@main_bp.route("/security", methods=["GET"])
def security():
    return render_template("security.html")


@main_bp.route("/contact-sales", methods=["GET", "POST"])
def contact_sales():
    """B2B enquiry form. GET renders it (with an optional ?reason= tag from a
    segment/pricing CTA); POST validates, records a SalesLead and pings the
    admins. A hidden honeypot field kills the simplest bots."""
    from site_settings import get_setting

    reason = (request.values.get("reason") or "general")[:40]
    calcom_url = get_setting("calcom_url")

    if request.method == "POST":
        # Bots fill every field, including the hidden one; humans leave it blank.
        if (request.form.get("website") or "").strip():
            flash("Thanks — we'll be in touch.", "success")
            return redirect(url_for("main.contact_sales"))

        email = (request.form.get("email") or "").strip()[:255]
        if not _EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "error")
            return render_template("contact_sales.html", reason=reason,
                                   calcom_url=calcom_url, form=request.form)

        from models import SalesLead, db
        lead = SalesLead(
            name=(request.form.get("name") or "").strip()[:120] or None,
            email=email,
            company=(request.form.get("company") or "").strip()[:160] or None,
            message=(request.form.get("message") or "").strip()[:4000] or None,
            source=reason,
            user_id=current_user.id if current_user.is_authenticated else None,
        )
        db.session.add(lead)
        db.session.commit()
        _notify_admins_of_lead(lead)
        flash("Thanks — we'll be in touch shortly.", "success")
        return redirect(url_for("main.contact_sales"))

    return render_template("contact_sales.html", reason=reason,
                           calcom_url=calcom_url, form={})


def _notify_admins_of_lead(lead):
    """Best-effort admin notification for a new sales lead (never raises)."""
    try:
        from models import User
        from services import send_email
        admins = User.query.filter_by(is_admin=True).all()
        body = (
            f"New sales lead ({lead.source}):\n\n"
            f"Name: {lead.name or '—'}\n"
            f"Email: {lead.email}\n"
            f"Company: {lead.company or '—'}\n\n"
            f"{lead.message or '(no message)'}"
        )
        for admin in admins:
            if admin.email:
                send_email(admin.email, f"New sales lead: {lead.email}", body)
    except Exception:
        pass


@main_bp.route("/workflow", methods=["GET"])
def workflow():
    return render_template("workflow.html")


@main_bp.route("/developers", methods=["GET"])
def developers():
    """Public API/integration documentation (sidebar + content)."""
    from config import SITE_URL
    return render_template("developers.html", site_url=SITE_URL)


@main_bp.route("/settings/developer", methods=["GET"])
def developer_settings():
    """Self-serve panel to create/revoke API tokens and manage webhooks."""
    from flask import redirect, url_for
    from services.plans import plan_allows
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=url_for("main.developer_settings")))
    return render_template(
        "developer_settings.html",
        api_enabled=plan_allows(current_user, "api_access"),
        webhooks_enabled=plan_allows(current_user, "webhooks"),
    )


@main_bp.route("/pricing", methods=["GET"])
def pricing():
    from services.plans import public_plan_slugs, plan_name, all_plan_configs

    from services.credits import CREDIT_PACKS

    # Admins resolve to the internal "unlimited" plan (not public), so it
    # highlights nothing on the tier grid -- the template shows a note instead.
    current_plan = plan_name(current_user) if current_user.is_authenticated else None

    return render_template(
        "pricing.html",
        plans=public_plan_slugs(),
        plan_config=all_plan_configs(),
        credit_packs=CREDIT_PACKS,
        current_plan=current_plan,
    )
