"""Material presets (viewer material editor) and AI text-prompt presets."""

import os
import re

from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from glb_modifier import modify_glb
from models import AIGenerationJob, MaterialPreset, OrganizationMember, PromptPreset, db
from services.model_permissions import check_model_mutation_allowed, get_live_model
from services.org_membership import _organization_membership
from version_manager import create_version

material_presets_bp = Blueprint("material_presets", __name__)

SYSTEM_PROMPT_PRESETS = [
    {"id": "system:ecommerce", "name": "E-commerce Ready", "category": "commerce",
     "prompt_template": "{prompt}, centered product asset, clean topology, realistic PBR materials, studio-ready"},
    {"id": "system:game", "name": "Game Asset", "category": "game",
     "prompt_template": "{prompt}, optimized game-ready asset, clean UVs, efficient topology, PBR textures"},
    {"id": "system:stylized", "name": "Stylized", "category": "creative",
     "prompt_template": "{prompt}, cohesive stylized 3D design, appealing silhouette, hand-painted PBR look"},
]

SYSTEM_MATERIAL_PRESETS = [
    {"id": "system:matte", "name": "Matte Polymer", "color": "#d1d5db", "metalness": 0.0, "roughness": 0.82, "opacity": 1.0},
    {"id": "system:steel", "name": "Brushed Steel", "color": "#b8c0c8", "metalness": 0.92, "roughness": 0.28, "opacity": 1.0},
    {"id": "system:gold", "name": "Polished Gold", "color": "#d4a72c", "metalness": 1.0, "roughness": 0.18, "opacity": 1.0},
    {"id": "system:glass", "name": "Tinted Glass", "color": "#b9e6ff", "metalness": 0.0, "roughness": 0.08, "opacity": 0.32},
    {"id": "system:clay", "name": "Studio Clay", "color": "#b96f50", "metalness": 0.0, "roughness": 0.9, "opacity": 1.0},
]


def _material_payload(data):
    color = str(data.get("color", "#ffffff"))
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise ValueError("Invalid material color")
    values = {}
    for field, default in (("metalness", 0), ("roughness", 0.5), ("opacity", 1)):
        value = float(data.get(field, default))
        if not 0 <= value <= 1:
            raise ValueError(f"{field} must be between 0 and 1")
        values[field] = value
    return {"color": color, **values}


@material_presets_bp.route("/api/material-presets", methods=["GET", "POST"])
@login_required
def material_presets_api():
    if request.method == "GET":
        organization_ids = [item.organization_id for item in OrganizationMember.query.filter_by(user_id=current_user.id)]
        custom = MaterialPreset.query.filter(
            or_(MaterialPreset.user_id == current_user.id,
                   MaterialPreset.organization_id.in_(organization_ids) if organization_ids else db.false())
        ).order_by(MaterialPreset.created_at.desc()).all()
        return jsonify({"success": True, "presets": SYSTEM_MATERIAL_PRESETS + [{
            "id": preset.id, "name": preset.name, "color": preset.color,
            "metalness": preset.metalness, "roughness": preset.roughness,
            "opacity": preset.opacity, "organization_id": preset.organization_id,
            "custom": True,
        } for preset in custom]})
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:120]
    if not name:
        return jsonify({"success": False, "error": "Preset name is required"}), 400
    organization_id = data.get("organization_id")
    if organization_id is not None and not _organization_membership(
        int(organization_id), {"owner", "admin", "editor"}
    ):
        return jsonify({"success": False, "error": "Organization editor role required"}), 403
    try:
        values = _material_payload(data)
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    preset = MaterialPreset(
        user_id=current_user.id,
        organization_id=int(organization_id) if organization_id is not None else None,
        name=name, **values,
    )
    db.session.add(preset); db.session.commit()
    return jsonify({"success": True, "id": preset.id}), 201


@material_presets_bp.route("/api/material-presets/<int:preset_id>", methods=["DELETE"])
@login_required
def delete_material_preset(preset_id):
    preset = MaterialPreset.query.filter_by(id=preset_id, user_id=current_user.id).first_or_404()
    db.session.delete(preset); db.session.commit()
    return jsonify({"success": True})


def _resolve_material_preset(preset_id):
    if isinstance(preset_id, str) and preset_id.startswith("system:"):
        return next((item for item in SYSTEM_MATERIAL_PRESETS if item["id"] == preset_id), None)
    try:
        preset = db.session.get(MaterialPreset, int(preset_id))
    except (TypeError, ValueError):
        return None
    if not preset:
        return None
    if current_user.is_authenticated and preset.user_id == current_user.id:
        pass
    elif not (current_user.is_authenticated and preset.organization_id and
              _organization_membership(preset.organization_id)):
        return None
    return {"id": preset.id, "name": preset.name, "color": preset.color,
            "metalness": preset.metalness, "roughness": preset.roughness,
            "opacity": preset.opacity}


