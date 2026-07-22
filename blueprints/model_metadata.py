"""Model metadata (name/description), sharing visibility, viewer settings,
and e-commerce integration snippet generation."""

import re

from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required

from models import User, UserModel, db
from services.model_permissions import (
    check_model_mutation_allowed,
    check_model_view_allowed,
    get_live_model,
)
from services.plans import plan_allows
from services.viewer_settings import resolved_viewer_settings

model_metadata_bp = Blueprint("model_metadata", __name__)


@model_metadata_bp.route("/api/models/<model_id>/metadata", methods=["PATCH"])
@login_required
def update_model_metadata(model_id):
    model = UserModel.query.get_or_404(model_id)
    if model.user_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    if "display_name" in data:
        model.display_name = str(data["display_name"])[:255] or None
    if "description" in data:
        model.description = str(data["description"])[:2000] or None
    if "tags" in data:
        raw_tags = data["tags"]
        if not isinstance(raw_tags, list):
            return jsonify({"error": "tags must be a list of strings"}), 400
        cleaned = []
        for tag in raw_tags:
            tag = re.sub(r"[^a-z0-9 -]", "", str(tag).strip().lower())[:30]
            if tag and tag not in cleaned:
                cleaned.append(tag)
        model.tags = ",".join(cleaned[:10]) or None
    db.session.commit()
    return jsonify({"ok": True, "tags": (model.tags or "").split(",") if model.tags else []})


@model_metadata_bp.route("/api/models/<model_id>/sharing", methods=["PATCH"])
@login_required
def update_model_sharing(model_id):
    model = UserModel.query.get_or_404(model_id)
    if model.user_id != current_user.id:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    visibility = data.get("visibility", model.visibility)
    if visibility not in {"private", "unlisted", "public"}:
        return jsonify({"success": False, "error": "Invalid visibility"}), 400
    domains = data.get("embed_allowed_domains")
    if domains is not None:
        if not isinstance(domains, list) or len(domains) > 50:
            return jsonify({"success": False, "error": "Domains must be a list"}), 400
        cleaned = []
        for domain in domains:
            domain = str(domain).strip().lower()
            if domain and re.fullmatch(r"(?:[a-z0-9-]+\.)*[a-z0-9-]+", domain):
                cleaned.append(domain)
            elif domain:
                return jsonify({"success": False, "error": f"Invalid domain: {domain}"}), 400
        model.embed_allowed_domains = ",".join(sorted(set(cleaned))) or None
    model.visibility = visibility
    db.session.commit()
    return jsonify({"success": True, "visibility": model.visibility})


