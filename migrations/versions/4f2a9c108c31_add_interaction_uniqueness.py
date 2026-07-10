"""add interaction and version uniqueness

Revision ID: 4f2a9c108c31
Revises: 3d51bf5709ae
"""

from alembic import op


revision = "4f2a9c108c31"
down_revision = "3d51bf5709ae"
branch_labels = None
depends_on = None


def upgrade():
    # Preserve the oldest row if legacy races produced duplicates.
    op.execute("DELETE FROM model_like WHERE user_id IS NOT NULL AND id NOT IN (SELECT MIN(id) FROM model_like WHERE user_id IS NOT NULL GROUP BY model_id, user_id)")
    op.execute("DELETE FROM model_like WHERE session_id IS NOT NULL AND id NOT IN (SELECT MIN(id) FROM model_like WHERE session_id IS NOT NULL GROUP BY model_id, session_id)")
    op.execute("DELETE FROM model_save WHERE id NOT IN (SELECT MIN(id) FROM model_save GROUP BY model_id, user_id)")
    op.execute("DELETE FROM model_hotspot WHERE id NOT IN (SELECT MIN(id) FROM model_hotspot GROUP BY model_id, hotspot_id)")
    op.execute("DELETE FROM model_version WHERE id NOT IN (SELECT MIN(id) FROM model_version GROUP BY model_id, version_number)")
    with op.batch_alter_table("model_like") as batch:
        batch.create_unique_constraint("uq_model_like_user", ["model_id", "user_id"])
        batch.create_unique_constraint("uq_model_like_session", ["model_id", "session_id"])
    with op.batch_alter_table("model_save") as batch:
        batch.create_unique_constraint("uq_model_save_user", ["model_id", "user_id"])
    with op.batch_alter_table("model_hotspot") as batch:
        batch.create_unique_constraint("uq_model_hotspot_external_id", ["model_id", "hotspot_id"])
    with op.batch_alter_table("model_version") as batch:
        batch.create_unique_constraint("uq_model_version_number", ["model_id", "version_number"])


def downgrade():
    with op.batch_alter_table("model_version") as batch:
        batch.drop_constraint("uq_model_version_number", type_="unique")
    with op.batch_alter_table("model_hotspot") as batch:
        batch.drop_constraint("uq_model_hotspot_external_id", type_="unique")
    with op.batch_alter_table("model_save") as batch:
        batch.drop_constraint("uq_model_save_user", type_="unique")
    with op.batch_alter_table("model_like") as batch:
        batch.drop_constraint("uq_model_like_session", type_="unique")
        batch.drop_constraint("uq_model_like_user", type_="unique")
