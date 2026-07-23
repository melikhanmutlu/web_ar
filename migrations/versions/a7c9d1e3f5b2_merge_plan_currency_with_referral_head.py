"""merge plan-currency-usd head with the referral-fields branch

Two migration chains had diverged and were never merged (confirmed while
testing the new plan-currency migration: `flask db upgrade` failed with
"Multiple heads are present"). Pure merge marker, no schema change.

Revision ID: a7c9d1e3f5b2
Revises: f1a2b3c4d5e6, c83a5e7f2b91
Create Date: 2026-07-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c9d1e3f5b2'
down_revision = ('f1a2b3c4d5e6', 'c83a5e7f2b91')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
