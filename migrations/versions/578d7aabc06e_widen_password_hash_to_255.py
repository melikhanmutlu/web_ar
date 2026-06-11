"""widen user.password_hash to 255

Werkzeug 3.x defaults generate_password_hash to scrypt, whose output is
~160+ chars. Postgres enforces VARCHAR(128) (sqlite does not), so
registration failed with StringDataRightTruncation in production.

Revision ID: 578d7aabc06e
Revises: 3a81971f8f25
Create Date: 2026-06-10 13:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '578d7aabc06e'
down_revision = '3a81971f8f25'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column(
            'password_hash',
            existing_type=sa.String(length=128),
            type_=sa.String(length=255),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.alter_column(
            'password_hash',
            existing_type=sa.String(length=255),
            type_=sa.String(length=128),
            existing_nullable=True,
        )
