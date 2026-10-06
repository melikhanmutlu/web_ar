"""ARC-06: an explicit APP_ENV wins over the DATABASE_URL production inference."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import config

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("environ, expected", [
    ({}, False),
    ({"DATABASE_URL": "sqlite:///x.db"}, True),          # inference unchanged
    ({"RAILWAY_ENVIRONMENT": "production"}, True),
    ({"APP_ENV": "production"}, True),
    ({"APP_ENV": "development", "DATABASE_URL": "postgresql://h/db"}, False),
    ({"APP_ENV": "test", "RAILWAY_ENVIRONMENT": "production"}, False),
    ({"APP_ENV": " Production "}, True),                   # case/space tolerant
])
def test_detect_production(environ, expected):
    assert config._detect_production(environ, "development") is expected


def test_flask_env_production_still_inferred_without_app_env():
    assert config._detect_production({}, "production") is True
    assert config._detect_production({"APP_ENV": "development"}, "production") is False


def test_unknown_app_env_is_rejected():
    with pytest.raises(RuntimeError, match="APP_ENV"):
        config._detect_production({"APP_ENV": "staging"}, "development")


@pytest.mark.parametrize("raw, default, expected", [
    (None, True, True), (None, False, False), ("", True, True),
    ("false", True, False), ("0", True, False), ("true", False, True), ("YES", False, True),
])
def test_env_flag(raw, default, expected):
    environ = {} if raw is None else {"SESSION_COOKIE_SECURE": raw}
    assert config._env_flag(environ, "SESSION_COOKIE_SECURE", default) is expected


def _import_config(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in {"APP_ENV", "SECRET_KEY", "WEB_AR_SECRET_KEY", "DATABASE_URL",
                        "RAILWAY_ENVIRONMENT", "FLASK_ENV", "SESSION_COOKIE_SECURE"}}
    env.update(extra)
    code = ("import config, json; print(json.dumps([config._IS_PRODUCTION, "
            "config.SESSION_COOKIE_SECURE, config.REMEMBER_COOKIE_SECURE]))")
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          capture_output=True, text=True)


def test_dev_app_env_with_database_url_boots_without_secret_key():
    result = _import_config(DATABASE_URL="sqlite:///local.db", APP_ENV="development")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [False, False, False]


def test_database_url_alone_still_requires_secret_key():
    result = _import_config(DATABASE_URL="sqlite:///local.db")
    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_production_app_env_requires_secret_key_and_sets_secure_cookies():
    assert _import_config(APP_ENV="production").returncode != 0
    result = _import_config(APP_ENV="production", SECRET_KEY="x")
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [True, True, True]


def test_session_cookie_secure_env_override():
    result = _import_config(APP_ENV="production", SECRET_KEY="x", SESSION_COOKIE_SECURE="false")
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [True, False, False]
