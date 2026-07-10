"""add capability tokens"""
from alembic import op
import sqlalchemy as sa

revision = "c9e1a32f0b71"
down_revision = "b41c0de66a01"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.add_column(sa.Column("edit_token_hash", sa.String(255), nullable=True))
    with op.batch_alter_table("conversion_job") as batch_op:
        batch_op.add_column(sa.Column("status_token_hash", sa.String(255), nullable=True))

def downgrade():
    with op.batch_alter_table("conversion_job") as batch_op:
        batch_op.drop_column("status_token_hash")
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.drop_column("edit_token_hash")
