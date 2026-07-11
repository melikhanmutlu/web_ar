"""add ON DELETE rules to foreign keys

The ORM has delete-orphan cascades, but the database itself accepted
orphans (and SQLite never enforced FKs at all until the engine-level
PRAGMA hook in models.py). Recreate every child FK with an explicit
ON DELETE rule so raw SQL deletes and multi-process deletes stay
consistent on both SQLite and PostgreSQL.
"""
from alembic import op
import sqlalchemy as sa

revision = "8d4e1f7a2b9c"
down_revision = "4f2a9c108c31"
branch_labels = None
depends_on = None

# (table, column, referred_table, ondelete)
FK_RULES = [
    ("folder", "user_id", "user", "CASCADE"),
    ("folder", "parent_id", "folder", "CASCADE"),
    ("folder", "organization_id", "organization", "SET NULL"),
    ("organization_member", "organization_id", "organization", "CASCADE"),
    ("organization_member", "user_id", "user", "CASCADE"),
    ("organization_domain", "organization_id", "organization", "CASCADE"),
    ("api_token", "user_id", "user", "CASCADE"),
    ("api_token", "organization_id", "organization", "CASCADE"),
    ("user_model", "user_id", "user", "SET NULL"),
    ("user_model", "folder_id", "folder", "SET NULL"),
    ("user_model", "organization_id", "organization", "SET NULL"),
    ("model_share_link", "model_id", "user_model", "CASCADE"),
    ("model_analytics_event", "model_id", "user_model", "CASCADE"),
    ("model_hotspot", "model_id", "user_model", "CASCADE"),
    ("model_version", "model_id", "user_model", "CASCADE"),
    ("model_lod", "model_id", "user_model", "CASCADE"),
    ("model_derived_asset", "model_id", "user_model", "CASCADE"),
    ("camera_view", "model_id", "user_model", "CASCADE"),
    ("model_like", "model_id", "user_model", "CASCADE"),
    ("model_like", "user_id", "user", "SET NULL"),
    ("model_save", "model_id", "user_model", "CASCADE"),
    ("model_save", "user_id", "user", "CASCADE"),
    ("ai_generation_job", "user_id", "user", "SET NULL"),
    ("ai_generation_job", "parent_job_id", "ai_generation_job", "SET NULL"),
    ("ai_generation_job", "preset_id", "prompt_preset", "SET NULL"),
    ("prompt_preset", "user_id", "user", "CASCADE"),
    ("material_preset", "user_id", "user", "CASCADE"),
    ("material_preset", "organization_id", "organization", "SET NULL"),
    ("conversion_job", "user_id", "user", "SET NULL"),
    ("conversion_job_event", "job_id", "conversion_job", "CASCADE"),
]

# Deterministic names for unnamed FKs: production DBs may be chain-migrated
# (some FKs explicitly named) or bootstrapped via create_all + stamp (all
# unnamed), so drop by the reflected name when one exists and fall back to
# the convention name that batch-mode reflection assigns. Recreated
# constraints always get the canonical convention name.
NAMING_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _fk_name(table, column, referred):
    return f"fk_{table}_{column}_{referred}"


def _existing_fk_names(bind, table):
    """Map constrained column -> real constraint name (None when unnamed)."""
    inspector = sa.inspect(bind)
    names = {}
    for fk in inspector.get_foreign_keys(table):
        if len(fk["constrained_columns"]) == 1:
            names[fk["constrained_columns"][0]] = fk["name"]
    return names


def _clean_orphans():
    """The new constraints validate existing rows; repair orphans first."""
    for table, column, referred, ondelete in FK_RULES:
        orphaned = (
            f'{column} IS NOT NULL AND {column} NOT IN (SELECT id FROM "{referred}")'
        )
        if ondelete == "SET NULL" or (table == "folder" and column == "parent_id"):
            # Self-referencing folder tree included: promote orphaned subtrees
            # instead of deleting user data during a schema migration.
            op.execute(f'UPDATE "{table}" SET {column} = NULL WHERE {orphaned}')
        else:
            op.execute(f'DELETE FROM "{table}" WHERE {orphaned}')


def _apply(ondelete_for):
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    tables = {}
    for rule in FK_RULES:
        tables.setdefault(rule[0], []).append(rule)

    for table, rules in tables.items():
        existing = _existing_fk_names(bind, table)
        if sqlite:
            with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch:
                for _, column, referred, ondelete in rules:
                    name = existing.get(column) or _fk_name(table, column, referred)
                    batch.drop_constraint(name, type_="foreignkey")
                    batch.create_foreign_key(
                        _fk_name(table, column, referred),
                        referred, [column], ["id"],
                        ondelete=ondelete_for(ondelete),
                    )
        else:
            for _, column, referred, ondelete in rules:
                name = existing.get(column)
                if name is None:
                    raise RuntimeError(f"Could not reflect FK name for {table}.{column}")
                op.drop_constraint(name, table, type_="foreignkey")
                op.create_foreign_key(
                    _fk_name(table, column, referred),
                    table, referred, [column], ["id"],
                    ondelete=ondelete_for(ondelete),
                )


def upgrade():
    _clean_orphans()
    _apply(lambda ondelete: ondelete)


def downgrade():
    _apply(lambda ondelete: None)
