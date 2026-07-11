"""merge fk ondelete rules with prior head

Revision ID: 9e763c273aef
Revises: 3d462bc1154c, 8d4e1f7a2b9c
Create Date: 2026-07-11 11:47:31.313908

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9e763c273aef'
down_revision = ('3d462bc1154c', '8d4e1f7a2b9c')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
