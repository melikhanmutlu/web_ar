"""add user ai_credit_balance column

Prepaid overage credits (1 credit = 1 AI generation) consumed after the
plan's monthly AI quota is exhausted. Admin-granted for now; a payment
provider tops it up later via the same grant seam.
"""
from alembic import op
import sqlalchemy as sa

revision = "f5b7c2e9a4d1"
down_revision = "c5b1d9f34e82"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "ai_credit_balance",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade():
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_column("ai_credit_balance")
