"""add viewer and white-label settings"""
from alembic import op
import sqlalchemy as sa

revision = "e80c6a0254b9"
down_revision = "d79b5f9143a8"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.add_column(sa.Column("viewer_settings", sa.JSON(), nullable=True))

def downgrade():
    with op.batch_alter_table("user_model") as batch_op:
        batch_op.drop_column("viewer_settings")
