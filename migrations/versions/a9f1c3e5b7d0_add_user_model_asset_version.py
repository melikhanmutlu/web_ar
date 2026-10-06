"""add user_model.asset_version (cache-busting counter for GLB/USDZ/thumbnail)

Revision ID: a9f1c3e5b7d0
Revises: e3f5a7b9c1d2
"""
from alembic import op
import sqlalchemy as sa

revision = "a9f1c3e5b7d0"
down_revision = "e3f5a7b9c1d2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user_model", schema=None) as batch_op:
        batch_op.add_column(sa.Column("asset_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    with op.batch_alter_table("user_model", schema=None) as batch_op:
        batch_op.drop_column("asset_version")
