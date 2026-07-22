"""add sales_lead table

B2B inbound enquiries from /contact-sales (and later the signal-mining
sweep): name/email/company/message plus a source tag and a follow-up status.
"""
from alembic import op
import sqlalchemy as sa

revision = "a71c93e5d284"
down_revision = "f3b8d1c6a9e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_lead",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=160), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sales_lead_email", "sales_lead", ["email"])
    op.create_index("ix_sales_lead_status", "sales_lead", ["status"])
    op.create_index("ix_sales_lead_created_at", "sales_lead", ["created_at"])


def downgrade():
    op.drop_index("ix_sales_lead_created_at", table_name="sales_lead")
    op.drop_index("ix_sales_lead_status", table_name="sales_lead")
    op.drop_index("ix_sales_lead_email", table_name="sales_lead")
    op.drop_table("sales_lead")
