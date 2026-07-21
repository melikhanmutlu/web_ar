"""add organization white-label branding"""
from alembic import op
import sqlalchemy as sa

revision = "c3f8a1e2d5b7"
down_revision = "b7e3f9a1c2d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("organization") as batch_op:
        batch_op.add_column(sa.Column("branding", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("organization") as batch_op:
        batch_op.drop_column("branding")
