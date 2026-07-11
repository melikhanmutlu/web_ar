"""add user plan column

Plan/billing foundation (Faz 5): which tier's limits apply to a user's
storage quota and AI daily limit.
"""
from alembic import op
import sqlalchemy as sa

revision = "e29f4b8d1c73"
down_revision = "d18a2f6c9e04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("plan", sa.String(length=20), nullable=False, server_default="free"),
    )


def downgrade():
    op.drop_column("user", "plan")
