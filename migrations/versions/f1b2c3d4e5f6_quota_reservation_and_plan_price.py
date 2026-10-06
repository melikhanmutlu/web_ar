"""storage-quota reservations on conversion jobs

- conversion_job.reserved_bytes: bytes an in-flight upload job will add to its
  owner's storage; counted against the quota only while the job is
  pending/processing (services/storage_quota.py).

Revision ID: f1b2c3d4e5f6
Revises: c7d8e9f0a1b2
"""
from alembic import op
import sqlalchemy as sa

revision = "f1b2c3d4e5f6"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("conversion_job", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("reserved_bytes", sa.BigInteger(), nullable=False, server_default="0")
        )


def downgrade():
    with op.batch_alter_table("conversion_job", schema=None) as batch_op:
        batch_op.drop_column("reserved_bytes")
