"""add ai_generation_job.credit_spent

True while the job holds a prepaid overage credit that was spent to start it;
flipped to False when that credit is refunded after the job fails, so the
refund happens exactly once.

Revision ID: f3c4d5e6f7a8
Revises: e3f5a7b9c1d2
"""
from alembic import op
import sqlalchemy as sa

revision = "f3c4d5e6f7a8"
down_revision = "e3f5a7b9c1d2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ai_generation_job", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("credit_spent", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table("ai_generation_job", schema=None) as batch_op:
        batch_op.drop_column("credit_spent")
