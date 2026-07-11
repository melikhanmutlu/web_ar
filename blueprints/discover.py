"""Public gallery: browse models the community has made public."""
from flask import Blueprint, render_template, request

from models import ModelLike, UserModel, db

discover_bp = Blueprint("discover", __name__)

PAGE_SIZE = 24
SORT_OPTIONS = {"newest", "popular"}


@discover_bp.route("/discover")
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
    sort = request.args.get("sort", "newest")
    if sort not in SORT_OPTIONS:
        sort = "newest"
    like_counts = dict(
        db.session.query(ModelLike.model_id, db.func.count(ModelLike.id))
        .group_by(ModelLike.model_id).all()
    )
    if sort == "popular":
        # Small public catalogs are the expected scale here; sorting by a
        # precomputed dict in Python avoids a correlated subquery for a
        # feature that isn't performance-critical yet.
        models = sorted(
            query.all(), key=lambda m: like_counts.get(m.id, 0), reverse=True
        )
    else:
        models = query.order_by(UserModel.upload_date.desc()).all()

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    start = (page - 1) * PAGE_SIZE
    page_models = models[start:start + PAGE_SIZE]
    has_more = start + PAGE_SIZE < len(models)

    return render_template(
        "discover.html", models=page_models, like_counts=like_counts,
        search=search, sort=sort, page=page, has_more=has_more,
        total_count=len(models),
    )
