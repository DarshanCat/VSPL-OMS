"""Regression tests for cwd-independent DATABASE_URL / .env resolution (app/core/config.py).

Verifies:
1. DATABASE_URL resolves to the same absolute path regardless of process cwd.
2. An explicit OS environment variable takes precedence over .env and the class default.
3. A value loaded from .env is distinguished from an explicit OS env var.
4. The class default only applies when neither an env var nor .env defines DATABASE_URL.
5. An already-absolute sqlite:////... URL is left untouched (never re-anchored).
6. A non-sqlite URL (e.g. Postgres) is preserved verbatim.
7. Credentials are redacted before being logged.

These import only the pure functions from app.core.config (never app.main), so they
never open a database connection or trigger application startup.
"""
import os
from pathlib import Path

import pytest

from app.core.config import (
    database_url_source,
    resolve_relative_sqlite_url,
    redact_database_url,
    _BACKEND_ROOT,
    Settings,
)


@pytest.fixture(autouse=True)
def _clean_database_url_env(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    yield


def test_resolution_is_identical_from_backend_and_repo_root(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=sqlite:///./vspl_smes.db\n")

    class S(Settings.__bases__[0]):
        model_config = {"env_file": str(dotenv), "extra": "ignore"}
        DATABASE_URL: str = "sqlite:///./vspl_smes.db"

    anchor = tmp_path
    resolved_from_backend = resolve_relative_sqlite_url(S().DATABASE_URL, anchor)

    old_cwd = os.getcwd()
    try:
        monkeypatch.chdir(tmp_path.parent)
        resolved_from_parent = resolve_relative_sqlite_url(S().DATABASE_URL, anchor)
    finally:
        os.chdir(old_cwd)

    assert resolved_from_backend == resolved_from_parent
    assert resolved_from_backend == f"sqlite:///{(anchor / 'vspl_smes.db').resolve()}"


def test_explicit_env_var_takes_precedence_and_is_passed_through(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@dbhost/prod")

    class S(Settings.__bases__[0]):
        model_config = {"env_file": str(_BACKEND_ROOT / ".env"), "extra": "ignore"}
        DATABASE_URL: str = "sqlite:///./vspl_smes.db"

    s = S()
    assert s.DATABASE_URL == "postgresql://user:secret@dbhost/prod"
    assert database_url_source(s) == "explicit_env_var"


def test_dotenv_value_distinguished_from_explicit_env_var(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("DATABASE_URL=sqlite:///./from_dotenv.db\n")

    class S(Settings.__bases__[0]):
        model_config = {"env_file": str(dotenv), "extra": "ignore"}
        DATABASE_URL: str = "sqlite:///./vspl_smes.db"

    s = S()
    assert s.DATABASE_URL == "sqlite:///./from_dotenv.db"
    assert database_url_source(s) == "dotenv_file"


def test_class_default_only_when_neither_env_var_nor_dotenv_set(tmp_path):
    missing_dotenv = tmp_path / "does_not_exist" / ".env"

    class S(Settings.__bases__[0]):
        model_config = {"env_file": str(missing_dotenv), "extra": "ignore"}
        DATABASE_URL: str = "sqlite:///./vspl_smes.db"

    s = S()
    assert s.DATABASE_URL == "sqlite:///./vspl_smes.db"
    assert database_url_source(s) == "class_default"


def test_absolute_sqlite_url_is_never_reanchored():
    abs_url = "sqlite:////C:/some/absolute/path.db"
    assert resolve_relative_sqlite_url(abs_url, Path("/irrelevant/anchor")) == abs_url


def test_non_sqlite_url_is_preserved_verbatim():
    pg_url = "postgresql://user:pw@host:5432/dbname"
    assert resolve_relative_sqlite_url(pg_url, Path("/irrelevant/anchor")) == pg_url


def test_redact_strips_userinfo_from_url():
    assert redact_database_url("postgresql://user:secret@dbhost/prod") == "postgresql://***:***@dbhost/prod"
    # sqlite paths have no userinfo and must be unaffected
    sqlite_url = "sqlite:///C:/VSPL/VSPL smart/backend/vspl_smes.db"
    assert redact_database_url(sqlite_url) == sqlite_url
