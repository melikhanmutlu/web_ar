"""add model sharing policy"""
from alembic import op
import sqlalchemy as sa

revision = "d13b9f35e7a2"
down_revision = "c9e1a32f0b71"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.add_column(sa.Column("visibility", sa.String(20), nullable=False, server_default="unlisted"))
        batch_op.add_column(sa.Column("embed_allowed_domains", sa.Text(), nullable=True))
        batch_op.create_index("ix_user_model_visibility", ["visibility"])
    op.create_table(
        "model_share_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("user_model.id"), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("permission", sa.String(10), nullable=False, server_default="view"),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_model_share_link_model_id", "model_share_link", ["model_id"])
    op.create_index("ix_model_share_link_token_digest", "model_share_link", ["token_digest"], unique=True)
    op.create_index("ix_model_share_link_expires_at", "model_share_link", ["expires_at"])

def downgrade():
    op.drop_table("model_share_link")
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.drop_index("ix_user_model_visibility")
        batch_op.drop_column("embed_allowed_domains")
        batch_op.drop_column("visibility")
