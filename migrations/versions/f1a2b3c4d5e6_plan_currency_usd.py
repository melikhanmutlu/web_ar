"""Default plan pricing to USD instead of TRY

Revision ID: f1a2b3c4d5e6
Revises: 9e763c273aef
Create Date: 2026-07-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "9e763c273aef"
branch_labels = None
depends_on = None

plan = sa.table("plan", sa.column("currency", sa.String))


def upgrade():
    with op.batch_alter_table("plan") as batch_op:
        batch_op.alter_column("currency", server_default="USD")
    # Existing seeded/admin-created plans still carry the old TRY default —
    # this app's pricing is USD-only, so bring every plan in line, not just
    # future ones.
    op.execute(plan.update().where(plan.c.currency == "TRY").values(currency="USD"))


def downgrade():
    with op.batch_alter_table("plan") as batch_op:
        batch_op.alter_column("currency", server_default="TRY")
