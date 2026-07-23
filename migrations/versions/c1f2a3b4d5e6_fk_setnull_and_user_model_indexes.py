"""org.created_by + admin_audit_log.actor_id ON DELETE SET NULL; index user_model.user_id/folder_id

Deleting a user who created an Organization or performed an admin action used
to fail with a FK RESTRICT (created_by was NOT NULL, actor_id had no ON DELETE
rule), blocking the admin "Delete user" action. Make both nullable/SET NULL so
the user row can be removed while the org/audit row survives. Also index the
two hottest UserModel filter columns.

Revision ID: c1f2a3b4d5e6
Revises: b3d4e6f8a1c9
Create Date: 2026-07-23 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c1f2a3b4d5e6"
down_revision = "b3d4e6f8a1c9"
branch_labels = None
depends_on = None

# (table, column, referred_table, ondelete)
FK_RULES = [
    ("organization", "created_by", "user", "SET NULL"),
    ("admin_audit_log", "actor_id", "user", "SET NULL"),
]

NAMING_CONVENTION = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _fk_name(table, column, referred):
    return f"fk_{table}_{column}_{referred}"


def _existing_fk_names(bind, table):
    inspector = sa.inspect(bind)
    names = {}
    for fk in inspector.get_foreign_keys(table):
        if len(fk["constrained_columns"]) == 1:
            names[fk["constrained_columns"][0]] = fk["name"]
    return names


def _apply(ondelete_for, created_by_nullable):
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    for table, rules in {"organization": [FK_RULES[0]], "admin_audit_log": [FK_RULES[1]]}.items():
        existing = _existing_fk_names(bind, table)
        if sqlite:
            with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch:
                if table == "organization":
                    batch.alter_column(
                        "created_by", existing_type=sa.Integer(), nullable=created_by_nullable
                    )
                for _, column, referred, ondelete in rules:
                    name = existing.get(column) or _fk_name(table, column, referred)
                    batch.drop_constraint(name, type_="foreignkey")
                    batch.create_foreign_key(
                        _fk_name(table, column, referred),
                        referred, [column], ["id"], ondelete=ondelete_for(ondelete),
                    )
        else:
            if table == "organization":
                op.alter_column(
                    "organization", "created_by", existing_type=sa.Integer(),
                    nullable=created_by_nullable,
                )
            for _, column, referred, ondelete in rules:
                name = existing.get(column) or _fk_name(table, column, referred)
                op.drop_constraint(name, table, type_="foreignkey")
                op.create_foreign_key(
                    _fk_name(table, column, referred),
                    table, referred, [column], ["id"], ondelete=ondelete_for(ondelete),
                )


def upgrade():
    _apply(lambda ondelete: ondelete, True)
    op.create_index("ix_user_model_user_id", "user_model", ["user_id"])
    op.create_index("ix_user_model_folder_id", "user_model", ["folder_id"])


def downgrade():
    op.drop_index("ix_user_model_folder_id", table_name="user_model")
    op.drop_index("ix_user_model_user_id", table_name="user_model")
    _apply(lambda ondelete: None, False)
