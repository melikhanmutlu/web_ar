"""Model editing pipeline: apply/save material+transform modifications,
mesh dimensions/bounds, and plane slicing."""

import json
import os
import shutil
import time

import trimesh
from flask import Blueprint, jsonify, request, send_from_directory

from glb_modifier import modify_glb
from models import UserModel, db
from services.model_permissions import check_model_mutation_allowed, check_model_view_allowed, get_live_model
from version_manager import create_version

model_editing_bp = Blueprint("model_editing", __name__)


def _mesh_vertex_face_counts(mesh):
    """Total vertex/face counts for either a Trimesh or a Scene (summed
    across all its geometries) -- mirrors how the upload pipeline populates
    UserModel.vertices/faces from the initial conversion. Geometries without
    faces (e.g. a POINTS-mode primitive loaded as a trimesh.PointCloud, which
    has .vertices but no .faces at all) are skipped rather than counted as
    zero, since counting them at all would still crash on `g.faces`."""
    if isinstance(mesh, trimesh.Scene):
        geoms = [g for g in mesh.geometry.values() if hasattr(g, "vertices") and hasattr(g, "faces")]
        return sum(len(g.vertices) for g in geoms), sum(len(g.faces) for g in geoms)
    if hasattr(mesh, "vertices") and hasattr(mesh, "faces"):
        return len(mesh.vertices), len(mesh.faces)
    return None, None


def _invalidate_thumbnail(app_module, model):
    """Delete the stale thumbnail and re-queue generation so the library
    card reflects the model's new geometry/color after an edit. Without
    this, generate_thumbnail_async's "already exists, skip" guard means the
    pre-edit thumbnail is shown forever. Best-effort: a failure here must
    never fail the edit that already succeeded."""
    thumbnail_path = os.path.join(os.path.dirname(model.filename), "thumbnail.png")
    try:
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
        app_module._enqueue_internal_job("thumbnail", model.id, {
            "kind": "thumbnail", "color": model.color, "user_id": model.user_id,
        })
    except Exception as e:
        app_module.logger.warning(f"[_invalidate_thumbnail] Failed to re-queue thumbnail for {model.id}: {e}")


