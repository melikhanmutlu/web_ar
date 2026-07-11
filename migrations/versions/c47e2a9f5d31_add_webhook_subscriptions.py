"""add webhook_subscription table

User-owned HTTPS endpoints notified on conversion/AI generation
completion events (fire-and-forget delivery, no retry queue).
"""
from alembic import op
import sqlalchemy as sa

revision = "c47e2a9f5d31"
down_revision = "b2f4a8c1d6e3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "webhook_subscription",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret", sa.String(length=64), nullable=False),
        sa.Column("event_types", sa.String(length=300), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_webhook_subscription_user_id", "webhook_subscription", ["user_id"]
    )


def downgrade():
    op.drop_index("ix_webhook_subscription_user_id", table_name="webhook_subscription")
    op.drop_table("webhook_subscription")
