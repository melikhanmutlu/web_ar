"""add admin_audit_log table

Revision ID: a3f6d1c9b5e2
Revises: e1a7c9b4f206
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a3f6d1c9b5e2'
down_revision = 'e1a7c9b4f206'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=True),
        sa.Column('target_id', sa.String(length=64), nullable=True),
        sa.Column('detail', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table('admin_audit_log', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_admin_audit_log_action'), ['action'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_admin_audit_log_created_at'), ['created_at'], unique=False
        )


def downgrade():
    with op.batch_alter_table('admin_audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_admin_audit_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_admin_audit_log_action'))
    op.drop_table('admin_audit_log')
