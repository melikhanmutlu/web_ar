"""Model viewer surfaces: the main AR/3D viewer, iframe embed, VR (A-Frame),
and side-by-side compare pages."""

import os

from flask import Blueprint, abort, flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user

from config import SEO_INDEX_MODEL_PAGES
from models import ModelLike, ModelSave, UserModel, db
from services.model_analytics import record_model_event
from services.model_permissions import check_model_mutation_allowed, check_model_view_allowed, get_live_model
from services.viewer_settings import resolved_viewer_settings

viewer_bp = Blueprint("viewer", __name__)


def _seo_robots_for_model_page(is_canonical=False):
    """Single source of truth for whether a model page (/view, /embed, /vr)
    is indexable. Flip config.SEO_INDEX_MODEL_PAGES to change it for every
    model's canonical /view/<id> page at once — that's the only call site
    that can ever return "index, follow". /embed/<id> and /vr/<id> are
    alternate renderings of the same content (an iframe-embed viewer and a
    VR viewer) and always stay noindex, always deferring to /view/<id> via
    their <link rel="canonical">, independent of this flag — mirrors how
    YouTube's /embed/<id> stays noindex while /watch?v=<id> is indexed, and
    avoids sending mixed index+cross-canonical signals on the same page.
    """
    if is_canonical and SEO_INDEX_MODEL_PAGES:
        return "index, follow"
    return "noindex, follow"


