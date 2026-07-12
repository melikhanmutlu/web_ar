"""add model_measurement table

Saved distance measurements between two points on a model (measure tool).
"""
from alembic import op
import sqlalchemy as sa

revision = "a3c9e1f24b70"
down_revision = "e29f4b8d1c73"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "model_measurement",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("ax", sa.Float(), nullable=False),
        sa.Column("ay", sa.Float(), nullable=False),
        sa.Column("az", sa.Float(), nullable=False),
        sa.Column("bx", sa.Float(), nullable=False),
        sa.Column("by", sa.Float(), nullable=False),
        sa.Column("bz", sa.Float(), nullable=False),
        sa.Column("distance_cm", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["user_model.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_measurement_model_id", "model_measurement", ["model_id"], unique=False
    )


def downgrade():
    op.drop_index("ix_model_measurement_model_id", table_name="model_measurement")
    op.drop_table("model_measurement")
