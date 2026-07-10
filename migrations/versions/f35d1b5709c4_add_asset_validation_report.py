"""add asset validation report"""
from alembic import op
import sqlalchemy as sa

revision = "f35d1b5709c4"
down_revision = "e24c0a46f8b3"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.add_column(sa.Column("validation_report", sa.JSON(), nullable=True))

def downgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.drop_column("validation_report")
