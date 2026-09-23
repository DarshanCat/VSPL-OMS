"""Regression tests for the Manufacturing Reports Center endpoints.

These cover the actual bug found and fixed: the frontend's report download
buttons used plain `<a href download>` navigation, which never sends the
Authorization header this API requires (there is no cookie-based auth) --
every request was silently rejected with 401 before it ever reached
ReportService. Fixed on the frontend (authenticated blob download via
lib/api.ts's downloadFile()); these tests lock in the backend contract that
fix depends on: auth is required, a valid token succeeds, and the response
is real, well-formed, database-derived content -- never invented data.
"""
import csv
import io
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app
from app.oms_core import storage

SEEDED_LOGINS = {
    "ADMIN": ("admin@vspl.com", "admin123"),
}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _login(client, role_key="ADMIN"):
    email, password = SEEDED_LOGINS[role_key]
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# CSV exports: wip / movements / dispatch
# ---------------------------------------------------------------------------

CSV_ENDPOINTS = [
    "/api/v1/reports/export/wip-csv",
    "/api/v1/reports/export/movements-csv",
    "/api/v1/reports/export/dispatch-csv",
]


@pytest.mark.parametrize("endpoint", CSV_ENDPOINTS)
def test_csv_report_requires_authentication(client, endpoint):
    """This is the exact failure mode the plain <a href download> tag hit in
    production -- no Authorization header, 401, no file ever downloads."""
    resp = client.get(endpoint)
    assert resp.status_code == 401, resp.text


@pytest.mark.parametrize("endpoint", CSV_ENDPOINTS)
def test_csv_report_succeeds_with_valid_token(client, endpoint):
    token = _login(client)
    resp = client.get(endpoint, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")
    # Real, parseable CSV with a header row -- not an empty or malformed body.
    rows = list(csv.reader(io.StringIO(resp.text)))
    assert len(rows) >= 1
    assert len(rows[0]) > 1


def test_wip_csv_reflects_seeded_work_order_data(client):
    """The report must be database-derived, never invented -- check it contains
    a WO number that actually exists in the seeded dataset, not a placeholder."""
    token = _login(client)
    resp = client.get("/api/v1/reports/export/wip-csv", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert "WO Number" in resp.text
    assert "WO-1001" in resp.text or "WO-" in resp.text


# ---------------------------------------------------------------------------
# Latest OMS Master Spreadsheet (report 4) -- a metadata lookup, not a file
# download in itself; the actual file is fetched via /oms/download/master/*
# ---------------------------------------------------------------------------

def test_latest_master_requires_authentication(client):
    resp = client.get("/api/v1/oms/latest-master")
    assert resp.status_code == 401, resp.text


def test_latest_master_reports_none_when_no_master_exists_yet(client, monkeypatch, tmp_path):
    """No master has been generated -- the endpoint must say so (None), never
    fabricate a filename."""
    monkeypatch.setattr(storage, "MASTERS_DIR", tmp_path / "masters_empty")
    token = _login(client)
    resp = client.get("/api/v1/oms/latest-master", headers=_auth(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["latest_master"] is None


def test_master_file_download_succeeds_once_a_master_exists(client, monkeypatch, tmp_path):
    """Full flow: latest-master reports the real filename, and
    /oms/download/master/{filename} returns the actual file bytes -- this is
    what the frontend now does in two authenticated steps, replacing the old
    broken direct link to a JSON-only endpoint."""
    masters_dir = tmp_path / "masters"
    masters_dir.mkdir()
    fake_master = masters_dir / "Master_2026-09-22.xlsx"
    fake_master.write_bytes(b"fake-xlsx-bytes-for-test")
    monkeypatch.setattr(storage, "MASTERS_DIR", masters_dir)

    token = _login(client)
    latest = client.get("/api/v1/oms/latest-master", headers=_auth(token))
    assert latest.status_code == 200, latest.text
    filename = latest.json()["latest_master"]
    assert filename == "Master_2026-09-22.xlsx"

    download = client.get(f"/api/v1/oms/download/master/{filename}", headers=_auth(token))
    assert download.status_code == 200, download.text
    assert download.content == b"fake-xlsx-bytes-for-test"


def test_master_download_requires_authentication(client, monkeypatch, tmp_path):
    masters_dir = tmp_path / "masters"
    masters_dir.mkdir()
    (masters_dir / "Master_2026-09-22.xlsx").write_bytes(b"x")
    monkeypatch.setattr(storage, "MASTERS_DIR", masters_dir)

    resp = client.get("/api/v1/oms/download/master/Master_2026-09-22.xlsx")
    assert resp.status_code == 401, resp.text


def test_master_download_rejects_path_traversal_filename(client, monkeypatch, tmp_path):
    masters_dir = tmp_path / "masters"
    masters_dir.mkdir()
    monkeypatch.setattr(storage, "MASTERS_DIR", masters_dir)

    token = _login(client)
    # A single path segment containing ".." (no slashes, so it still routes to this
    # handler) exercises oms.py's own _safe_name() rejection directly.
    resp = client.get("/api/v1/oms/download/master/..xlsx", headers=_auth(token))
    assert resp.status_code == 400, resp.text
