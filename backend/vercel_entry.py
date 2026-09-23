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
"""
from fastapi import FastAPI
from app.main import app as real_app

app = FastAPI()
app.mount("/api/backend", real_app)
