from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

@router.get("/export/wip-csv")
def export_wip_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download current WIP matrix as CSV."""
    csv_content = ReportService.generate_wip_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vspl_smes_wip_report.csv"}
    )

@router.get("/export/movements-csv")
def export_movements_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download full movement history ledger as CSV."""
    csv_content = ReportService.generate_movements_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vspl_smes_movement_ledger.csv"}
    )

@router.get("/export/dispatch-csv")
def export_dispatch_csv(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download dispatch transaction history as CSV."""
    csv_content = ReportService.generate_dispatch_csv(db)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vspl_smes_dispatch_report.csv"}
    )
