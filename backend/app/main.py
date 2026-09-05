from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import engine, Base, SessionLocal, auto_migrate_schema
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
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