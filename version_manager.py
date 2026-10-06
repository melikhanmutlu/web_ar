"""
Model Version Manager
Handles version tracking for model modifications
"""

import json
import os
import shutil
import logging
import uuid
from datetime import datetime
from models import db, ModelVersion, UserModel
from config import CONVERTED_FOLDER

logger = logging.getLogger(__name__)

# Reject absurdly large meshes before loading them into memory (DoS guard).
MAX_VERTICES = int(os.environ.get("MAX_MODEL_VERTICES", 5_000_000))


def _model_dir(model_id):
    """Storage-root aware path to a model's directory (respects the volume)."""
    return os.path.join(CONVERTED_FOLDER, model_id)


def version_path(version):
    """Live path to a version snapshot file.

    ModelVersion.filename stores an absolute path captured at snapshot time;
    when the storage root moves between deploys (e.g. a Railway volume is
    attached or its mount path changes) that path goes stale even though the
    file still exists under the current root. Resolve against the current
    CONVERTED_FOLDER first, falling back to the stored path.
    """
    live = os.path.join(_model_dir(version.model_id), os.path.basename(version.filename))
    if os.path.exists(live):
        return live
    return version.filename


def bump_asset_version(model_id):
    """Increment UserModel.asset_version (the ?v= cache-buster for GLB, USDZ and
    thumbnail URLs) after model.glb/thumbnail was rewritten. Best-effort: a
    failure must never fail the edit that already succeeded."""
    try:
        model = db.session.get(UserModel, model_id)
        if model:
            model.bump_asset_version()
            db.session.commit()
    except Exception as e:
        logger.warning(f"Failed to bump asset_version for {model_id}: {e}")
        db.session.rollback()


def _atomic_copy(src, dst):
    """Copy src over dst atomically (temp file + os.replace on same dir)."""
    tmp = f"{dst}.tmp.{os.getpid()}"
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def create_version(model_id, operation_type, operation_details=None, comment=None):
    """
    Create a new version entry for a model

    Args:
        model_id: UUID of the model
        operation_type: Type of operation ('upload', 'transform', 'slice', 'material')
        operation_details: Dict with operation details
        comment: Optional user comment

    Returns:
        ModelVersion object or None
    """
    version_file = None
    try:
        model = db.session.get(UserModel, model_id)
        if not model:
            logger.error(f"Model {model_id} not found")
            return None

        # Get next version number
        last_version = ModelVersion.query.filter_by(model_id=model_id).order_by(ModelVersion.version_number.desc()).first()
        version_number = (last_version.version_number + 1) if last_version else 1

        # Copy current model file to version storage
        current_file = os.path.join(_model_dir(model_id), 'model.glb')
        candidate = os.path.join(_model_dir(model_id), f'version_{version_number}.glb')

        if not os.path.exists(current_file):
            logger.error(f"Current model file not found: {current_file}")
            return None
        shutil.copy2(current_file, candidate)
        version_file = candidate
        file_size = os.path.getsize(version_file)

        # Get model metadata. trimesh can't decode meshopt/draco, so read a
        # decompressed temp copy of compressed models.
        import trimesh
        from converters.glb_optimizer import readable_glb

        with readable_glb(current_file) as readable_path:
            mesh = trimesh.load(readable_path, force='mesh')

        if isinstance(mesh, trimesh.Scene):
            meshes = list(mesh.geometry.values())
            if meshes:
                mesh = trimesh.util.concatenate(meshes)

        if not hasattr(mesh, 'vertices'):
            logger.error(f"Model {model_id} produced no mesh; skipping version metadata")
            _remove_quietly(version_file)  # the copy at version_file was already made above
            return None
        if len(mesh.vertices) > MAX_VERTICES:
            logger.error(
                f"Model {model_id} mesh too large "
                f"({len(mesh.vertices)} > {MAX_VERTICES} verts); skipping version"
            )
            _remove_quietly(version_file)
            return None

        bounds = mesh.bounds
        dimensions = bounds[1] - bounds[0]

        # Record the model's cumulative_scale alongside the snapshot (inside
        # the operation_details JSON — no schema change needed) so
        # restore_version can roll it back together with the geometry.
        # Callers commit their cumulative_scale update BEFORE calling
        # create_version, so this reflects the post-operation state.
        details = dict(operation_details or {})
        details.setdefault('cumulative_scale_after', float(model.cumulative_scale or 1.0))

        # Create version entry
        version = ModelVersion(
            model_id=model_id,
            version_number=version_number,
            filename=version_file,
            file_size=file_size,
            operation_type=operation_type,
            operation_details=details,
            dimensions={
                'x': round(float(dimensions[0] * 100), 2),
                'y': round(float(dimensions[1] * 100), 2),
                'z': round(float(dimensions[2] * 100), 2),
                'max': round(float(max(dimensions) * 100), 2)
            },
            vertices=len(mesh.vertices),
            faces=len(mesh.faces),
            comment=comment
        )

        db.session.add(version)
        db.session.commit()
        version_file = None  # committed: the row now owns the file

        logger.info(f"Created version {version_number} for model {model_id}: {operation_type}")

        # Each version is a full on-disk GLB copy — cap how many accumulate
        # per model regardless of call site (upload/transform/slice/AI/etc).
        # cleanup_old_versions() never raises, so a prune failure can't turn
        # a successful version creation into a failed one.
        cleanup_old_versions(model_id)

        return version

    except Exception as e:
        logger.error(f"Failed to create version for model {model_id}: {e}", exc_info=True)
        db.session.rollback()
        # Don't leave an orphaned version_N.glb that no DB row points at.
        _remove_quietly(version_file)
        return None


