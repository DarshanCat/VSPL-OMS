"""Vercel deployment entrypoint ONLY -- not a second application.

Three different Vercel Services routing mechanisms (rewrites.transforms,
destination.path, and experimentalServices.mount) were each tried and confirmed --
against the live production deployment, not assumption -- to either have no effect or
be outright rejected by Vercel at deploy time. None of them stripped the /api/backend
prefix before the request reached FastAPI.

This sidesteps the problem entirely by doing the prefix-stripping inside FastAPI
itself, via Starlette's own well-established app.mount(), instead of depending on any
Vercel routing feature. The real, complete, totally unmodified application
(app.main:app) is mounted under /api/backend -- every existing route, every existing
piece of business logic, auth, and RBAC is untouched; this file adds nothing to them.

vercel.json's backend service entrypoint points here instead of app.main:app.
Local development, uvicorn, and every existing test are unaffected -- they all still
use app.main:app directly.

IMPORTANT -- lifespan forwarding (fixes a real, confirmed production bug):
Starlette's ASGI server only ever sends the `lifespan` protocol scope to the
OUTERMOST app it was given -- here, this wrapper. Mounting real_app under
/api/backend with app.mount() does NOT cascade lifespan startup/shutdown events into
the mounted sub-application; only http/websocket scopes get dispatched to it. Since
this wrapper was previously a bare `FastAPI()` with no lifespan of its own,
real_app's lifespan (Base.metadata.create_all() + auto_migrate_schema(), in
app/main.py) never ran in production, no matter how many times it was deployed --
confirmed empirically via TestClient against both apps (see
backend/tests/test_vercel_lifespan.py), not assumed. Passing real_app's own lifespan
context through to this wrapper is the fix: identical startup behavior, still
running the exact same unmodified app.main.lifespan function, just actually invoked.
"""
from fastapi import FastAPI
from app.main import app as real_app

app = FastAPI(lifespan=real_app.router.lifespan_context)
app.mount("/api/backend", real_app)
