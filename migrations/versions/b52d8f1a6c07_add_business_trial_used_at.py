"""add user.business_trial_used_at

Self-serve 14-day Business trial (F2.4): records when a user redeemed their
one allowed trial so it can never be taken twice.
"""
from alembic import op
import sqlalchemy as sa

revision = "b52d8f1a6c07"
down_revision = "a71c93e5d284"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("business_trial_used_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("user", "business_trial_used_at")
