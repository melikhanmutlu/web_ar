"""add lifecycle_email table

Dedupe ledger for worker-sent lifecycle emails (renewal reminders, win-back):
one row per email actually delivered, unique per (user_id, kind, dedupe_key).
"""
from alembic import op
import sqlalchemy as sa

revision = "e6f2a9c47d18"
down_revision = "d4a9c7e12f38"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lifecycle_email",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "dedupe_key", name="uq_lifecycle_email_once"),
    )
    op.create_index("ix_lifecycle_email_user_id", "lifecycle_email", ["user_id"])


def downgrade():
    op.drop_index("ix_lifecycle_email_user_id", table_name="lifecycle_email")
    op.drop_table("lifecycle_email")
