"""add hotspot_comment table

Discussion replies pinned to a specific hotspot (Faz 3: hotspot
comment/discussion thread), separate from the hotspot's own title/description.
"""
from alembic import op
import sqlalchemy as sa

revision = "d18a2f6c9e04"
down_revision = "c47e2a9f5d31"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hotspot_comment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hotspot_id", sa.Integer(), sa.ForeignKey("model_hotspot.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_hotspot_comment_hotspot_id", "hotspot_comment", ["hotspot_id"]
    )


def downgrade():
    op.drop_index("ix_hotspot_comment_hotspot_id", table_name="hotspot_comment")
    op.drop_table("hotspot_comment")
