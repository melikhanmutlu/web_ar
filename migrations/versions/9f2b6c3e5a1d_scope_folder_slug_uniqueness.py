"""scope folder slug uniqueness to owner/org/parent

Folder.slug was globally unique, so an unrelated user who happened to
generate the same slug would trigger an unexpected IntegrityError. The
namespace now matches the duplicate checks in the app: unique per
(user, organization, parent).
"""
from alembic import op
import sqlalchemy as sa

revision = "9f2b6c3e5a1d"
down_revision = "9e763c273aef"
branch_labels = None
depends_on = None

# Batch-mode reflection assigns this name to the baseline's unnamed
# UNIQUE(slug) constraint on SQLite so it can be dropped.
NAMING_CONVENTION = {
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _slug_unique_name(bind):
    for constraint in sa.inspect(bind).get_unique_constraints("folder"):
        if constraint["column_names"] == ["slug"]:
            return constraint["name"]
    return None


def upgrade():
    bind = op.get_bind()
    existing = _slug_unique_name(bind)
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("folder", naming_convention=NAMING_CONVENTION) as batch:
            batch.drop_constraint(existing or "uq_folder_slug", type_="unique")
            batch.create_unique_constraint(
                "uq_folder_scope_slug",
                ["user_id", "organization_id", "parent_id", "slug"],
            )
    else:
        if existing is None:
            raise RuntimeError("Could not reflect the folder slug UNIQUE constraint")
        op.drop_constraint(existing, "folder", type_="unique")
        op.create_unique_constraint(
            "uq_folder_scope_slug", "folder",
            ["user_id", "organization_id", "parent_id", "slug"],
        )


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("folder", naming_convention=NAMING_CONVENTION) as batch:
            batch.drop_constraint("uq_folder_scope_slug", type_="unique")
            batch.create_unique_constraint("uq_folder_slug", ["slug"])
    else:
        op.drop_constraint("uq_folder_scope_slug", "folder", type_="unique")
        op.create_unique_constraint("uq_folder_slug", "folder", ["slug"])
