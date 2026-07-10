from dataclasses import dataclass
from typing import Optional

from werkzeug.security import check_password_hash


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    status: int = 200
    error: Optional[str] = None


class ModelAccessService:
    """Central policy for model visibility and mutation capabilities."""

    def __init__(self, model_type):
        self.model_type = model_type

    def live(self, model_id):
        return self.model_type.query.filter_by(id=model_id, deleted_at=None).first()

    def mutation_decision(
        self, model_id, *, actor_id=None, edit_token=None, require_exists=True
    ):
        model = self.model_type.query.get(model_id)
        if model is None:
            if require_exists:
                return None, AccessDecision(False, 404, "Model not found")
            return None, AccessDecision(True)
        if model.deleted_at is not None:
            return model, AccessDecision(False, 410, "Model is in trash")
        if model.user_id is not None:
            if actor_id != model.user_id:
                return model, AccessDecision(False, 403, "Forbidden: you do not own this model")
            return model, AccessDecision(True)
        if model.edit_token_hash:
            if not edit_token or not check_password_hash(model.edit_token_hash, edit_token):
                return model, AccessDecision(False, 403, "Valid edit token required")
        return model, AccessDecision(True)