@material_presets_bp.route("/api/models/<model_id>/material-preset", methods=["POST"])
def apply_model_material_preset(model_id):
    import app as app_module

    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    preset = _resolve_material_preset(data.get("preset_id"))
    if not preset:
        return jsonify({"success": False, "error": "Material preset not found"}), 404
    model = get_live_model(model_id)
    # glb_path resolves the live converted file; model.filename is a stale
    # absolute path once the storage root moves between deploys.
    source = model.glb_path
    temp_output = source + ".material.tmp.glb"
    modifications = {"material": {
        "color": preset["color"], "metalness": preset["metalness"],
        "roughness": preset["roughness"], "opacity": preset["opacity"],
        "tint_textures": bool(data.get("tint_textures", False)),
    }}
    if not modify_glb(source, temp_output, modifications):
        return jsonify({"success": False, "error": "Failed to apply material"}), 500
    os.replace(temp_output, source)
    create_version(
        model_id=model_id, operation_type="material",
        operation_details={"preset_id": preset["id"], **modifications},
        comment=f"Applied material preset: {preset['name']}",
    )
    model.validation_report = app_module.asset_quality.inspect(source)
    db.session.commit()
    return jsonify({"success": True, "preset": preset, "viewer_url": url_for("viewer.view_model", model_id=model_id)})


@material_presets_bp.route("/api/ai/presets", methods=["GET", "POST"])
@login_required
def ai_prompt_presets():
    if request.method == "GET":
        custom = PromptPreset.query.filter_by(user_id=current_user.id).order_by(PromptPreset.created_at.desc()).all()
        return jsonify({"success": True, "presets": SYSTEM_PROMPT_PRESETS + [{
            "id": preset.id, "name": preset.name, "category": preset.category,
            "prompt_template": preset.prompt_template, "custom": True,
        } for preset in custom]})
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:120]
    template = str(data.get("prompt_template", "")).strip()[:2000]
    if not name or not template or "{prompt}" not in template:
        return jsonify({"success": False, "error": "Name and a template containing {prompt} are required"}), 400
    preset = PromptPreset(
        user_id=current_user.id, name=name, prompt_template=template,
        category=str(data.get("category", "custom"))[:60],
    )
    db.session.add(preset)
    db.session.commit()
    return jsonify({"success": True, "id": preset.id}), 201


@material_presets_bp.route("/api/ai/presets/<int:preset_id>", methods=["PATCH", "DELETE"])
@login_required
def ai_prompt_preset(preset_id):
    preset = PromptPreset.query.filter_by(id=preset_id, user_id=current_user.id).first_or_404()
    if request.method == "DELETE":
        db.session.delete(preset)
        db.session.commit()
        return jsonify({"success": True})
    data = request.get_json(silent=True) or {}
    if "name" in data:
        preset.name = str(data["name"]).strip()[:120] or preset.name
    if "prompt_template" in data:
        template = str(data["prompt_template"]).strip()[:2000]
        if "{prompt}" not in template:
            return jsonify({"success": False, "error": "Template must contain {prompt}"}), 400
        preset.prompt_template = template
    if "category" in data:
        preset.category = str(data["category"])[:60]
    db.session.commit()
    return jsonify({"success": True})


@material_presets_bp.route("/api/ai/generations", methods=["GET"])
@login_required
def ai_generation_history():
    limit = min(100, max(1, request.args.get("limit", 50, type=int)))
    jobs = AIGenerationJob.query.filter_by(user_id=current_user.id).order_by(
        AIGenerationJob.created_at.desc()
    ).limit(limit).all()
    return jsonify({"success": True, "generations": [job.to_dict() for job in jobs]})


def _resolve_prompt_preset(preset_id, prompt):
    if not preset_id:
        return prompt, None
    if isinstance(preset_id, str) and preset_id.startswith("system:"):
        preset = next((item for item in SYSTEM_PROMPT_PRESETS if item["id"] == preset_id), None)
        if not preset:
            raise ValueError("Preset not found")
        return preset["prompt_template"].replace("{prompt}", prompt), None
    preset = PromptPreset.query.filter_by(id=int(preset_id), user_id=current_user.id).first()
    if not preset:
        raise ValueError("Preset not found")
    return preset.prompt_template.replace("{prompt}", prompt), preset.id
