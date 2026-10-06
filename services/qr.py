"""QR-code generation for a model's viewer URL. Extracted from app.py."""

import logging
import os
import uuid

import qrcode
from flask import current_app, request, url_for
from sqlalchemy.orm import Session

from models import UserModel, db

logger = logging.getLogger(__name__)


def generate_qr_code(model_id):
    """Generate QR code for a model."""
    try:
        session = Session(db.engine)
        model = session.get(UserModel, model_id)
        if not model:
            logger.error(f"Model not found with ID: {model_id}")
            return None

        # Generate the absolute URL for the model view
        base_url = request.host_url.rstrip("/")  # Get base URL without trailing slash
        model_url = f"{base_url}{url_for('viewer.view_model', model_id=model_id)}"

        # Create QR code instance
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )

        # Add data to QR code
        qr.add_data(model_url)
        qr.make(fit=True)

        # Create QR code image with proper coloring
        qr_image = qr.make_image(fill_color="black", back_color="white")

        # Generate unique filename for QR code
        qr_filename = f"qr_{model_id}_{uuid.uuid4()}.png"
        qr_path = os.path.join(current_app.config["CONVERTED_FOLDER"], qr_filename)

        # Save QR code image
        qr_image.save(qr_path)

        # Update model with QR code filename
        model.qr_code = qr_filename
        db.session.commit()

        logger.info(f"QR code generated successfully: {qr_filename}")
        return qr_filename
    except Exception as e:
        logger.error(f"Error generating QR code: {str(e)}")
        return None
