"""email verification columns + private-by-default model visibility

Adds user.email_verified_at / user.pending_email and backfills every existing
user as verified so current customers aren't locked out of verified-only perks.
Also flips the user_model.visibility server default to "private" (existing rows
are untouched; the ORM sets "unlisted" for owner-less uploads).

Revision ID: f2b3c4d5e6f7
Revises: f3c4d5e6f7a8
"""
from alembic import op
import sqlalchemy as sa

revision = "f2b3c4d5e6f7"
down_revision = "f3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email_verified_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("pending_email", sa.String(120), nullable=True))
    op.execute(sa.text('UPDATE "user" SET email_verified_at = CURRENT_TIMESTAMP'))
    with op.batch_alter_table("user_model", schema=None) as batch_op:
        batch_op.alter_column(
            "visibility",
            existing_type=sa.String(20),
            existing_nullable=False,
            server_default="private",
        )


def downgrade():
    with op.batch_alter_table("user_model", schema=None) as batch_op:
        batch_op.alter_column(
            "visibility",
            existing_type=sa.String(20),
            existing_nullable=False,
            server_default="unlisted",
        )
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("pending_email")
        batch_op.drop_column("email_verified_at")
