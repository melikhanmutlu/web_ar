"""storage-quota reservations on conversion jobs + fractional plan prices

- conversion_job.reserved_bytes: bytes an in-flight upload job will add to its
  owner's storage; counted against the quota only while the job is
  pending/processing (services/storage_quota.py).
- plan.price: Integer -> Numeric(10, 2) so prices like 19.99 are expressible.
  Existing whole-number prices are preserved (19 -> 19.00).

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
    with op.batch_alter_table("plan", schema=None) as batch_op:
        batch_op.alter_column(
            "price", existing_type=sa.Integer(), type_=sa.Numeric(10, 2),
            existing_nullable=True,
        )


def downgrade():
    # Fractional prices are rounded to whole units (the old column can't hold cents).
    op.execute(sa.text("UPDATE plan SET price = ROUND(price) WHERE price IS NOT NULL"))
    with op.batch_alter_table("plan", schema=None) as batch_op:
        batch_op.alter_column(
            "price", existing_type=sa.Numeric(10, 2), type_=sa.Integer(),
            existing_nullable=True, postgresql_using="ROUND(price)::integer",
        )
    with op.batch_alter_table("conversion_job", schema=None) as batch_op:
        batch_op.drop_column("reserved_bytes")
