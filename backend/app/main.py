import math
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.config import settings
from app.core.database import engine, Base, SessionLocal, auto_migrate_schema
from app.core.rate_limit import limiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.api.v1 import (
    auth, oms, production, work_orders, packing,
    dispatch, operations, dashboard, reports, ai, admin, analytics
)
from app.services.seed_service import seed_database_if_empty

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Ensure tables exist, apply column migrations, then seed initial data
    Base.metadata.create_all(bind=engine)
    auto_migrate_schema()
    db = SessionLocal()
    try:
        seed_database_if_empty(db)
    finally:
        db.close()
    yield

app = FastAPI(
    title="VSPL Smart Manufacturing Execution System (SMES) API",
    version="1.0.0",
    description="AI Powered Production Tracking, Planning & Manufacturing Intelligence for Vijay Spheroidals Pvt Ltd",
    lifespan=lifespan
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again later."})


def _json_safe(obj):
    """Recursively replace non-finite floats (NaN/Infinity/-Infinity) -- which
    Pydantic correctly rejects but Python's spec-compliant JSON encoder cannot
    serialize -- with their string form, so echoing a rejected value back to the
    client in a validation-error body can never itself crash the response."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


@app.exception_handler(RequestValidationError)
def validation_exception_handler(request: Request, exc: RequestValidationError):
    # FastAPI's default handler echoes the rejected input verbatim, which crashes with
    # an unhandled ValueError when that input is a non-finite float (e.g. a client
    # sending "quantity_moved": NaN) -- Pydantic already correctly rejects it with a
    # "finite_number" error; this only makes *reporting* that rejection crash-proof.
    return JSONResponse(status_code=422, content={"detail": _json_safe(exc.errors())})


app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register All API Routers
app.include_router(auth.router)
app.include_router(oms.router)
app.include_router(production.router)
app.include_router(work_orders.router)
app.include_router(packing.router)
app.include_router(dispatch.router)
app.include_router(operations.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(ai.router)
app.include_router(admin.router)
app.include_router(analytics.router)

@app.get("/health")
def health():
    return {
        "status": "online",
        "system": "VSPL Smart Manufacturing Execution System (SMES)",
        "oms_engine": "v3.3 connected"
    }