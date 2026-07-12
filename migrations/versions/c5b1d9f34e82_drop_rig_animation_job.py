"""drop rig_animation_job table

The rig/animation generation feature was removed. Drop its table; the
downgrade re-creates it (mirroring b8e3f5a2c7d1) so the migration is reversible.

Revision ID: c5b1d9f34e82
Revises: a3c9e1f24b70
"""
from alembic import op
import sqlalchemy as sa

revision = "c5b1d9f34e82"
down_revision = "a3c9e1f24b70"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("rig_animation_job")


def downgrade():
    op.create_table(
        "rig_animation_job",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("model_id", sa.String(length=36), sa.ForeignKey("user_model.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("height_meters", sa.Float(), nullable=False),
        sa.Column("animation_action_ids", sa.JSON(), nullable=True),
        sa.Column("meshy_remesh_id", sa.String(length=80), nullable=True),
        sa.Column("meshy_rig_id", sa.String(length=80), nullable=True),
        sa.Column("meshy_animate_id", sa.String(length=80), nullable=True),
        sa.Column("stage", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("result_model_id", sa.String(length=36), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