def _remove_quietly(path):
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def get_version_history(model_id):
    """
    Get all versions for a model
    
    Returns:
        List of ModelVersion objects, ordered by version_number desc
    """
    return ModelVersion.query.filter_by(model_id=model_id).order_by(ModelVersion.created_at.desc()).all()


def restore_version(model_id, version_number):
    """
    Restore a model to a specific version

    Records two new versions: an "Auto-backup before restoring vN" snapshot of
    the current state (so the restore can itself be undone), and a
    "Restored from vN" snapshot taken AFTER the file was copied back, so it
    reflects the restored content.

    Args:
        model_id: UUID of the model
        version_number: Version number to restore

    Returns:
        bool: True if successful
    """
    try:
        version = ModelVersion.query.filter_by(model_id=model_id, version_number=version_number).first()
        if not version:
            logger.error(f"Version {version_number} not found for model {model_id}")
            return False

        src = version_path(version)
        if not os.path.exists(src):
            logger.error(f"Version file not found: {src}")
            return False
        # Read what we need from the row now: the create_version() calls below
        # prune old versions, which could delete this very row/file.
        version_dimensions = version.dimensions
        version_vertices = version.vertices
        version_faces = version.faces
        restored_scale = (version.operation_details or {}).get('cumulative_scale_after')

        # Stash the restore source in a temp file before touching anything
        # else (see above: pruning could delete the version file under us).
        restore_source = f"{src}.restoring.{uuid.uuid4().hex}"
        shutil.copy2(src, restore_source)

        current_file = os.path.join(_model_dir(model_id), 'model.glb')
        try:
            # Preserve the current state first, so the restore is undoable.
            backup = create_version(
                model_id, 'backup', {'restored_from': version_number},
                f'Auto-backup before restoring version {version_number}',
            )
            if backup is None:
                logger.warning(f"Could not create pre-restore backup for model {model_id}")

            # Copy version file to current model atomically (temp + rename), so a
            # failure mid-copy never leaves a truncated model.glb being served.
            _atomic_copy(restore_source, current_file)
        finally:
            if os.path.exists(restore_source):
                os.remove(restore_source)

        # Update model metadata so the DB matches the restored GLB. `bounds`
        # is the column view_model actually renders dimensions from (writing
        # only original_dimensions left the viewer showing the pre-restore
        # size indefinitely). original_dimensions is the AS-UPLOADED size and
        # must stay untouched.
        model = db.session.get(UserModel, model_id)
        if model:
            if version_dimensions:
                model.bounds = json.dumps({
                    "extents": [
                        version_dimensions.get('x'),
                        version_dimensions.get('y'),
                        version_dimensions.get('z'),
                    ],
                    "max": version_dimensions.get('max'),
                })
            if os.path.exists(current_file):
                model.file_size = os.path.getsize(current_file)
            if version_vertices is not None:
                model.vertices = version_vertices
            if version_faces is not None:
                model.faces = version_faces
            # Roll cumulative_scale back with the geometry (recorded per
            # version by create_version; absent on versions created before
            # that was added — leave the current value in that case).
            if restored_scale is not None:
                model.cumulative_scale = float(restored_scale)
            model.bump_asset_version()
            db.session.commit()

        # Snapshot of the restored state (cumulative_scale_after is read from
        # the model row committed just above).
        create_version(
            model_id, 'restore', {'restored_from': version_number},
            f'Restored from version {version_number}',
        )

        logger.info(f"Restored model {model_id} to version {version_number}")
        return True

    except Exception as e:
        logger.error(f"Failed to restore version {version_number} for model {model_id}: {e}", exc_info=True)
        db.session.rollback()
        return False


def delete_version(model_id, version_number):
    """
    Delete a specific version
    
    Args:
        model_id: UUID of the model
        version_number: Version number to delete
    
    Returns:
        bool: True if successful
    """
    try:
        version = ModelVersion.query.filter_by(model_id=model_id, version_number=version_number).first()
        if not version:
            logger.error(f"Version {version_number} not found for model {model_id}")
            return False
        
        # Commit the DB deletion first; only remove the file once the row is
        # gone. Removing the file first risks losing data if the commit fails.
        version_file = version_path(version)
        db.session.delete(version)
        db.session.commit()

        if version_file and os.path.exists(version_file):
            try:
                os.remove(version_file)
            except OSError as file_err:
                logger.warning(f"Version row deleted but file remains {version_file}: {file_err}")

        logger.info(f"Deleted version {version_number} for model {model_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to delete version {version_number} for model {model_id}: {e}", exc_info=True)
        db.session.rollback()
        return False


def cleanup_old_versions(model_id, keep_last_n=10):
    """
    Clean up old versions, keeping only the last N versions
    
    Args:
        model_id: UUID of the model
        keep_last_n: Number of recent versions to keep
    
    Returns:
        int: Number of versions deleted
    """
    try:
        versions = ModelVersion.query.filter_by(model_id=model_id).order_by(ModelVersion.version_number.desc()).all()
        
        if len(versions) <= keep_last_n:
            return 0
        
        # Never prune the first (upload) version: it is the only way back to
        # the as-uploaded model. It takes one of the keep_last_n slots, so
        # the total stays capped.
        oldest = versions[-1]
        versions_to_delete = [v for v in versions[max(keep_last_n - 1, 0):] if v.id != oldest.id]
        deleted_count = 0
        
        for version in versions_to_delete:
            if delete_version(model_id, version.version_number):
                deleted_count += 1
        
        logger.info(f"Cleaned up {deleted_count} old versions for model {model_id}")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Failed to cleanup versions for model {model_id}: {e}", exc_info=True)
        return 0
