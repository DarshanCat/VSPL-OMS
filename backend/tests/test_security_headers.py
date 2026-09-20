"""Security-header regression tests (security remediation phase 2)."""
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app


def test_api_response_carries_baseline_security_headers():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        # Never sent outside of ENVIRONMENT=production (this test runs with the
        # default/dev settings).
        assert "strict-transport-security" not in resp.headers


def test_docs_endpoint_is_not_broken_by_csp():
    """FastAPI's Swagger UI loads its assets from a CDN with inline scripts; a strict
    CSP there would break it, so CSP must be skipped for the docs paths specifically
    (the other, harmless headers still apply)."""
    with TestClient(app) as client:
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "content-security-policy" not in resp.headers
        assert resp.headers["x-content-type-options"] == "nosniff"


def test_cors_rejects_unlisted_origin_and_allows_configured_origin():
    limiter.reset()
    with TestClient(app) as client:
        # Configured origin (see backend/app/core/config.py default CORS_ORIGINS)
        resp = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

        # Arbitrary, unlisted origin
        resp2 = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in resp2.headers
    limiter.reset()
