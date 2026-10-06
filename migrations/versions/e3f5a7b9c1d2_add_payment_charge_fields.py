"""add payment charge_amount / charge_currency / fx_rate

PayTR settles in TRY while prices are listed in USD. Keep the list price in
amount/currency and record what was actually charged and at which rate.

Revision ID: e3f5a7b9c1d2
Revises: d2e4f6a8b0c1
"""
from alembic import op
import sqlalchemy as sa

revision = "e3f5a7b9c1d2"
down_revision = "d2e4f6a8b0c1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("payment", schema=None) as batch_op:
        batch_op.add_column(sa.Column("charge_amount", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("charge_currency", sa.String(3), nullable=True))
        batch_op.add_column(sa.Column("fx_rate", sa.Numeric(14, 6), nullable=True))


def downgrade():
    with op.batch_alter_table("payment", schema=None) as batch_op:
        batch_op.drop_column("fx_rate")
        batch_op.drop_column("charge_currency")
        batch_op.drop_column("charge_amount")
