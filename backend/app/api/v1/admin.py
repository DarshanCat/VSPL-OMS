from typing import List
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.order import Customer, Part
from app.models.audit import AuditLog

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

class CustomerOut(BaseModel):
    id: str
    customer_code: str
    name: str
    class Config:
        from_attributes = True

class PartOut(BaseModel):
    id: str
    part_number: str
    grade: str
    description: str
    class Config:
        from_attributes = True

class MachineOut(BaseModel):
    machine_id: str
    name: str
    stage: str
    status: str

class AuditLogOut(BaseModel):
    id: str
    user_name: str
    action: str
    entity: str
    entity_id: str
    old_value: str
    new_value: str
    details: str
    created_at: str

@router.get("/customers", response_model=List[CustomerOut])
def list_customers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Customer).order_by(Customer.customer_code).all()

@router.get("/parts", response_model=List[PartOut])
def list_parts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Part).order_by(Part.part_number).all()

@router.get("/machines", response_model=List[MachineOut])
def list_machines(user: User = Depends(get_current_user)):
    return [
        MachineOut(machine_id="M-CC01", name="Centrifugal Casting 1", stage="F1", status="Running"),
        MachineOut(machine_id="M-CC02", name="Centrifugal Casting 2", stage="F1", status="Running"),
        MachineOut(machine_id="M-LATHE-01", name="CNC Heavy Lathe 01", stage="F2", status="Running"),
        MachineOut(machine_id="M-LATHE-02", name="CNC Precision Lathe 02", stage="F2", status="Idle"),
        MachineOut(machine_id="M-VMC-01", name="Vertical Machining Center", stage="F3", status="Running"),
        MachineOut(machine_id="M-INSPECT-01", name="CMM Final Inspection Bay", stage="FI", status="Running"),
        MachineOut(machine_id="M-PACK-01", name="Automatic Banding & Packing", stage="PACKING", status="Running"),
    ]

@router.get("/audit-logs")
def list_audit_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.QA, UserRole.CEO)),
):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(l.id),
            "user_name": l.user_name or "System",
            "action": l.action,
            "entity": l.entity,
            "entity_id": l.entity_id or "",
            "old_value": l.old_value or "",
            "new_value": l.new_value or "",
            "details": l.details or "",
            "created_at": l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else ""
        }
        for l in logs
    ]
