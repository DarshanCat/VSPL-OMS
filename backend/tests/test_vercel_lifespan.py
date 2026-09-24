"""Regression test for the confirmed production bug: app.main's FastAPI lifespan
(Base.metadata.create_all() + auto_migrate_schema()) never ran in production because
vercel_entry.py -- the actual ASGI entrypoint Vercel invokes, per vercel.json's
`"entrypoint": "vercel_entry:app"` -- mounted app.main:app as a sub-application
without forwarding lifespan. Starlette only sends the ASGI `lifespan` protocol scope
to the outermost app; app.mount() does not cascade it into the mounted sub-app. This
was verified empirically (not assumed) before the fix: wrapping vercel_entry.app in a
TestClient triggered zero auto_migrate_schema() calls, while wrapping app.main:app
directly triggered exactly one.

This test asserts the fixed behavior and is the guard against this exact class of
regression recurring (e.g. if vercel_entry.py's `lifespan=` wiring is ever removed).
"""
from starlette.testclient import TestClient

import app.core.database as db_module
import app.main as main_module


def test_real_app_lifespan_runs_directly(monkeypatch):
    """Baseline: app.main:app's own lifespan runs when it is itself the outermost
    ASGI app (this is how every existing test and local uvicorn already use it)."""
    calls = []
    monkeypatch.setattr(db_module, "auto_migrate_schema", lambda: calls.append(1))
    monkeypatch.setattr(main_module, "auto_migrate_schema", lambda: calls.append(1))

    with TestClient(main_module.app):
        pass

    assert len(calls) == 1


def test_vercel_entry_forwards_lifespan_to_mounted_app(monkeypatch):
    """The actual regression guard: vercel_entry.app (what Vercel really invokes) must
    trigger app.main's lifespan -- and therefore auto_migrate_schema() -- even though
    app.main:app is only mounted as a sub-application, not the outermost app."""
    calls = []
    monkeypatch.setattr(db_module, "auto_migrate_schema", lambda: calls.append(1))
    monkeypatch.setattr(main_module, "auto_migrate_schema", lambda: calls.append(1))

    import importlib
    import vercel_entry
    importlib.reload(vercel_entry)  # rebuild the wrapper against the patched app.main

    with TestClient(vercel_entry.app):
        pass

    assert len(calls) == 1, (
        "vercel_entry.app's lifespan did not reach app.main's lifespan -- this is "
        "the exact bug that left auto_migrate_schema() (and Base.metadata.create_all()) "
        "never running in production."
    )


def test_vercel_entry_still_routes_requests_to_mounted_app():
    """The lifespan fix must not change request routing -- /api/backend/<path> must
    still reach app.main's real routes, unmodified."""
    import vercel_entry

    with TestClient(vercel_entry.app) as client:
        resp = client.get("/api/backend/docs")
        assert resp.status_code == 200
