"""Shared view/mutation authorization guards for model-scoped routes.

Extracted from app.py so both the future route blueprints and admin.py can
import these without recreating app.py's import graph (admin.py deliberately
avoids importing app.py to prevent a circular import with worker.py).
"""

from flask import jsonify, request, session
from flask_login import current_user

from models import ModelShareLink, OrganizationMember, UserModel, db
from services.model_access import ModelAccessService

model_access = ModelAccessService(UserModel)


def get_live_model(model_id):
    """Find a model only when it is not in trash."""
    return model_access.live(model_id)


def _active_share_grant(model_id):
    """Resolve a session grant against the current share-link state.

    Storing only a permission in the session made revoked and expired links
    effective until the browser session ended. Grants now retain the link id
    and are revalidated on every protected model operation.
    """
    grants = dict(session.get("model_share_grants", {}))
    grant = grants.get(model_id)
    if not isinstance(grant, dict) or not grant.get("link_id"):
        if grant is not None:
            grants.pop(model_id, None)
            session["model_share_grants"] = grants
        return None
    link = db.session.get(ModelShareLink, grant["link_id"])
    if not link or link.model_id != model_id or not link.is_active:
        grants.pop(model_id, None)
        session["model_share_grants"] = grants
        return None
    return link.permission


def check_model_mutation_allowed(model_id, require_exists=True):
    """Owner guard for model mutation endpoints.

    Anonymous models require their edit capability token. User and organization
    models require owner/editor authorization. Returns a response tuple to return from
    the view, or None when the mutation is allowed.
    """
    body = request.get_json(silent=True) or {}
    token = (request.headers.get("X-Model-Edit-Token") or
             request.args.get("edit_token") or body.get("edit_token") or
             session.get(f"model_edit_token:{model_id}"))
    actor_id = current_user.id if current_user.is_authenticated else None
    grant = _active_share_grant(model_id)
    model = db.session.get(UserModel, model_id)
    organization_can_edit = False
    if actor_id and model and model.organization_id:
        membership = OrganizationMember.query.filter_by(
            organization_id=model.organization_id, user_id=actor_id
        ).first()
        organization_can_edit = bool(membership and membership.role in {"owner", "admin", "editor"})
    _, decision = model_access.mutation_decision(
        model_id, actor_id=actor_id, edit_token=token,
        share_can_edit=grant == "edit", organization_can_edit=organization_can_edit,
        require_exists=require_exists,
        actor_is_admin=bool(current_user.is_authenticated and current_user.is_admin),
    )
    if not decision.allowed:
        return jsonify({"success": False, "error": decision.error}), decision.status
    if token:
        session[f"model_edit_token:{model_id}"] = token
    return None


def check_model_view_allowed(model_id):
    actor_id = current_user.id if current_user.is_authenticated else None
    grant = _active_share_grant(model_id)
    model = db.session.get(UserModel, model_id)
    organization_member = bool(
        actor_id and model and model.organization_id and
        OrganizationMember.query.filter_by(
            organization_id=model.organization_id, user_id=actor_id
        ).first()
    )
    _, decision = model_access.view_decision(
        model_id, actor_id=actor_id, has_share_grant=grant is not None,
        organization_member=organization_member,
        actor_is_admin=bool(current_user.is_authenticated and current_user.is_admin),
    )
    if not decision.allowed:
        return decision
    return None
