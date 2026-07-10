"""add scoped api tokens"""
from alembic import op
import sqlalchemy as sa

revision = "c68a4e8032f7"
down_revision = "b57f3d7921e6"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "api_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id")),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("last_used_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_api_token_user_id", "api_token", ["user_id"])
    op.create_index("ix_api_token_organization_id", "api_token", ["organization_id"])
    op.create_index("ix_api_token_token_prefix", "api_token", ["token_prefix"])
    op.create_index("ix_api_token_token_digest", "api_token", ["token_digest"], unique=True)

def downgrade():
    op.drop_table("api_token")
