"""align models with the migrated schema (OPS-05)

- api_token.token_digest, model_share_link.token_digest, organization.slug,
  organization_domain.hostname: the migrations created both a UNIQUE constraint
  and a unique index (ix_*) on the same column. The model declares only the
  unique index, so drop the redundant constraint (its auto-created index goes
  with it; the ix_* unique index keeps enforcing uniqueness). PostgreSQL only:
  SQLite keeps the constraint inline in CREATE TABLE and the duplication is
  harmless there.
- hotspot_comment.created_at / payment.created_at: the DB is NOT NULL already;
  the models now say so. Defensive for DBs bootstrapped with create_all: NULL
  rows are backfilled, then the column is made NOT NULL if it is not already.
- ix_hotspot_comment_hotspot_id: now declared in the model; created here if a
  create_all-bootstrapped DB lacks it.

No data is dropped.

Revision ID: c7d8e9f0a1b2
Revises: a9f1c3e5b7d0
"""
from alembic import op
import sqlalchemy as sa

revision = "c7d8e9f0a1b2"
down_revision = "a9f1c3e5b7d0"
branch_labels = None
depends_on = None

# (table, column) pairs that carry a redundant UNIQUE constraint next to ix_*.
_DUP_UNIQUE = [
    ("api_token", "token_digest"),
    ("model_share_link", "token_digest"),
    ("organization", "slug"),
    ("organization_domain", "hostname"),
]
_NOT_NULL_CREATED_AT = ["hotspot_comment", "payment"]


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if bind.dialect.name == "postgresql":
        for table, column in _DUP_UNIQUE:
            has_unique_index = any(
                ix.get("unique")
                and ix["column_names"] == [column]
                and ix["name"] == f"ix_{table}_{column}"
                for ix in insp.get_indexes(table)
            )
            if not has_unique_index:
                continue  # keep the only uniqueness guarantee we have
            for uc in insp.get_unique_constraints(table):
                if uc["column_names"] == [column]:
                    op.drop_constraint(uc["name"], table, type_="unique")

    for table in _NOT_NULL_CREATED_AT:
        col = next(c for c in insp.get_columns(table) if c["name"] == "created_at")
        if col["nullable"]:
            op.execute(
                sa.text(f"UPDATE {table} SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
            )
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)

    if "ix_hotspot_comment_hotspot_id" not in {i["name"] for i in insp.get_indexes("hotspot_comment")}:
        op.create_index("ix_hotspot_comment_hotspot_id", "hotspot_comment", ["hotspot_id"])


def downgrade():
    # Restore the previous (redundant) shape on PostgreSQL. The NOT NULL and
    # index states are left as they were: they were already the live schema.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, column in _DUP_UNIQUE:
            op.create_unique_constraint(f"{table}_{column}_key", table, [column])
