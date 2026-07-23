"""Add SalesLead.admin_notes

Revision ID: b3d4e6f8a1c9
Revises: a7c9d1e3f5b2
Create Date: 2026-07-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = "b3d4e6f8a1c9"
down_revision = "a7c9d1e3f5b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sales_lead") as batch_op:
        batch_op.add_column(sa.Column("admin_notes", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("sales_lead") as batch_op:
        batch_op.drop_column("admin_notes")
