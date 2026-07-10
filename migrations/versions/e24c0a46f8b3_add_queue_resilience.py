"""add queue resilience and worker heartbeat"""
from alembic import op
import sqlalchemy as sa

revision = "e24c0a46f8b3"
down_revision = "d13b9f35e7a2"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("conversion_job") as batch_op:
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_conversion_job_next_attempt_at", ["next_attempt_at"])
    op.create_table(
        "worker_heartbeat",
        sa.Column("worker_id", sa.String(120), primary_key=True),
        sa.Column("hostname", sa.String(255)),
        sa.Column("process_id", sa.Integer()),
        sa.Column("current_job_id", sa.String(36)),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_worker_heartbeat_last_seen_at", "worker_heartbeat", ["last_seen_at"])
    op.create_table(
        "conversion_job_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("conversion_job.id"), nullable=False),
        sa.Column("level", sa.String(10), nullable=False, server_default="info"),
        sa.Column("event", sa.String(60), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("attempt", sa.Integer()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_conversion_job_event_job_id", "conversion_job_event", ["job_id"])
    op.create_index("ix_conversion_job_event_created_at", "conversion_job_event", ["created_at"])

def downgrade():
    op.drop_table("conversion_job_event")
    op.drop_table("worker_heartbeat")
    with op.batch_alter_table("conversion_job") as batch_op:
        batch_op.drop_index("ix_conversion_job_next_attempt_at")
        batch_op.drop_column("last_heartbeat_at")
        batch_op.drop_column("next_attempt_at")
