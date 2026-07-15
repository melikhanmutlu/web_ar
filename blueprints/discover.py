"""Public gallery: browse community models that owners made public."""
from flask import Blueprint, render_template, request

from models import UserModel, db

discover_bp = Blueprint("discover", __name__)

PAGE_SIZE = 24


@discover_bp.route("/discover")
@discover_bp.route("/community")
def discover():
    query = UserModel.query.filter(
        UserModel.visibility == "public", UserModel.deleted_at.is_(None)
    )
    search = request.args.get("q", "").strip()
    if search:
        like_pattern = f"%{search}%"
        query = query.filter(
            db.or_(
                UserModel.display_name.ilike(like_pattern),
                UserModel.tags.ilike(like_pattern),
            )
        )
    models = query.order_by(UserModel.upload_date.desc()).all()

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * PAGE_SIZE
    page_models = models[start:start + PAGE_SIZE]
    has_more = start + PAGE_SIZE < len(models)

    return render_template(
        "discover.html", models=page_models, search=search,
        page=page, has_more=has_more,
    )
