"""add tags to user_model

Comma-joined lowercase tags for the my-models search/filter UI.
"""
from alembic import op
import sqlalchemy as sa

revision = "b2f4a8c1d6e3"
down_revision = "9f2b6c3e5a1d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_model") as batch:
        batch.add_column(sa.Column("tags", sa.String(length=500), nullable=True))


def downgrade():
    with op.batch_alter_table("user_model") as batch:
        batch.drop_column("tags")
