"""add model LOD manifests"""
from alembic import op
import sqlalchemy as sa

revision = "f91d7b1365ca"
down_revision = "e80c6a0254b9"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "model_lod",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("user_model.id"), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("model_id", "level", name="uq_model_lod_level"),
    )
    op.create_index("ix_model_lod_model_id", "model_lod", ["model_id"])

def downgrade():
    op.drop_table("model_lod")
