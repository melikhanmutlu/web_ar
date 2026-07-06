"""add ai generation job options and texture_ref columns

Revision ID: f7c2a1d9e4b6
Revises: a3f6d1c9b5e2
Create Date: 2026-07-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f7c2a1d9e4b6'
down_revision = 'a3f6d1c9b5e2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('ai_generation_job', schema=None) as batch_op:
        batch_op.add_column(sa.Column('options', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('texture_ref', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('ai_generation_job', schema=None) as batch_op:
        batch_op.drop_column('texture_ref')
        batch_op.drop_column('options')
