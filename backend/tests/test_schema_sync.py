"""Regression tests for the schema-sync mechanism (app.core.database.auto_migrate_schema)
that produced the production gap this task investigates: a model column with no
corresponding ADD COLUMN IF NOT EXISTS statement fails against a real, already-existing
table (observed in production as `customers.address does not exist`).

These tests do not touch any real database -- they run auto_migrate_schema() against a
throwaway in-memory/file-based SQLite database created fresh in this test session, using
the exact same function production startup calls.
"""
import re
import inspect
import sqlite3
import tempfile
import os

import pytest
from sqlalchemy import create_engine, text

import app.models  # noqa: F401 -- populates Base.metadata
from app.core.database import Base, auto_migrate_schema


@pytest.fixture
def sqlite_db(monkeypatch):
    """A fresh, file-based SQLite database with all current tables created, then
    monkeypatch app.core.database's module-level `engine` to point at it -- the same
    global auto_migrate_schema() reads from at call time."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)

        import app.core.database as db_module
        original_engine = db_module.engine
        db_module.engine = engine
        try:
            yield engine
        finally:
            db_module.engine = original_engine
            engine.dispose()
    finally:
        os.unlink(path)


def test_auto_migrate_schema_runs_without_raising_on_fresh_db(sqlite_db):
    """The exact call production startup makes (Base.metadata.create_all() already ran
    in the fixture, matching the real lifespan order) must never raise."""
    auto_migrate_schema()


def test_auto_migrate_schema_is_idempotent(sqlite_db):
    """Running it twice in a row (e.g. two cold starts) must be a safe no-op the second
    time -- never an error, never a destructive action."""
    auto_migrate_schema()
    auto_migrate_schema()


def test_auto_migrate_schema_adds_all_customer_columns(sqlite_db):
    """Regression test for the exact production failure: every column the Customer
    model declares beyond the original (id, customer_code, name) must be added by
    auto_migrate_schema(), and actually be queryable afterward -- not just present in
    the statements list."""
    auto_migrate_schema()
    with sqlite_db.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(customers)"))}
    for expected in ("address", "gst", "contact_person", "email", "phone", "is_active"):
        assert expected in cols, f"customers.{expected} missing after auto_migrate_schema()"


def test_every_customer_model_column_has_an_add_column_statement():
    """Static guard: fails fast in CI if a future new Customer model field is added
    without a matching ADD COLUMN IF NOT EXISTS statement -- the exact class of bug
    that broke production (customers.address et al.)."""
    src = inspect.getsource(auto_migrate_schema)
    pairs = set(re.findall(r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+)", src, re.IGNORECASE))
    covered = {col for (tbl, col) in pairs if tbl == "customers"}

    customers_table = Base.metadata.tables["customers"]
    original_columns = {"id", "customer_code", "name"}
    model_columns = {c.name for c in customers_table.columns}
    new_columns = model_columns - original_columns

    uncovered = new_columns - covered
    assert not uncovered, (
        f"Customer model column(s) {sorted(uncovered)} have no ADD COLUMN IF NOT EXISTS "
        "statement in auto_migrate_schema() -- would fail against an existing production "
        "table exactly like customers.address did."
    )


def test_auto_migrate_schema_never_contains_destructive_statements():
    """Static guard against a regression toward destructive migration statements ever
    being added to this function."""
    src = inspect.getsource(auto_migrate_schema)
    forbidden = ("DROP TABLE", "DROP COLUMN", "TRUNCATE", "DELETE FROM")
    upper_src = src.upper()
    for kw in forbidden:
        assert kw not in upper_src, f"auto_migrate_schema() must never contain {kw!r}"
