"""payment e-invoice outcome columns

Payment.invoice_status ('none' | 'pending' | 'issued' | 'failed'),
invoice_external_id and invoice_error store the result of
services/invoicing.issue_invoice so un-invoiced payments can be reconciled.
Existing rows default to 'none'.

Revision ID: e0f1a2b3c4d5
Revises: c7d8e9f0a1b2
"""
from alembic import op
import sqlalchemy as sa

revision = "e0f1a2b3c4d5"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    existing = _columns("payment")
    with op.batch_alter_table("payment", schema=None) as batch_op:
        if "invoice_status" not in existing:
            batch_op.add_column(sa.Column("invoice_status", sa.String(length=10),
                                          nullable=False, server_default="none"))
        if "invoice_external_id" not in existing:
            batch_op.add_column(sa.Column("invoice_external_id", sa.String(length=120), nullable=True))
        if "invoice_error" not in existing:
            batch_op.add_column(sa.Column("invoice_error", sa.Text(), nullable=True))


def downgrade():
    existing = _columns("payment")
    with op.batch_alter_table("payment", schema=None) as batch_op:
        for name in ("invoice_error", "invoice_external_id", "invoice_status"):
            if name in existing:
                batch_op.drop_column(name)
