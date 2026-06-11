"""One-time self-heal for the production alembic_version table.

The v26 design branch had its own migration chain (webar_* tables) and a
deploy stamped the production DB with its head (2b7a25cad39b). After main
was reverted to the v25 line, that revision no longer exists in the repo,
so `flask db upgrade` aborts with "Can't locate revision" and new
migrations (e.g. user_model.deleted_at) never run.

The actual v25-line schema state of that DB corresponds to 578d7aabc06e
(widen password_hash), so we re-point alembic_version there and let the
regular `flask db upgrade` in the start command apply the rest.

Safe to run on every boot: it only acts when alembic_version contains one
of the known-orphaned v26 revisions. The orphaned webar_* tables are left
in place (harmless; can be dropped manually later).
"""
import sys

from sqlalchemy import create_engine, text

sys.path.insert(0, '.')
from config import SQLALCHEMY_DATABASE_URI  # reuses postgres:// URL fix

# v26-only revisions that may be stamped in the production DB
ORPHANED_REVISIONS = {'2b7a25cad39b', 'e26f30fb4560'}
# Last v25-line revision that actually ran against that DB
KNOWN_GOOD_REVISION = '578d7aabc06e'


def main():
    engine = create_engine(SQLALCHEMY_DATABASE_URI)
    with engine.connect() as conn:
        try:
            current = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        except Exception:
            print("heal_alembic: no alembic_version table; nothing to do")
            return

        if current in ORPHANED_REVISIONS:
            conn.execute(
                text("UPDATE alembic_version SET version_num = :rev"),
                {"rev": KNOWN_GOOD_REVISION},
            )
            conn.commit()
            print(f"heal_alembic: re-pointed {current} -> {KNOWN_GOOD_REVISION}")
        else:
            print(f"heal_alembic: version {current} is known; nothing to do")


if __name__ == '__main__':
    main()
