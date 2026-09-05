from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.dashboard import DashboardStatsOut
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

@router.get("/stats", response_model=DashboardStatsOut)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve comprehensive live executive & operational manufacturing KPIs."""
    return DashboardService.get_dashboard_stats(db)