@model_editing_bp.route("/apply_modifications", methods=["POST"])
def apply_modifications():
    """Apply material and transform modifications to GLB model"""
    import app as app_module

    try:
        data = request.json
        model_id = data.get("model_id")
        modifications = data.get("modifications")

        if not model_id or not modifications:
            return jsonify(
                {"success": False, "error": "Missing model_id or modifications"}
            ), 400

        guard = check_model_mutation_allowed(model_id)
        if guard is not None:
            return guard

        app_module.logger.info(f"[apply_modifications] Model ID: {model_id}")
        app_module.logger.info(f"[apply_modifications] Modifications: {modifications}")

        # Get original GLB path
        original_path = os.path.join(
            app_module.app.config["CONVERTED_FOLDER"], model_id, "model.glb"
        )

        if not os.path.exists(original_path):
            app_module.logger.error(f"Original GLB not found: {original_path}")
            return jsonify({"success": False, "error": "Original model not found"}), 404

        # trimesh can't decode meshopt/draco-compressed GLBs, so decompress
        # in place first (the edit rewrites geometry to uncompressed form
        # anyway) instead of hard-blocking. Keeps compressed models editable.
        from converters.glb_optimizer import decompress_glb_in_place

        if decompress_glb_in_place(original_path):
            app_module.logger.info(f"[apply_modifications] Decompressed {model_id} for editing")

        # Same as save_modifications: the user picked the color while SEEING
        # the texture in the viewer, so the downloaded file must tint the
        # texture exactly like Save does — otherwise download ≠ save ≠ preview.
        if isinstance(modifications.get("material"), dict):
            modifications["material"]["tint_textures"] = True

        # Create output filename with timestamp
        timestamp = int(time.time())
        output_filename = f"modified_{timestamp}.glb"
        output_path = os.path.join(
            app_module.app.config["CONVERTED_FOLDER"], model_id, output_filename
        )

        app_module.logger.info(f"[apply_modifications] Input: {original_path}")
        app_module.logger.info(f"[apply_modifications] Output: {output_path}")

        # Apply modifications
        success = modify_glb(original_path, output_path, modifications)

        if success:
            download_url = f"/download_modified/{model_id}/{output_filename}"
            app_module.logger.info(f"[apply_modifications] Success! Download URL: {download_url}")
            return jsonify(
                {
                    "success": True,
                    "download_url": download_url,
                    "filename": output_filename,
                }
            )
        else:
            app_module.logger.error("[apply_modifications] Modification failed")
            return jsonify({"success": False, "error": "Failed to modify GLB"}), 500

    except Exception as e:
        app_module.logger.error(f"[apply_modifications] Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@model_editing_bp.route("/download_modified/<model_id>/<filename>")
def download_modified(model_id, filename):
    """Download modified GLB file"""
    import app as app_module

    # Owner guard + reject path traversal in the filename.
    guard = check_model_mutation_allowed(model_id)
    if guard is not None:
        return guard
    if os.path.basename(filename) != filename:
        app_module.logger.warning(f"[download_modified] Unsafe filename rejected: {filename}")
        return "Not Found", 404
    try:
        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard
        directory = os.path.join(app_module.app.config["CONVERTED_FOLDER"], model_id)
        app_module.logger.info(f"[download_modified] Serving {filename} from {directory}")

        if not os.path.exists(os.path.join(directory, filename)):
            app_module.logger.error(f"File not found: {os.path.join(directory, filename)}")
            return "File not found", 404

        return send_from_directory(
            directory,
            filename,
            as_attachment=True,
            download_name=f"modified_model_{int(time.time())}.glb",
        )
    except Exception as e:
        app_module.logger.error(f"[download_modified] Error: {e}", exc_info=True)
        return str(e), 500


@model_editing_bp.route("/get_model_dimensions/<model_id>")
def get_model_dimensions(model_id):
    """Get model dimensions in meters.

    Read-only: no ownership guard. The viewer page calls this for every
    visitor, and the same dimensions are already server-rendered publicly —
    the old mutation guard just made non-owners 403 for data they can see.
    """
    import app as app_module

    try:
        model = get_live_model(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        glb_path = model.glb_path

        if not os.path.exists(glb_path):
            return jsonify({"success": False, "error": "Model not found"}), 404

        # Load model with trimesh
        mesh = trimesh.load(glb_path, force="scene")

        # Get bounding box
        bounds = mesh.bounds

        # Empty/degenerate model → report zeros instead of crashing.
        if bounds is None:
            return jsonify({"success": True, "dimensions": {
                "width": 0.0, "height": 0.0, "depth": 0.0, "max": 0.0}})

        # Calculate dimensions (in meters, assuming GLB units are meters)
        dimensions = bounds[1] - bounds[0]

        # Convert to cm for display
        dimensions_cm = {
            "width": float(dimensions[0] * 100),  # X
            "height": float(dimensions[1] * 100),  # Y
            "depth": float(dimensions[2] * 100),  # Z
            "unit": "cm",
        }

        app_module.logger.info(
            f"[get_model_dimensions] Model {model_id} dimensions: {dimensions_cm}"
        )

        # AR places the GLB at its native scale as real-world meters, so a
        # wrong-unit conversion (mm mistaken for m, etc.) looks implausibly
        # tiny or huge there. Warn (never block) when the largest dimension
        # falls outside a plausible real-world object range.
        max_dimension_m = float(max(dimensions))
        scale_warning = None
        min_m = app_module.app.config.get("AR_SCALE_WARNING_MIN_METERS", 0.02)
        max_m = app_module.app.config.get("AR_SCALE_WARNING_MAX_METERS", 20)
        if max_dimension_m > 0 and max_dimension_m < min_m:
            scale_warning = (
                f"This model's largest side is only {max_dimension_m * 100:.1f} cm — "
                "if it looks wrong in AR, the source file's units may have been "
                "misdetected during conversion."
            )
        elif max_dimension_m > max_m:
            scale_warning = (
                f"This model's largest side is {max_dimension_m:.1f} m — "
                "if it looks wrong in AR, the source file's units may have been "
                "misdetected during conversion."
            )

        return jsonify({
            "success": True,
            "dimensions": dimensions_cm,
            "scale_warning": scale_warning,
        })

    except Exception as e:
        app_module.logger.error(f"[get_model_dimensions] Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@model_editing_bp.route("/save_modifications", methods=["POST"])
def save_modifications():
    """Save modifications to original GLB model (replaces model.glb)"""
    import app as app_module

    try:
        data = request.json
        model_id = data.get("model_id")
        modifications = data.get("modifications")

        if not model_id or not modifications:
            return jsonify(
                {"success": False, "error": "Missing model_id or modifications"}
            ), 400

        app_module.logger.info(f"[save_modifications] Model ID: {model_id}")
        app_module.logger.info(f"[save_modifications] Modifications: {modifications}")

        # This is the viewer's material editor: the user picked the color while
        # SEEING the texture, so honor it as a tint. (Upload-time color keeps
        # the protective skip-on-textured behavior in glb_modifier.)
        if isinstance(modifications.get("material"), dict):
            modifications["material"]["tint_textures"] = True

        # Use current model.glb as base (which may be sliced or modified)
        # This ensures modifications are applied to the current state, not original upload
        model = UserModel.query.get(model_id)
        if not model:
            app_module.logger.error(f"Model not found for ID: {model_id}")
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        # Use current model.glb file as the base for modifications
        current_model_path = os.path.join(
            app_module.app.config["CONVERTED_FOLDER"], model_id, "model.glb"
        )

        if not os.path.exists(current_model_path):
            app_module.logger.error(f"Current model.glb not found: {current_model_path}")
            return jsonify({"success": False, "error": "Model file not found"}), 404

        # trimesh can't decode meshopt/draco-compressed GLBs -- decompress in
        # place first (the save rewrites geometry to uncompressed form anyway)
        # instead of hard-blocking, so compressed models stay editable.
        from converters.glb_optimizer import decompress_glb_in_place

        if decompress_glb_in_place(current_model_path):
            app_module.logger.info(f"[save_modifications] Decompressed {model_id} for editing")

        app_module.logger.info(
            f"[save_modifications] Using current model.glb as base: {current_model_path}"
        )

        # Create backup of current model
        backup_path = os.path.join(
            app_module.app.config["CONVERTED_FOLDER"],
            model_id,
            f"model_backup_{int(time.time())}.glb",
        )
        shutil.copy2(current_model_path, backup_path)
        app_module.logger.info(f"[save_modifications] Created backup: {backup_path}")
        app_module.cleanup_old_backups(os.path.dirname(backup_path))

        # Create temporary output path
        temp_output = os.path.join(
            app_module.app.config["CONVERTED_FOLDER"], model_id, f"temp_{int(time.time())}.glb"
        )

        app_module.logger.info(f"[save_modifications] Input: {current_model_path}")
        app_module.logger.info(f"[save_modifications] Temp output: {temp_output}")

        # Apply modifications to current model
        success = modify_glb(current_model_path, temp_output, modifications)

        if success and os.path.exists(temp_output):
            # Replace current model.glb with modified version (atomic on same volume)
            os.replace(temp_output, current_model_path)
            app_module.logger.info(
                f"[save_modifications] Successfully replaced model.glb with modified version"
            )

            # Keep iOS AR in sync: Quick Look uses the USDZ, so it must be
            # rebuilt from the freshly modified GLB.
            app_module.refresh_usdz_after_edit(model_id, current_model_path)

            # Update database dimensions after modifications
            try:
                mesh = trimesh.load(current_model_path, force="scene")
                if isinstance(mesh, trimesh.Scene):
                    bounds = mesh.bounds
                else:
                    bounds = mesh.bounds

                dimensions = bounds[1] - bounds[0]
                new_dims = {
                    "x": round(float(dimensions[0] * 100), 2),
                    "y": round(float(dimensions[1] * 100), 2),
                    "z": round(float(dimensions[2] * 100), 2),
                    "max": round(float(max(dimensions) * 100), 2),
                }

                # Update database. UserModel stores dimensions in the `bounds`
                # JSON-string column as {"extents": [x,y,z], "max": m} (cm) —
                # this is the shape view_model reads. Writing model.dimensions
                # (no such column) silently dropped the update.
                model = UserModel.query.get(model_id)
                if model:
                    model.bounds = json.dumps({
                        "extents": [new_dims["x"], new_dims["y"], new_dims["z"]],
                        "max": new_dims["max"],
                    })
                    model.file_size = os.path.getsize(current_model_path)
                    model.vertices, model.faces = _mesh_vertex_face_counts(mesh)

                    # Update cumulative scale if scale was applied
                    if (
                        "transform" in modifications
                        and "scale" in modifications["transform"]
                    ):
                        applied_scale = float(modifications["transform"]["scale"])
                        if applied_scale != 1.0:
                            current_cumulative = model.cumulative_scale or 1.0
                            model.cumulative_scale = current_cumulative * applied_scale
                            app_module.logger.info(
                                f"[save_modifications] Updated cumulative scale: {current_cumulative} * {applied_scale} = {model.cumulative_scale}"
                            )

                    db.session.commit()
                    app_module.logger.info(
                        f"[save_modifications] Updated database dimensions: {new_dims}"
                    )
                    # The library card otherwise keeps showing the pre-edit
                    # geometry/color forever (thumbnails are only ever
                    # generated once, at upload).
                    _invalidate_thumbnail(app_module, model)

            except Exception as dim_error:
                app_module.logger.error(
                    f"[save_modifications] Failed to update dimensions: {dim_error}"
                )

            # Create version entry
            try:
                operation_type = (
                    "transform" if "transform" in modifications else "material"
                )
                if "material" in modifications and "transform" in modifications:
                    operation_type = "transform+material"

                create_version(
                    model_id=model_id,
                    operation_type=operation_type,
                    operation_details=modifications,
                    comment="Model modifications saved",
                )
                app_module.logger.info(
                    f"[save_modifications] Created version entry for {model_id}"
                )
            except Exception as version_error:
                app_module.logger.error(
                    f"[save_modifications] Failed to create version: {version_error}"
                )

            return jsonify(
                {
                    "success": True,
                    "message": "Model saved successfully",
                    "backup": os.path.basename(backup_path),
                }
            )
        else:
            app_module.logger.error("[save_modifications] Modification failed")
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return jsonify({"success": False, "error": "Failed to modify GLB"}), 500

    except Exception as e:
        app_module.logger.error(f"[save_modifications] Error: {e}", exc_info=True)
        # modify_glb writes to temp_output before any later step can raise;
        # clean it up so a failed save doesn't leave orphaned temp_*.glb files.
        if 'temp_output' in locals() and os.path.exists(temp_output):
            os.remove(temp_output)
        return jsonify({"success": False, "error": str(e)}), 500


@model_editing_bp.route("/get_mesh_bounds/<model_id>")
def api_get_mesh_bounds_route(model_id):
    """Get mesh bounding box for slicer"""
    import app as app_module

    guard = check_model_mutation_allowed(model_id)
    if guard is not None:
        return guard
    try:
        model = get_live_model(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        from mesh_slicer import get_mesh_bounds as get_bounds

        model_path = model.filename

        if not os.path.exists(model_path):
            return jsonify({"success": False, "error": "Model not found"}), 404

        bounds = get_bounds(model_path)

        if bounds:
            return jsonify({"success": True, "bounds": bounds})
        else:
            return jsonify({"success": False, "error": "Failed to get bounds"}), 500

    except Exception as e:
        app_module.logger.error(f"Error getting mesh bounds: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@model_editing_bp.route("/slice_model", methods=["POST"])
def slice_model():
    """Slice a 3D model with a plane"""
    import app as app_module
    from converters.glb_quality import finalize_glb

    try:
        from mesh_slicer import slice_mesh_multi

        data = request.json
        model_id = data.get("model_id")

        # Accept either the new atomic multi-plane payload (`planes`) or the legacy
        # single-plane fields. Everything is funnelled through one multi-plane slice
        # so X+Y+Z is applied in a single pass producing ONE backup + ONE version.
        planes = data.get("planes")
        if not planes:
            single_origin = data.get("plane_origin")
            single_normal = data.get("plane_normal")
            if single_origin and single_normal:
                planes = [
                    {
                        "plane_origin": single_origin,
                        "plane_normal": single_normal,
                        "keep_side": data.get("keep_side", "positive"),
                    }
                ]

        app_module.logger.info(
            f"[slice_model] Received request for model_id: {model_id}, "
            f"{len(planes) if planes else 0} plane(s)"
        )

        if not model_id or not planes:
            return jsonify(
                {"success": False, "error": "Missing required parameters"}
            ), 400

        # Owner guard (models without a DB record are treated as anonymous)
        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        # Try to find the model file
        # First check if model_id is a UUID (converted model)
        input_path = os.path.join(app_module.app.config["CONVERTED_FOLDER"], model_id, "model.glb")

        if not os.path.exists(input_path):
            # Maybe model_id is the full filename from database
            model = UserModel.query.get(model_id)
            if model and model.filename:
                # model.filename is the full storage path "<CONVERTED_FOLDER>/<uuid>/model.glb"
                # (CONVERTED_FOLDER is absolute, so splitting on "/" and indexing
                # doesn't recover the uuid — take the parent directory's basename instead).
                folder_id = os.path.basename(os.path.dirname(model.filename))
                if folder_id:
                    input_path = os.path.join(
                        app_module.app.config["CONVERTED_FOLDER"], folder_id, "model.glb"
                    )
                    app_module.logger.info(f"[slice_model] Trying alternate path: {input_path}")

        if not os.path.exists(input_path):
            app_module.logger.error(f"[slice_model] Model not found at: {input_path}")
            app_module.logger.error(
                f"[slice_model] CONVERTED_FOLDER: {app_module.app.config['CONVERTED_FOLDER']}"
            )
            app_module.logger.error(f"[slice_model] model_id: {model_id}")
            return jsonify(
                {"success": False, "error": f"Model not found at {input_path}"}
            ), 404

        # trimesh can't decode meshopt/draco-compressed GLBs -- decompress in
        # place first (slicing rewrites geometry to uncompressed form anyway)
        # instead of hard-blocking, so compressed models can be sliced.
        from converters.glb_optimizer import decompress_glb_in_place

        if decompress_glb_in_place(input_path):
            app_module.logger.info(f"[slice_model] Decompressed {model_id} for slicing")

        # Create backup
        backup_path = os.path.join(
            app_module.app.config["CONVERTED_FOLDER"],
            model_id,
            f"model_backup_{int(time.time())}.glb",
        )
        shutil.copy2(input_path, backup_path)
        app_module.logger.info(f"[slice_model] Created backup: {backup_path}")
        app_module.cleanup_old_backups(os.path.dirname(backup_path))

        # Slice the mesh
        temp_output = os.path.join(
            app_module.app.config["CONVERTED_FOLDER"],
            model_id,
            f"temp_sliced_{int(time.time())}.glb",
        )

        slice_result = slice_mesh_multi(
            input_path=input_path,
            output_path=temp_output,
            planes=planes,
        )
        success = bool(slice_result.get("success"))

        if success and os.path.exists(temp_output):
            # Replace original with sliced version (atomic on same volume)
            os.replace(temp_output, input_path)
            app_module.logger.info(
                f"[slice_model] Successfully replaced original with sliced mesh"
            )

            # Re-run the same GLB quality pass upload does: patches any
            # primitive that slicing left materialless with a default PBR
            # material and re-asserts doubleSided, since nothing else does
            # this after a slice (idempotent — never touches existing artwork).
            quality_warnings = []
            try:
                quality_warnings = finalize_glb(input_path, search_dirs=[os.path.dirname(input_path)])
                for w in quality_warnings:
                    app_module.logger.warning(f"[slice_model] GLB quality: {w}")
            except Exception as e:
                app_module.logger.warning(f"[slice_model] GLB quality pass skipped: {e}")

            # Rebuild the iOS USDZ from the sliced GLB (Quick Look uses it).
            app_module.refresh_usdz_after_edit(model_id, input_path)

            # Update dimensions in database
            try:
                mesh = trimesh.load(input_path, force="mesh")

                if isinstance(mesh, trimesh.Scene):
                    meshes = list(mesh.geometry.values())
                    if meshes:
                        mesh = trimesh.util.concatenate(meshes)

                bounds = mesh.bounds
                dimensions = bounds[1] - bounds[0]
                new_dims = {
                    "x": round(float(dimensions[0] * 100), 2),
                    "y": round(float(dimensions[1] * 100), 2),
                    "z": round(float(dimensions[2] * 100), 2),
                    "max": round(float(max(dimensions) * 100), 2),
                }

                model = UserModel.query.get(model_id)
                if model:
                    # Persist to the `bounds` column in the shape view_model reads.
                    model.bounds = json.dumps(
                        {
                            "extents": [new_dims["x"], new_dims["y"], new_dims["z"]],
                            "max": new_dims["max"],
                        }
                    )
                    model.file_size = os.path.getsize(input_path)
                    model.vertices, model.faces = _mesh_vertex_face_counts(mesh)
                    db.session.commit()
                    app_module.logger.info(f"[slice_model] Updated dimensions: {new_dims}")
                    # A slice changes the geometry outright -- the library
                    # card must not keep showing the pre-slice thumbnail.
                    _invalidate_thumbnail(app_module, model)

            except Exception as dim_error:
                app_module.logger.error(f"[slice_model] Failed to update dimensions: {dim_error}")

            # Create a SINGLE version entry for the whole multi-plane slice
            try:
                axis_count = len(planes)
                create_version(
                    model_id=model_id,
                    operation_type="slice",
                    operation_details={"planes": planes},
                    comment=f"Sliced model ({axis_count} plane(s))",
                )
                app_module.logger.info(f"[slice_model] Created version entry for {model_id}")
            except Exception as version_error:
                app_module.logger.error(f"[slice_model] Failed to create version: {version_error}")

            # Surface near-flat results, lost materials, or GLB quality issues
            # so the UI can warn the user instead of a silently degraded model.
            warnings = []
            if slice_result.get("degenerate"):
                warnings.append(
                    "The slice result is nearly flat — one dimension is almost zero. "
                    "Check the kept side / slider position."
                )
            if slice_result.get("material_warning"):
                warnings.append(slice_result["material_warning"])
            warnings.extend(quality_warnings)

            response = {
                "success": True,
                "message": "Model sliced successfully",
                "backup": os.path.basename(backup_path),
            }
            if warnings:
                response["warning"] = " ".join(warnings)
            return jsonify(response)
        else:
            app_module.logger.error("[slice_model] Slicing failed")
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return jsonify({"success": False, "error": "Failed to slice model"}), 500

    except Exception as e:
        app_module.logger.error(f"[slice_model] Error: {e}", exc_info=True)
        # slice_mesh_multi may have partially written temp_output before this
        # raised; clean it up so a failed slice doesn't leave an orphaned
        # temp_sliced_*.glb behind forever.
        if 'temp_output' in locals() and os.path.exists(temp_output):
            os.remove(temp_output)
        return jsonify({"success": False, "error": str(e)}), 500
