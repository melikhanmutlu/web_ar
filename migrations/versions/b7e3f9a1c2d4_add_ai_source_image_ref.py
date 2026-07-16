"""add source_image_ref to ai_generation_job

Persist the source image used for image->3D generations (decoded to a real
file on disk; the column stores its path). Enables an admin audit preview of
what image a user used. Nullable -- text->3D jobs and older rows stay NULL.
"""
from alembic import op
import sqlalchemy as sa

revision = "b7e3f9a1c2d4"
down_revision = "a2c8e1f5b6d3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ai_generation_job",
        sa.Column("source_image_ref", sa.String(length=255), nullable=True),
    )


def downgrade():
    op.drop_column("ai_generation_job", "source_image_ref")
