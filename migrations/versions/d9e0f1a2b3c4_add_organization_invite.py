"""organization invites (email invitation + accept flow)

Revision ID: d9e0f1a2b3c4
Revises: e0f1a2b3c4d5
"""
from alembic import op
import sqlalchemy as sa

revision = "d9e0f1a2b3c4"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if "organization_invite" in insp.get_table_names():
        return
    op.create_table(
        "organization_invite",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime()),
        sa.Column("invited_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organization_invite_organization_id", "organization_invite", ["organization_id"])
    op.create_index("ix_organization_invite_email", "organization_invite", ["email"])
    op.create_index("ix_organization_invite_token_hash", "organization_invite", ["token_hash"], unique=True)


def downgrade():
    op.drop_table("organization_invite")
