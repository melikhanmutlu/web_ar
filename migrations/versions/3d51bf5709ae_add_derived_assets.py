"""add model derived assets"""
from alembic import op
import sqlalchemy as sa

revision = "3d51bf5709ae"
down_revision = "2c40ae4698fd"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "model_derived_asset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("user_model.id"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("asset_metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("model_id", "kind", name="uq_model_derived_kind"),
    )
    op.create_index("ix_model_derived_asset_model_id", "model_derived_asset", ["model_id"])

def downgrade():
    op.drop_table("model_derived_asset")
