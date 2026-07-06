"""add user_model.source column

Revision ID: c4d7e9f1a3b5
Revises: b8e3f5a2c7d1
Create Date: 2026-07-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c4d7e9f1a3b5'
down_revision = 'b8e3f5a2c7d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_model', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=30), nullable=True))


def downgrade():
    with op.batch_alter_table('user_model', schema=None) as batch_op:
        batch_op.drop_column('source')
