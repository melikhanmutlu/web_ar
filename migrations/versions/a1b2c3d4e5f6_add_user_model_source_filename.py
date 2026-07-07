"""add user_model.source_filename column

Revision ID: a1b2c3d4e5f6
Revises: c4d7e9f1a3b5
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'c4d7e9f1a3b5'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_model', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_filename', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('user_model', schema=None) as batch_op:
        batch_op.drop_column('source_filename')
