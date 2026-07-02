"""add user.is_admin / user.is_active and the site_setting table

Foundation for the admin panel: a boolean admin flag, an account
active/deactivated flag, and a key/value table for admin-editable
runtime settings.

Revision ID: d92f4a7c81e3
Revises: b41c0de66a01
Create Date: 2026-07-02

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd92f4a7c81e3'
down_revision = 'b41c0de66a01'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true())
        )

    op.create_table(
        'site_setting',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('site_setting')
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('is_active')
        batch_op.drop_column('is_admin')
