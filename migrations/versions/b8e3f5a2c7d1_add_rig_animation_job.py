"""add rig_animation_job table

Revision ID: b8e3f5a2c7d1
Revises: f7c2a1d9e4b6
Create Date: 2026-07-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b8e3f5a2c7d1'
down_revision = 'f7c2a1d9e4b6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rig_animation_job',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('model_id', sa.String(length=36), sa.ForeignKey('user_model.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('height_meters', sa.Float(), nullable=False),
        sa.Column('animation_action_ids', sa.JSON(), nullable=True),
        sa.Column('meshy_remesh_id', sa.String(length=80), nullable=True),
        sa.Column('meshy_rig_id', sa.String(length=80), nullable=True),
        sa.Column('meshy_animate_id', sa.String(length=80), nullable=True),
        sa.Column('stage', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('progress', sa.Integer(), nullable=True),
        sa.Column('result_model_id', sa.String(length=36), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('rig_animation_job')