@model_metadata_bp.route("/api/models/<model_id>/viewer-settings", methods=["GET", "PATCH"])
def model_viewer_settings(model_id):
    model = get_live_model(model_id)
    if not model:
        return jsonify({"success": False, "error": "Model not found"}), 404
    if request.method == "GET":
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        return jsonify({"success": True, "settings": resolved_viewer_settings(model)})
    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    # Read-modify-write on a JSON column: two PATCHes issued close together
    # from the same session (e.g. the View tab's AR-placement select and a
    # Transform-preset save's camera-orbit patch) would otherwise each read
    # `current` before either commits, and the second commit silently drops
    # whatever field the first one had just written. with_for_update() locks
    # the row for the rest of this transaction so the second request's read
    # blocks until the first commits and sees its write.
    model = UserModel.query.filter_by(id=model_id).with_for_update().first()
    current = resolved_viewer_settings(model)
    if "environment" in data:
        if data["environment"] not in {"neutral", "legacy"}:
            return jsonify({"success": False, "error": "Invalid environment preset"}), 400
        current["environment"] = data["environment"]
    if "ar_placement" in data:
        # Only the two values model-viewer actually implements ("ceiling"
        # was accepted before but the engine silently treated it as floor).
        if data["ar_placement"] not in {"floor", "wall"}:
            return jsonify({"success": False, "error": "Invalid ar_placement"}), 400
        current["ar_placement"] = data["ar_placement"]
    for field, minimum, maximum in (
        ("exposure", 0.1, 3.0), ("shadow_intensity", 0.0, 3.0),
        ("shadow_softness", 0.0, 1.0),
        ("auto_rotate_delay", 0, 30000),
    ):
        if field in data:
            try:
                value = float(data[field])
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": f"Invalid {field}"}), 400
            if not minimum <= value <= maximum:
                return jsonify({"success": False, "error": f"{field} outside allowed range"}), 400
            current[field] = int(value) if field == "auto_rotate_delay" else value
    for field in ("auto_rotate", "show_dimensions", "show_ar"):
        if field in data:
            if not isinstance(data[field], bool):
                return jsonify({"success": False, "error": f"{field} must be a boolean"}), 400
            current[field] = data[field]
    if "background_color" in data:
        color = str(data["background_color"])
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            return jsonify({"success": False, "error": "Invalid background color"}), 400
        current["background_color"] = color
    for field in ("camera_orbit", "field_of_view"):
        if field in data:
            value = str(data[field]).strip()[:80]
            if not value:
                return jsonify({"success": False, "error": f"Invalid {field}"}), 400
            current[field] = value
    if "branding" in data:
        branding = data["branding"]
        if not isinstance(branding, dict):
            return jsonify({"success": False, "error": "Invalid branding"}), 400
        # White-label branding (custom name/logo/color, hiding "Powered by")
        # is a paid feature gated on the model owner's plan. Anonymous models
        # (no owner) can't customize branding.
        owner = db.session.get(User, model.user_id) if model.user_id else None
        if not (owner and plan_allows(owner, "white_label")):
            return jsonify({
                "success": False,
                "error": "White-label branding requires a Business plan.",
            }), 403
        merged = dict(current["branding"])
        if "name" in branding:
            merged["name"] = str(branding["name"]).strip()[:80] or "ARVision"
        if "logo_url" in branding:
            logo = branding["logo_url"]
            if logo and not str(logo).startswith("https://"):
                return jsonify({"success": False, "error": "Logo URL must use HTTPS"}), 400
            merged["logo_url"] = str(logo)[:500] if logo else None
        if "primary_color" in branding:
            color = str(branding["primary_color"])
            if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                return jsonify({"success": False, "error": "Invalid branding color"}), 400
            merged["primary_color"] = color
        if "hide_powered_by" in branding:
            if not isinstance(branding["hide_powered_by"], bool):
                return jsonify({"success": False, "error": "hide_powered_by must be a boolean"}), 400
            merged["hide_powered_by"] = branding["hide_powered_by"]
        current["branding"] = merged
    if "section_presets" in data:
        presets = data["section_presets"]
        if not isinstance(presets, list) or len(presets) > 10:
            return jsonify({"success": False, "error": "Invalid section presets"}), 400
        cleaned = []
        for preset in presets:
            if not isinstance(preset, dict) or preset.get("axis") not in {"x", "y", "z"}:
                return jsonify({"success": False, "error": "Invalid section preset"}), 400
            try:
                section_value = float(preset.get("value", 0))
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "Invalid section preset value"}), 400
            cleaned.append({
                "name": str(preset.get("name", "Section"))[:60],
                "axis": preset["axis"],
                "value": max(-100.0, min(100.0, section_value)),
                "side": "negative" if preset.get("side") == "negative" else "positive",
            })
        current["section_presets"] = cleaned
    model.viewer_settings = current
    db.session.commit()
    return jsonify({"success": True, "settings": current})


@model_metadata_bp.route("/api/models/<model_id>/integration-snippets", methods=["GET"])
def model_integration_snippets(model_id):
    model = get_live_model(model_id)
    if not model:
        return jsonify({"success": False, "error": "Model not found"}), 404
    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard
    embed_url = url_for("viewer.embed_view", model_id=model_id, _external=True)
    iframe = f'<iframe src="{embed_url}" width="100%" height="500" frameborder="0" allow="xr-spatial-tracking; fullscreen" loading="lazy"></iframe>'
    return jsonify({
        "success": True,
        "embed_url": embed_url,
        "html": iframe,
        "shopify_liquid": '<div class="arvision-product-model">' + iframe + '</div>',
        "woocommerce_shortcode": f'[arvision_model url="{embed_url}" height="500"]',
    })
