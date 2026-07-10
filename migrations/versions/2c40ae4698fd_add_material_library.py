"""add reusable material library"""
from alembic import op
import sqlalchemy as sa

revision = "2c40ae4698fd"
down_revision = "1b3f9d3587ec"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "material_preset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id")),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("color", sa.String(7), nullable=False),
        sa.Column("metalness", sa.Float(), nullable=False),
        sa.Column("roughness", sa.Float(), nullable=False),
        sa.Column("opacity", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_material_preset_user_id", "material_preset", ["user_id"])
    op.create_index("ix_material_preset_organization_id", "material_preset", ["organization_id"])

def downgrade():
    op.drop_table("material_preset")
