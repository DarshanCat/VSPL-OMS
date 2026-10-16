from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User
from app.schemas.operations import (
    OrderIntakeCreate, OrderIntakeResponse,
    WOReleaseCreate, WOReleaseResponse,
    ConversionCreate, ConversionResponse,
    NCRecordCreate, NCRecordUpdate, NCRecordOut,
    ReleaseEvidenceCreate,
    EngineeringReleaseResponse, ManufacturingReleaseResponse,
    WorkOrderCreatePayload, WorkOrderCreateResponse,
    NextSequencesResponse, OARUpdate
)
from app.schemas.work_order import OARListItem, OARGenealogyResponse
from app.services.operations_service import OperationsService
from app.services.work_order_service import WorkOrderService
from app.core.roles import (
    PLANNING_ROLES, WO_RELEASE_ROLES, CONVERSION_MODULE_ROLES, QUALITY_APPROVAL_ROLES,
    ENGINEERING_RELEASE_ROLES, MANUFACTURING_RELEASE_ROLES
)

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])

@router.get("/next-sequences", response_model=NextSequencesResponse)
def get_next_sequences(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Retrieve the next suggested, collision-free OAR and WO sequence numbers."""
    return OperationsService.get_next_sequences(db)

@router.post("/intake", response_model=OrderIntakeResponse)
def create_order_intake(
    payload: OrderIntakeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Step 1: Sales / Planning Order Intake (OAR) creation. Creates an OAR
    linked to confirmed customer PO or schedule without creating WOs by default."""
    return OperationsService.create_order_intake(db, payload, current_user=user)

@router.post("/work-orders", response_model=WorkOrderCreateResponse)
def create_work_order(
    payload: WorkOrderCreatePayload,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Step 2: Planner generates Work Order(s) from a created OAR with custom date,
    quantity, and process route."""
    return OperationsService.create_work_order(db, payload, current_user=user)

@router.get("/oars", response_model=List[OARListItem])
def list_oars(
    search: Optional[str] = Query(None, description="Search by OAR, customer, part, or PO"),
    status_filter: Optional[str] = Query(None, description="Filter by OAR status (accept/hold/reject)"),
    customer_code: Optional[str] = Query(None, description="Filter by customer code"),
    classification: Optional[str] = Query(None, description="Filter by classification: 'Production' or 'NPD'"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Read-only OAR & WO roll-up list/search for order intake tracking. Not a new
    business engine -- every figure is read directly from existing Order/WorkOrder/
    StageWIP/ProductionUpdate/Dispatch records."""
    return WorkOrderService.list_oars(
        db,
        search=search,
        status_filter=status_filter,
        customer_code=customer_code,
        classification=classification,
        limit=limit,
        offset=offset
    )

@router.get("/oars/export/excel")
def export_oars_excel(
    classification: Optional[str] = Query(None, description="Filter by classification: 'Production' or 'NPD'"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Export all open OARs, Work Orders, Traceability Matrix, and Data Capture Specifications to Excel."""
    from app.services.excel_export_service import generate_excel_bytes
    excel_content = generate_excel_bytes(db, classification_filter=classification)
    filename = f"VSPL_Open_OAR_and_WO_Dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.get("/oars/{oar_number}/genealogy", response_model=OARGenealogyResponse)
def get_oar_genealogy(
    oar_number: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Authoritative OAR-level production genealogy across original and all patch/replacement WOs."""
    genealogy = WorkOrderService.get_oar_genealogy(db, oar_number)
    if not genealogy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"OAR '{oar_number}' not found."
        )
    return genealogy

@router.patch("/oars/{oar_number}", response_model=OARListItem)
def update_oar(
    oar_number: str,
    payload: OARUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PLANNING_ROLES))
):
    """Update OAR Commitment Date, Delivery Date, Status, or Remarks."""
    return OperationsService.update_oar(db, oar_number=oar_number, payload=payload, current_user=user)

@router.post("/wo/{wo_number}/engineering-release", response_model=EngineeringReleaseResponse)
def engineering_release(
    wo_number: str,
    payload: Optional[ReleaseEvidenceCreate] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*ENGINEERING_RELEASE_ROLES))
):
    """First step of the release chain: OAR -> WO Created -> Engineering Release ->
    Manufacturing Release -> WO Released -> Production."""
    return OperationsService.engineering_release(db, wo_number, payload=payload, current_user=user)

@router.post("/wo/{wo_number}/manufacturing-release", response_model=ManufacturingReleaseResponse)
def manufacturing_release(
    wo_number: str,
    payload: Optional[ReleaseEvidenceCreate] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANUFACTURING_RELEASE_ROLES))
):
    """Second step of the release chain -- requires Engineering Release to already be recorded."""
    return OperationsService.manufacturing_release(db, wo_number, payload=payload, current_user=user)

@router.post("/wo-release", response_model=WOReleaseResponse)
def release_work_order(
    payload: WOReleaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*WO_RELEASE_ROLES))
):
    """Release a Work Order with physical quantity and custom stage routing."""
    return OperationsService.release_work_order(db, payload, current_user=user)

@router.post("/conversion", response_model=ConversionResponse)
def create_conversion(
    payload: ConversionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*CONVERSION_MODULE_ROLES))
):
    """Execute part conversion between Work Orders with route debit validation."""
    return OperationsService.create_conversion(db, payload, current_user=user)

@router.get("/nc", response_model=List[NCRecordOut])
def get_nc_records(
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all QA Non-Conformance records."""
    return OperationsService.get_nc_records(db, limit=limit, offset=offset)

@router.post("/nc", response_model=NCRecordOut)
def create_nc_record(
    payload: NCRecordCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Log a new QA Non-Conformance defect report."""
    return OperationsService.create_nc(db, payload, current_user=user)

@router.put("/nc", response_model=NCRecordOut)
def update_nc_record(
    payload: NCRecordUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*QUALITY_APPROVAL_ROLES))
):
    """Update NC status, root cause, or disposition (quality-approval action)."""
    return OperationsService.update_nc(db, payload, current_user=user)
