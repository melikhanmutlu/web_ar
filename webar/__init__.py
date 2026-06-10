"""WebAR — upload a 3D model, share it, view it in Augmented Reality.

Application factory. Production entrypoint is app.py (gunicorn app:app per
nixpacks.toml); the background converter is worker.py.
"""

import logging

from flask import Flask, render_template

from .config import Config, ensure_directories
from .extensions import csrf, db, limiter, login_manager, migrate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def create_app(config_object: type[Config] = Config) -> Flask:
    import os

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(
        __name__,
        template_folder=os.path.join(base, "templates"),
        static_folder=os.path.join(base, "static"),
    )
    app.config.from_object(config_object)
    ensure_directories(config_object)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from . import api, auth, views

    app.register_blueprint(views.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_e):
        max_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return render_template("errors/error.html",
                               code=413,
                               message=f"Dosya çok büyük (limit {max_mb} MB)."), 413

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("errors/error.html",
                               code=500,
                               message="Beklenmeyen bir hata oluştu."), 500

    if not app.config.get("SKIP_DB_BOOTSTRAP"):
        _bootstrap_database(app)

    return app


def _bootstrap_database(app: Flask) -> None:
    """Create missing tables and force-stamp Alembic to this codebase's head.

    Production runs `flask db upgrade` (with SKIP_DB_BOOTSTRAP=1) before the
    server starts, but a database that previously belonged to another
    migration chain (e.g. an older version of this app) carries an
    alembic_version this chain cannot locate, which would make every
    subsequent upgrade fail. Since create_all() guarantees our tables exist,
    overwriting alembic_version with our head is always correct here.
    Failures are logged, never fatal — gunicorn workers must still boot.
    """
    import os

    from sqlalchemy import text

    with app.app_context():
        try:
            db.create_all()

            from alembic.config import Config as AlembicConfig
            from alembic.script import ScriptDirectory

            migrations_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "migrations",
            )
            alembic_cfg = AlembicConfig(os.path.join(migrations_dir, "alembic.ini"))
            alembic_cfg.set_main_option("script_location", migrations_dir)
            head = ScriptDirectory.from_config(alembic_cfg).get_current_head()

            if head:
                with db.engine.begin() as conn:
                    conn.execute(text(
                        "CREATE TABLE IF NOT EXISTS alembic_version ("
                        "version_num VARCHAR(32) NOT NULL, "
                        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
                    ))
                    conn.execute(text("DELETE FROM alembic_version"))
                    conn.execute(
                        text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                        {"v": head},
                    )
        except BaseException as e:  # noqa: BLE001 — includes SystemExit from CLI helpers
            app.logger.warning(f"DB bootstrap skipped: {e}")
