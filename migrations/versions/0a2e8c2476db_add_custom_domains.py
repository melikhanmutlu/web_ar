"""add organization custom domains"""
from alembic import op
import sqlalchemy as sa

revision = "0a2e8c2476db"
down_revision = "f91d7b1365ca"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "organization_domain",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False, unique=True),
        sa.Column("verification_token", sa.String(80), nullable=False),
        sa.Column("verified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organization_domain_organization_id", "organization_domain", ["organization_id"])
    op.create_index("ix_organization_domain_hostname", "organization_domain", ["hostname"], unique=True)
    op.create_index("ix_organization_domain_verified_at", "organization_domain", ["verified_at"])

def downgrade():
    op.drop_table("organization_domain")
