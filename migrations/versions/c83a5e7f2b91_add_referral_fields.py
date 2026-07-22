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
    op.create_foreign_key(
        "fk_user_referred_by", "user", "user",
        ["referred_by_id"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_user_referred_by", "user", type_="foreignkey")
    op.drop_index("ix_user_referral_code", table_name="user")
    op.drop_column("user", "referred_by_id")
    op.drop_column("user", "referral_code")
