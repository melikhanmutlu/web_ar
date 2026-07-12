"""add payment table

Faz 5 billing foundation: manually-recorded payments (no payment provider
integrated yet -- an admin logs what a user paid for which plan and when).
"""
from alembic import op
import sqlalchemy as sa

revision = "a2c8e1f5b6d3"
down_revision = "f5b7c2e9a4d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="paid"),
        sa.Column("method", sa.String(length=40), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payment_user_id", "payment", ["user_id"])
    op.create_index("ix_payment_status", "payment", ["status"])
    op.create_index("ix_payment_created_at", "payment", ["created_at"])


def downgrade():
    op.drop_index("ix_payment_created_at", table_name="payment")
    op.drop_index("ix_payment_status", table_name="payment")
    op.drop_index("ix_payment_user_id", table_name="payment")
    op.drop_table("payment")
