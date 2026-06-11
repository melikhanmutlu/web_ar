"""add deleted_at to user_model (soft delete / trash)

Revision ID: b41c0de66a01
Revises: 578d7aabc06e
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b41c0de66a01'
down_revision = '578d7aabc06e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_model', schema=None) as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f('ix_user_model_deleted_at'), ['deleted_at'], unique=False)


def downgrade():
    with op.batch_alter_table('user_model', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_model_deleted_at'))
        batch_op.drop_column('deleted_at')
