"""add user referral_code + referred_by_id

Referral program (F3.2): each user gets a unique share code, and referred
users record who referred them (set once at registration).
"""
from alembic import op
import sqlalchemy as sa

revision = "c83a5e7f2b91"
down_revision = "b52d8f1a6c07"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("referral_code", sa.String(length=16), nullable=True))
    op.add_column("user", sa.Column("referred_by_id", sa.Integer(), nullable=True))
    op.create_index("ix_user_referral_code", "user", ["referral_code"], unique=True)
    # SQLite can't ALTER-ADD a constraint; use batch mode (copy-and-move) there,
    # and a plain ALTER on Postgres. Matches the pattern in 8d4e1f7a2b9c.
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch:
            batch.create_foreign_key(
                "fk_user_referred_by", "user",
                ["referred_by_id"], ["id"], ondelete="SET NULL",
            )
    else:
        op.create_foreign_key(
            "fk_user_referred_by", "user", "user",
            ["referred_by_id"], ["id"], ondelete="SET NULL",
        )


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("user") as batch:
            batch.drop_constraint("fk_user_referred_by", type_="foreignkey")
    else:
        op.drop_constraint("fk_user_referred_by", "user", type_="foreignkey")
    op.drop_index("ix_user_referral_code", table_name="user")
    op.drop_column("user", "referred_by_id")
    op.drop_column("user", "referral_code")
