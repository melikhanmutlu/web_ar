"""
Model Version Manager
Handles version tracking for model modifications
"""

import os
import shutil
import logging
from datetime import datetime
from models import db, ModelVersion, UserModel

logger = logging.getLogger(__name__)


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
    try:
        model = UserModel.query.get(model_id)
        if not model:
            logger.error(f"Model {model_id} not found")
            return None
        
        # Get next version number
        last_version = ModelVersion.query.filter_by(model_id=model_id).order_by(ModelVersion.version_number.desc()).first()
        version_number = (last_version.version_number + 1) if last_version else 1
        
        # Copy current model file to version storage
        current_file = os.path.join('converted', model_id, 'model.glb')
        version_file = os.path.join('converted', model_id, f'version_{version_number}.glb')
        
        if os.path.exists(current_file):
            shutil.copy2(current_file, version_file)
            file_size = os.path.getsize(version_file)
        else:
            logger.error(f"Current model file not found: {current_file}")
            return None
        
        # Get model metadata
        import trimesh
        mesh = trimesh.load(current_file, force='mesh')
        
        if isinstance(mesh, trimesh.Scene):
            meshes = list(mesh.geometry.values())
            if meshes:
                mesh = trimesh.util.concatenate(meshes)
        
        bounds = mesh.bounds
        dimensions = bounds[1] - bounds[0]
        
        # Create version entry
        version = ModelVersion(
            model_id=model_id,
            version_number=version_number,
            filename=version_file,
            file_size=file_size,
            operation_type=operation_type,
            operation_details=operation_details,
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
        
        logger.info(f"Created version {version_number} for model {model_id}: {operation_type}")
        return version
        
    except Exception as e:
        logger.error(f"Failed to create version for model {model_id}: {e}", exc_info=True)
        db.session.rollback()
        return None


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
        
        if not os.path.exists(version.filename):
            logger.error(f"Version file not found: {version.filename}")
            return False
        
        # Create a new version before restoring (to preserve current state)
        create_version(model_id, 'restore', {'restored_from': version_number}, f'Restored from version {version_number}')
        
        # Copy version file to current model
        current_file = os.path.join('converted', model_id, 'model.glb')
        shutil.copy2(version.filename, current_file)
        
        # Update model metadata
        model = UserModel.query.get(model_id)
        if model and version.dimensions:
            model.original_dimensions = version.dimensions
            db.session.commit()
        
        logger.info(f"Restored model {model_id} to version {version_number}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to restore version {version_number} for model {model_id}: {e}", exc_info=True)
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
        
        # Delete version file
        if os.path.exists(version.filename):
            os.remove(version.filename)
        
        # Delete database entry
        db.session.delete(version)
        db.session.commit()
        
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
        
        versions_to_delete = versions[keep_last_n:]
        deleted_count = 0
        
        for version in versions_to_delete:
            if delete_version(model_id, version.version_number):
                deleted_count += 1
        
        logger.info(f"Cleaned up {deleted_count} old versions for model {model_id}")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Failed to cleanup versions for model {model_id}: {e}", exc_info=True)
        return 0
