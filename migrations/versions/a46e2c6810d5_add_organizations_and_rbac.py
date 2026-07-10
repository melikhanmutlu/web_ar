"""add organizations and rbac"""
from alembic import op
import sqlalchemy as sa

revision = "a46e2c6810d5"
down_revision = "f35d1b5709c4"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "organization",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(140), nullable=False, unique=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organization_slug", "organization", ["slug"], unique=True)
    op.create_table(
        "organization_member",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
    )
    op.create_index("ix_organization_member_organization_id", "organization_member", ["organization_id"])
    op.create_index("ix_organization_member_user_id", "organization_member", ["user_id"])
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_user_model_organization", "organization", ["organization_id"], ["id"])
        batch_op.create_index("ix_user_model_organization_id", ["organization_id"])

def downgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.drop_index("ix_user_model_organization_id")
        batch_op.drop_constraint("fk_user_model_organization", type_="foreignkey")
        batch_op.drop_column("organization_id")
    op.drop_table("organization_member")
    op.drop_table("organization")
