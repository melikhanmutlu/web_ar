"""Claim an anonymous uploader's models on register/login.

An anonymous upload is controlled by an edit capability token, which this
browser's session holds (services/model_permissions.py stores it under
``model_edit_token:<model_id>``). When that browser signs up or logs in, the
owner-less models whose token it still holds move to the account.
"""

from flask import flash, session

from models import UserModel, db
from services.plans import plan_limit
from services.storage_quota import _storage_quota_bytes, _storage_usage_for

_PREFIX = "model_edit_token:"


def claim_session_models(user):
    """Move owner-less models whose edit token this session holds to `user`.

    Claimed models become private (private-by-default for owned models). The
    plan's model-count and storage limits are respected: models are claimed
    oldest first until one no longer fits; the rest stay anonymous (their
    token stays in the session) so they can be claimed after freeing space.
    Returns (claimed, skipped_for_limits).
    """
    from werkzeug.security import check_password_hash

    tokens = {k[len(_PREFIX):]: v for k, v in list(session.items())
              if k.startswith(_PREFIX) and isinstance(v, str)}
    if not tokens:
        return 0, 0
    candidates = (
        UserModel.query.filter(UserModel.id.in_(list(tokens)), UserModel.user_id.is_(None),
                               UserModel.deleted_at.is_(None))
        .order_by(UserModel.upload_date.asc()).all()
    )
    candidates = [m for m in candidates
                  if m.edit_token_hash and check_password_hash(m.edit_token_hash, tokens[m.id])]
    if not candidates:
        return 0, 0

    cap = plan_limit(user, "max_models")  # None/0 => unlimited
    count = UserModel.query.filter(UserModel.user_id == user.id, UserModel.deleted_at.is_(None)).count()
    quota = _storage_quota_bytes(user)  # 0 => unlimited
    used = _storage_usage_for(user.id)

    claimed = skipped = 0
    for model in candidates:
        size = model.file_size or 0
        if (cap and count >= cap) or (quota and used + size > quota):
            skipped += 1
            continue
        model.user_id = user.id
        model.visibility = "private"
        model.edit_token_hash = None  # now owned; the capability token is retired
        session.pop(_PREFIX + model.id, None)
        count += 1
        used += size
        claimed += 1
    db.session.commit()
    return claimed, skipped


def claim_and_flash(user):
    """claim_session_models + the user-facing flash messages."""
    claimed, skipped = claim_session_models(user)
    if claimed:
        flash(f"{claimed} model{'' if claimed == 1 else 's'} saved to your library.", "success")
    if skipped:
        flash(f"{skipped} anonymous model{'' if skipped == 1 else 's'} could not be added because "
              "your plan's model or storage limit is reached. Free up space or upgrade "
              "your plan to keep them.", "info")
    return claimed, skipped
