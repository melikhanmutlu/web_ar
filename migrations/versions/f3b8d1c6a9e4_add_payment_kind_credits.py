"""add payment.kind + payment.credits

Credit top-up checkout: a Payment row can now record a prepaid AI-credit
purchase ('topup', with `credits` holding how many) next to the existing
subscription-period purchases ('plan').
"""
from alembic import op
import sqlalchemy as sa

revision = "f3b8d1c6a9e4"
down_revision = "e6f2a9c47d18"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payment",
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="plan"),
    )
    op.add_column("payment", sa.Column("credits", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("payment", "credits")
    op.drop_column("payment", "kind")