@viewer_bp.route("/view/<model_id>")
def view_model(model_id):
    """View a specific model."""
    import app as app_module

    app_module.logger.info(f"Accessing view_model with ID: {model_id}")

    # Check if model exists in database
    model = UserModel.query.get(model_id)
    if not model:
        flash("Model not found", "error")
        return redirect(url_for("main.index"))

    # Trashed models are not viewable until restored
    if model.deleted_at is not None:
        flash("This model is in the trash. Restore it from My Models to view it.", "error")
        return redirect(url_for("main.index"))
    denied = check_model_view_allowed(model_id)
    if denied:
        abort(denied.status)
    if request.args.get("edit_token"):
        guard = check_model_mutation_allowed(model_id)
        if guard:
            abort(403)

    # Increment view count atomically (a read-modify-write loses concurrent
    # views; match the coalesce+1 pattern used for share/download counts).
    UserModel.query.filter_by(id=model_id).update(
        {UserModel.view_count: db.func.coalesce(UserModel.view_count, 0) + 1},
        synchronize_session=False,
    )
    db.session.commit()
    record_model_event(model_id, "view")

    # Check if converted file exists. glb_path resolves from the CURRENT
    # CONVERTED_FOLDER — the absolute path stored in model.filename goes stale
    # when the storage root moves between deploys (e.g. a Railway volume is
    # attached or its mount path changes), which used to strand every old
    # model behind this redirect even though its file still existed.
    glb_path = model.glb_path
    if not glb_path or not os.path.exists(glb_path):
        app_module.logger.error(f"Converted GLB file not found at path: {glb_path}")
        flash("Converted model file not found", "error")
        return redirect(url_for("main.index"))

    # Get model dimensions - try database first, then GLB file
    model_dimensions = None

    # First, try to get from database (faster)
    if model.bounds:
        try:
            import json

            bounds_data = json.loads(model.bounds)
            if "extents" in bounds_data:
                db_extents = bounds_data["extents"]
                model_dimensions = {
                    "x": round(float(db_extents[0]), 2),
                    "y": round(float(db_extents[1]), 2),
                    "z": round(float(db_extents[2]), 2),
                    "max": round(float(bounds_data.get("max", max(db_extents))), 2),
                }
                app_module.logger.info(f"Using dimensions from database: {model_dimensions}")
        except Exception as db_e:
            app_module.logger.warning(f"Could not parse bounds from database: {db_e}")

    # If not in database, calculate from GLB file
    if not model_dimensions:
        try:
            import trimesh
            import numpy as np
            from converters.glb_optimizer import readable_glb

            # Decompress meshopt/draco first (trimesh reads compressed GLBs as
            # empty geometry, which would render dimensions as 0 x 0 x 0).
            with readable_glb(glb_path) as readable_path:
                mesh = trimesh.load(readable_path)
            app_module.logger.info(f"Loaded mesh type: {type(mesh)}")

            # Get extents based on mesh type
            if isinstance(mesh, trimesh.Scene):
                # Prefer scene.bounds which includes node transforms (AABB of entire scene)
                # This fixes FBX2glTF cases where geometry is at origin but transforms are in nodes
                bounds = mesh.bounds
                # An empty/degenerate model has bounds=None — don't 500 the viewer.
                if bounds is None:
                    app_module.logger.warning("Model has no geometry; extents default to 0")
                    extents = np.zeros(3)
                else:
                    extents = bounds[1] - bounds[0]
                    app_module.logger.info(f"Scene extents from scene.bounds (AABB): {extents}")

                # If bounds also gives zero, try dump(concatenate=True) as fallback
                if max(extents) <= 0.001:
                    try:
                        combined_mesh = mesh.dump(concatenate=True)
                        extents = combined_mesh.extents
                        app_module.logger.info(
                            f"Scene extents from dump(concatenate=True): {extents}"
                        )
                    except Exception as _e:
                        app_module.logger.info(f"dump(concatenate=True) failed: {_e}")
                        # Final fallback: stack raw vertices
                        all_vertices = []
                        for geom in mesh.geometry.values():
                            if isinstance(geom, trimesh.Trimesh):
                                all_vertices.append(geom.vertices)
                        if all_vertices:
                            combined_vertices = np.vstack(all_vertices)
                            min_bounds = combined_vertices.min(axis=0)
                            max_bounds = combined_vertices.max(axis=0)
                            extents = max_bounds - min_bounds
                            app_module.logger.info(
                                f"Scene extents from stacked vertices: {extents}"
                            )
            else:
                extents = mesh.extents
                app_module.logger.info(f"Mesh extents: {extents}")

            # Convert to cm and round to 2 decimal places (show even if zero for FBX debugging)
            model_dimensions = {
                "x": round(float(extents[0]) * 100, 2),
                "y": round(float(extents[1]) * 100, 2),
                "z": round(float(extents[2]) * 100, 2),
                "max": round(float(max(extents)) * 100, 2),
            }
            app_module.logger.info(f"Model dimensions (cm): {model_dimensions}")

            if max(extents) <= 0.001:
                app_module.logger.warning(
                    f"Warning: Extents are zero or very small: {extents} - GLB may be corrupted"
                )
        except Exception as e:
            app_module.logger.error(f"Error getting model dimensions: {str(e)}")
            import traceback

            app_module.logger.error(traceback.format_exc())

    # Parse the path to get unique_id and actual filename for URL generation
    try:
        full_path = glb_path
        app_module.logger.info(f"Model full path: {full_path}")
        converted_folder_abs = os.path.abspath(app_module.app.config["CONVERTED_FOLDER"])

        if full_path.startswith(converted_folder_abs):
            relative_path = os.path.relpath(full_path, converted_folder_abs)
            # Use os.path.normpath to handle mixed slashes if any, then split
            parts = os.path.normpath(relative_path).split(os.sep)
            if len(parts) == 2:
                model_unique_id = parts[0]
                actual_filename = parts[1]
                app_module.logger.info(
                    f"Extracted ID: {model_unique_id}, Filename: {actual_filename}"
                )
            else:
                app_module.logger.error(
                    f"Could not parse unique_id and filename from relative path: {relative_path}"
                )
                raise ValueError(f"Invalid model path structure: {relative_path}")
        else:
            app_module.logger.error(
                f"Model path {full_path} does not start with converted folder {converted_folder_abs}"
            )
            raise ValueError("Model path is not within the expected converted folder")

        # Check for USDZ file
        usdz_actual_filename = None
        usdz_path = model.usdz_path
        if usdz_path and os.path.exists(usdz_path):
            usdz_actual_filename = os.path.basename(usdz_path)
            app_module.logger.info(f"Found USDZ file: {usdz_actual_filename}")

    except Exception as e:
        import traceback as tb

        app_module.logger.error(f"Error parsing model path '{model.filename}': {e}")
        app_module.logger.error(tb.format_exc())
        flash("Error processing model path.", "error")
        return redirect(url_for("main.index"))

    # Social data
    owner_username = model.user.username if model.user else "anonymous"
    like_count = ModelLike.query.filter_by(model_id=model_id).count()
    is_liked = False
    is_saved = False
    if current_user.is_authenticated:
        is_liked = (
            ModelLike.query.filter_by(
                model_id=model_id, user_id=current_user.id
            ).first()
            is not None
        )
        is_saved = (
            ModelSave.query.filter_by(
                model_id=model_id, user_id=current_user.id
            ).first()
            is not None
        )
    else:
        from flask import session
        sid = session.get("_id") or session.sid if hasattr(session, "sid") else None
        if sid:
            is_liked = (
                ModelLike.query.filter_by(model_id=model_id, session_id=sid).first()
                is not None
            )

    # Owner's other models for gallery (up to 9, excluding current)
    owner_models = []
    if model.user_id:
        owner_query = UserModel.query.filter(
                UserModel.user_id == model.user_id,
                UserModel.id != model_id,
                UserModel.deleted_at.is_(None),
            )
        if not (current_user.is_authenticated and current_user.id == model.user_id):
            owner_query = owner_query.filter(UserModel.visibility == "public")
        owner_models = (
            owner_query
            .order_by(UserModel.upload_date.desc())
            .limit(9)
            .all()
        )

    # Derive display name
    filename_base = (model.original_filename.rsplit(".", 1)[0]
                     if model.original_filename and model.original_filename != "Unknown" else "Model")
    display_name = model.display_name or filename_base
    # Admins get full owner-parity in the viewer (same as check_model_mutation_allowed
    # / check_model_view_allowed's actor_is_admin bypass), not just the actual owner.
    is_owner = current_user.is_authenticated and (
        model.user_id == current_user.id or current_user.is_admin
    )
    # Anonymous models (user_id None) are editable by anyone by design — this
    # mirrors check_model_mutation_allowed, so edit UI is only rendered for
    # viewers whose mutations the backend would actually accept.
    can_edit = is_owner or model.user_id is None

    response = make_response(render_template(
        "view.html",
        model_id=model_id,
        model=model,
        model_unique_id=model_unique_id,
        actual_filename=actual_filename,
        usdz_filename=usdz_actual_filename,
        model_dimensions=model_dimensions,
        cumulative_scale=model.cumulative_scale or 1.0,
        owner_username=owner_username,
        like_count=like_count,
        is_liked=is_liked,
        is_saved=is_saved,
        owner_models=owner_models,
        display_name=display_name,
        is_owner=is_owner,
        viewer_settings=resolved_viewer_settings(model),
        can_edit=can_edit,
        seo_robots=_seo_robots_for_model_page(is_canonical=True),
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@viewer_bp.route("/embed/<model_id>")
def embed_view(model_id):
    """Minimal embed viewer for iframe integration (e-commerce, portfolios)."""
    import app as app_module

    model = get_live_model(model_id)
    if not model:
        return "Model not found", 404
    denied = check_model_view_allowed(model_id)
    if denied:
        return denied.error, denied.status

    allowed_domains = [d.strip().lower() for d in (model.embed_allowed_domains or "").split(",") if d.strip()]
    if allowed_domains:
        from urllib.parse import urlparse
        origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
        hostname = (urlparse(origin).hostname or "").lower()
        if not any(hostname == d or hostname.endswith("." + d) for d in allowed_domains):
            return "Embedding domain is not allowed", 403
    record_model_event(model_id, "embed_view", {"autoplay": request.args.get("autoplay", "0")})

    glb_path = model.glb_path
    if not glb_path or not os.path.exists(glb_path):
        return "Model file not found", 404

    # Parse path
    try:
        full_path = glb_path
        converted_folder_abs = os.path.abspath(app_module.app.config["CONVERTED_FOLDER"])
        relative_path = os.path.relpath(full_path, converted_folder_abs)
        parts = os.path.normpath(relative_path).split(os.sep)
        model_unique_id = parts[0]
        actual_filename = parts[1]
    except Exception:
        return "Invalid model path", 500

    # Check USDZ
    usdz_actual_filename = None
    usdz_path = model.usdz_path
    if usdz_path and os.path.exists(usdz_path):
        usdz_actual_filename = os.path.basename(usdz_path)

    # Dimensions
    model_dimensions = None
    if model.bounds:
        try:
            import json
            bounds = json.loads(model.bounds) if isinstance(model.bounds, str) else model.bounds
            extents = bounds.get("extents", [0, 0, 0])
            model_dimensions = {
                "width": round(extents[0], 2),
                "height": round(extents[1], 2),
                "depth": round(extents[2], 2),
            }
        except Exception:
            pass

    return render_template(
        "embed.html",
        model=model,
        model_unique_id=model_unique_id,
        actual_filename=actual_filename,
        usdz_filename=usdz_actual_filename,
        model_dimensions=model_dimensions,
        autoplay=request.args.get("autoplay", "0") == "1",
        ar=request.args.get("ar", "1") != "0",
        viewer_settings=resolved_viewer_settings(model),
        seo_robots=_seo_robots_for_model_page(),
    )


@viewer_bp.route("/vr/<model_id>")
def vr_view(model_id):
    """VR viewer page for a specific model using A-Frame."""
    import app as app_module

    model = get_live_model(model_id)
    if not model:
        flash("Model not found", "error")
        return redirect(url_for("main.index"))
    denied = check_model_view_allowed(model_id)
    if denied:
        abort(denied.status)

    glb_path = model.glb_path
    if not glb_path or not os.path.exists(glb_path):
        flash("Converted model file not found", "error")
        return redirect(url_for("main.index"))

    # Parse unique_id and actual_filename from the live path (same logic as view_model)
    try:
        full_path = glb_path
        converted_folder_abs = os.path.abspath(app_module.app.config["CONVERTED_FOLDER"])
        if full_path.startswith(converted_folder_abs):
            relative_path = os.path.relpath(full_path, converted_folder_abs)
            parts = os.path.normpath(relative_path).split(os.sep)
            if len(parts) == 2:
                model_unique_id = parts[0]
                actual_filename = parts[1]
            else:
                raise ValueError(f"Invalid model path structure: {relative_path}")
        else:
            raise ValueError("Model path is not within the expected converted folder")
    except Exception as e:
        app_module.logger.error(f"VR view: error parsing model path: {e}")
        flash("Error processing model path.", "error")
        return redirect(url_for("main.index"))

    filename_base = (model.original_filename.rsplit(".", 1)[0]
                     if model.original_filename and model.original_filename != "Unknown" else "Model")
    display_name = model.display_name or filename_base

    response = make_response(render_template(
        "vr.html",
        model_id=model_id,
        model_unique_id=model_unique_id,
        actual_filename=actual_filename,
        display_name=display_name,
        seo_robots=_seo_robots_for_model_page(),
    ))
    response.headers["Cache-Control"] = "no-store"
    # A-Frame needs 'unsafe-eval' (it compiles code strings at runtime); the
    # app-wide CSP only allows 'wasm-unsafe-eval', so without this override the
    # A-Frame bundle throws "Refused to evaluate a string as JavaScript",
    # AFRAME never initializes, and the VR page renders pitch black. Set a
    # VR-only CSP here (the global after_request uses setdefault, so this
    # wins). Everything the page needs is same-origin/vendored now.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self' https: blob: data:; "
        "worker-src 'self' blob:; "
        "frame-ancestors 'self'"
    )
    return response


@viewer_bp.route("/compare/<left_id>/<right_id>")
def compare_models(left_id, right_id):
    left = get_live_model(left_id)
    right = get_live_model(right_id)
    if not left or not right:
        abort(404)
    for model_id in (left_id, right_id):
        denied = check_model_view_allowed(model_id)
        if denied:
            abort(denied.status)
    return render_template(
        "compare.html", left=left, right=right,
        left_file=os.path.basename(left.filename),
        right_file=os.path.basename(right.filename),
    )
