"""add Plan table, User.plan_expires_at, Payment provider columns"""
from alembic import op
import sqlalchemy as sa

revision = "d4a9c7e12f38"
down_revision = "c3f8a1e2d5b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=60), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="TRY"),
        sa.Column("billing_period", sa.String(length=10), nullable=False, server_default="monthly"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("limits", sa.JSON(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("plan") as batch_op:
        batch_op.create_index("ix_plan_slug", ["slug"], unique=True)

    with op.batch_alter_table("user") as batch_op:
        batch_op.add_column(sa.Column("plan_expires_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_user_plan_expires_at", ["plan_expires_at"], unique=False)

    with op.batch_alter_table("payment") as batch_op:
        batch_op.add_column(sa.Column("provider", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("provider_ref", sa.String(length=120), nullable=True))
        batch_op.create_index("ix_payment_provider_ref", ["provider_ref"], unique=True)


def downgrade():
    with op.batch_alter_table("payment") as batch_op:
        batch_op.drop_index("ix_payment_provider_ref")
        batch_op.drop_column("provider_ref")
        batch_op.drop_column("provider")

    with op.batch_alter_table("user") as batch_op:
        batch_op.drop_index("ix_user_plan_expires_at")
        batch_op.drop_column("plan_expires_at")

    with op.batch_alter_table("plan") as batch_op:
        batch_op.drop_index("ix_plan_slug")
    op.drop_table("plan")
