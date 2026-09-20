from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from app.core.config import settings

# FastAPI's built-in interactive docs (Swagger UI / ReDoc) load their JS/CSS from a
# CDN and rely on inline scripts to boot -- a strict Content-Security-Policy on these
# paths would break the docs UI, so CSP is skipped there. The other headers below are
# harmless for the docs UI and still applied everywhere.
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # This backend is a JSON API with no legitimate reason to ever be framed.
        response.headers["X-Frame-Options"] = "DENY"

        if not request.url.path.startswith(_DOCS_PATHS):
            # This API never serves renderable HTML/scripts itself; a fully locked-down
            # policy is safe here and does not affect JSON responses.
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"

        # Only sent when HTTPS is guaranteed in front of this app (this app never
        # terminates TLS itself -- see docs/PRODUCTION_DEPLOYMENT.md). Gated on
        # ENVIRONMENT=production so local HTTP development is never affected.
        if settings.ENVIRONMENT.lower() == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
