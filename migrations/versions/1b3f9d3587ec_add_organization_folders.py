"""add organization shared folders"""
from alembic import op
import sqlalchemy as sa

revision = "1b3f9d3587ec"
down_revision = "0a2e8c2476db"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("folder") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_folder_organization", "organization", ["organization_id"], ["id"])
        batch_op.create_index("ix_folder_organization_id", ["organization_id"])

def downgrade():
    with op.batch_alter_table("folder") as batch_op:
        batch_op.drop_index("ix_folder_organization_id")
        batch_op.drop_constraint("fk_folder_organization", type_="foreignkey")
        batch_op.drop_column("organization_id")
