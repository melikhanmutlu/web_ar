"""OPS-23: a failed boot-time DB inspection must not bootstrap/stamp the schema."""
import os
import sqlite3
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SCRIPT = textwrap.dedent(
    """
    import sqlalchemy

    _orig = sqlalchemy.inspect

    def _flaky(subject, *a, **kw):
        # Only the boot inspection of the engine fails (simulated transient error).
        if type(subject).__name__ == "Engine":
            raise RuntimeError("simulated transient DB error")
        return _orig(subject, *a, **kw)

    sqlalchemy.inspect = _flaky
    import app  # noqa: F401  (boot block runs on import)
    """
)


def _boot(db_path, extra_env=None):
    env = dict(os.environ)
    env.pop("SKIP_DB_BOOTSTRAP", None)
    env.pop("TEST_DATABASE_URL", None)
    env.update(
        DATABASE_URL=f"sqlite:///{db_path}",
        SECRET_KEY="test-only-secret-key",
        JOB_QUEUE="false",
    )
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )


def test_failed_inspection_skips_create_all_and_stamp(tmp_path):
    db_path = tmp_path / "boot.db"
    result = _boot(db_path)
    assert result.returncode == 0, result.stderr[-2000:]

    tables = set()
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
    assert "alembic_version" not in tables
    assert "user" not in tables, "create_all must not run when inspection failed"
