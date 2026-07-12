"""Shared model deletion helpers.

Used by the site's own delete endpoints (app.py) and the admin panel
(admin.py) so hard-deleting a model behaves identically everywhere:
on-disk artifacts are removed best-effort (log-and-continue, matching the
original delete_model behavior), and the ModelLike/ModelSave rows — which
have no ORM cascade and would block the row delete under Postgres FK
enforcement — are cleaned up explicitly.
"""

import logging
import os
import shutil

from flask import current_app

from models import ModelLike, ModelSave, RigAnimationJob

logger = logging.getLogger(__name__)


def purge_model_storage(model_id, qr_code=None):
    """Remove a model's on-disk artifacts: converted dir, upload dir, QR image.

    File-system errors are logged and swallowed so the DB row deletion can
    proceed regardless (a missing volume must not make models undeletable).
    """
    for config_key in ("CONVERTED_FOLDER", "UPLOAD_FOLDER"):
        directory = os.path.join(current_app.config[config_key], str(model_id))
        try:
            if os.path.exists(directory):
                shutil.rmtree(directory)
                logger.info(f"Deleted directory: {directory}")
        except Exception as e:
            logger.error(f"Error deleting {directory}: {e}")

    if qr_code:
        qr_path = os.path.join(current_app.config["QR_FOLDER"], qr_code)
        try:
            if os.path.exists(qr_path):
                os.remove(qr_path)
                logger.info(f"Deleted QR code: {qr_path}")
        except Exception as e:
            logger.error(f"Error deleting QR code {qr_path}: {e}")


def purge_model_completely(session, model):
    """Hard-delete a model: files, engagement rows, then the row itself.

    Works with both db.session and a raw Session(db.engine). The caller
    owns the commit. Versions/hotspots/camera views are removed by their
    existing 'all, delete-orphan' cascades.
    """
    purge_model_storage(model.id, model.qr_code)
    session.query(ModelLike).filter_by(model_id=model.id).delete(
        synchronize_session=False
    )
    session.query(ModelSave).filter_by(model_id=model.id).delete(
        synchronize_session=False
    )
    # RigAnimationJob.model_id is a NOT NULL FK with no ORM cascade, so under
    # Postgres FK enforcement it blocks the row delete (IntegrityError at
    # commit) for any model that was ever rigged/animated — and callers remove
    # the files first, leaving a broken zombie. Clear the job rows explicitly.
    session.query(RigAnimationJob).filter_by(model_id=model.id).delete(
        synchronize_session=False
    )
    session.delete(model)
