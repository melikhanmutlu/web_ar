"""add model analytics"""
from alembic import op
import sqlalchemy as sa

revision = "b57f3d7921e6"
down_revision = "a46e2c6810d5"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "model_analytics_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("user_model.id"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("visitor_hash", sa.String(64)),
        sa.Column("referrer_domain", sa.String(255)),
        sa.Column("device_type", sa.String(20)),
        sa.Column("event_metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_model_analytics_event_model_id", "model_analytics_event", ["model_id"])
    op.create_index("ix_model_analytics_event_event_type", "model_analytics_event", ["event_type"])
    op.create_index("ix_model_analytics_event_visitor_hash", "model_analytics_event", ["visitor_hash"])
    op.create_index("ix_model_analytics_event_created_at", "model_analytics_event", ["created_at"])

def downgrade():
    op.drop_table("model_analytics_event")
