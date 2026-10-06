import os
import tempfile

# Point the app at a throwaway SQLite file BEFORE importing it. Flask-SQLAlchemy
# latches its engine from the config at import time, so setting
# SQLALCHEMY_DATABASE_URI inside a fixture (as this module used to) had no
# effect — the suite actually ran against, and db.drop_all()'d, the developer's
# real instance/app.db. Setting DATABASE_URL here (config.py reads it at import)
# guarantees isolation. A temp file (not :memory:) keeps the same DB across the
# multiple connections SQLAlchemy may open during a test.
#
# TEST_DATABASE_URL (e.g. postgresql+psycopg2://user:pw@host/db) points the suite
# at an external database instead — CI uses it to run the tests on PostgreSQL,
# the production dialect. Under pytest-xdist each worker gets its own database
# (<name>_<worker id>, created here and dropped at exit) so workers never share
# tables; SQLite already gets one temp file per process.
_EXTERNAL_DB_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


def _per_worker_database(url_str):
    """Under xdist, create/return a URL for a worker-private database."""
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return url_str
    import atexit

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    url = make_url(url_str)
    if not url.get_backend_name().startswith("postgresql"):
        return url_str
    worker_db = f"{url.database}_{worker}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{worker_db}"'))
        conn.execute(text(f'CREATE DATABASE "{worker_db}"'))

    def _drop():
        try:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{worker_db}" WITH (FORCE)'))
        except Exception:
            pass
        admin.dispose()

    atexit.register(_drop)
    return url.set(database=worker_db).render_as_string(hide_password=False)


if _EXTERNAL_DB_URL:
    os.environ["DATABASE_URL"] = _per_worker_database(_EXTERNAL_DB_URL)
else:
    _TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="arvision_test_")
    os.close(_TEST_DB_FD)
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
# Setting DATABASE_URL trips config.py's production detection, which then
# requires a SECRET_KEY — provide a fixed test one so import succeeds.
os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

import threading
import time

import pytest
from app import app, db, limiter
from models import User, Folder

def _join_new_threads(before, timeout=30):
    """Wait for background threads a test started (inline conversion, USDZ
    refresh) before the schema is dropped under them — otherwise they hit
    "relation does not exist"/IntegrityError after the test ended and leak
    into the next test."""
    deadline = time.monotonic() + timeout
    for t in threading.enumerate():
        if t is threading.current_thread() or t in before:
            continue
        t.join(max(0, deadline - time.monotonic()))


@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['RATELIMIT_ENABLED'] = False
    limiter.enabled = False
    # DB isolation is handled at import time via DATABASE_URL (see top of file);
    # the engine is already latched, so setting the URI here would be a no-op.
    app.config['WTF_CSRF_ENABLED'] = False
    # The DATABASE_URL above flips config into "production" mode, which marks
    # cookies Secure; the Werkzeug test client speaks http, so a Secure session
    # cookie would never be sent back and every login-dependent test would fail.
    # Cookie flags are read per-response (not latched), so overriding here works.
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['REMEMBER_COOKIE_SECURE'] = False
    # In production the fallback monthly AI quota is 0 (Free gets no AI unless
    # an admin grants some). Most AI tests just exercise the generation
    # pipeline, not the quota, so give the test app a generous fallback;
    # quota-specific tests override it via the ai_monthly_limit setting or by
    # monkeypatching setting_int.
    app.config['AI_GEN_MONTHLY_LIMIT'] = 100
    # Flask-Limiter's storage is a process-wide singleton, so hits accumulate
    # across every test in the session, not just within one test. Its
    # `enabled` flag is latched from app.config only once, at the init_app()
    # call that already happened at import time — setting the config key
    # here has no effect, so the instance attribute must be flipped directly.
    # Without this, repeated /login calls across the suite eventually trip
    # the real rate limit and 429 unrelated tests. Tests that specifically
    # cover rate-limit/lockout behavior flip this back on for their own body.
    limiter.enabled = False
    # In-process view/like dedupe state must not leak between tests.
    from services import abuse_guard
    abuse_guard.reset()

    _threads_before = set(threading.enumerate())

    with app.test_client() as client:
        with app.app_context():
            db.drop_all()
            db.create_all()
            # Seed the Plan table like production boot does, so DB-backed plan
            # lookups behave the same in tests (an empty table falls back to
            # PLAN_CONFIG, which pure-function/no-context tests still exercise).
            from services.plans import seed_plans_if_empty
            seed_plans_if_empty()
            yield client
            _join_new_threads(_threads_before)
            db.session.remove()
            db.drop_all()
    limiter.enabled = True

@pytest.fixture
def init_database():
    user = User(username='testuser', email='test@test.com')
    user.set_password('testpassword')
    db.session.add(user)
    db.session.commit()
    return user
