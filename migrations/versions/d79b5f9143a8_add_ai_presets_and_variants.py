"""add ai presets variants and seo metadata"""
from alembic import op
import sqlalchemy as sa

revision = "d79b5f9143a8"
down_revision = "c68a4e8032f7"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "prompt_preset",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("category", sa.String(60)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_prompt_preset_user_id", "prompt_preset", ["user_id"])
    op.create_index("ix_prompt_preset_category", "prompt_preset", ["category"])
    with op.batch_alter_table("ai_generation_job") as batch_op:
        batch_op.add_column(sa.Column("parent_job_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("preset_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_ai_generation_parent", "ai_generation_job", ["parent_job_id"], ["id"])
        batch_op.create_foreign_key("fk_ai_generation_preset", "prompt_preset", ["preset_id"], ["id"])
        batch_op.create_index("ix_ai_generation_job_parent_job_id", ["parent_job_id"])
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.add_column(sa.Column("seo_metadata", sa.JSON(), nullable=True))

def downgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.drop_column("seo_metadata")
    with op.batch_alter_table("ai_generation_job") as batch_op:
        batch_op.drop_index("ix_ai_generation_job_parent_job_id")
        batch_op.drop_constraint("fk_ai_generation_preset", type_="foreignkey")
        batch_op.drop_constraint("fk_ai_generation_parent", type_="foreignkey")
        batch_op.drop_column("preset_id")
        batch_op.drop_column("parent_job_id")
    op.drop_table("prompt_preset")
