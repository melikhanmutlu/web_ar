"""add user session_version column

Embedded in the Flask-Login id so every password change invalidates existing
session and remember-me cookies (they were valid until expiry before).

Revision ID: d2e4f6a8b0c1
Revises: c1f2a3b4d5e6
"""
from alembic import op
import sqlalchemy as sa

revision = "d2e4f6a8b0c1"
down_revision = "c1f2a3b4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "session_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("session_version")
