"""Read-only Roles & Responsibilities reference. Purely informational -- actual
authorization is, and remains, backend RBAC (the tuples in `app.core.roles`, enforced
via `require_roles`/service-layer `_require_role` on every other router). This
endpoint never grants or checks permissions itself; it only describes the permission
tiers that already exist elsewhere in the codebase, so the descriptions here must be
kept in sync with `app.core.roles` if those tuples ever change."""
from typing import List
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/roles", tags=["roles"])


class RoleInfo(BaseModel):
    role: str
    display_name: str
    department: str
    permissions: List[str]
    allowed_modules: List[str]


_ROLES: List[RoleInfo] = [
    RoleInfo(
        role="admin", display_name="SUPER_ADMIN", department="Administration",
        permissions=["Full administration", "User management", "Master data admin", "Override any release step"],
        allowed_modules=["Everything"],
    ),
    RoleInfo(
        role="planner", display_name="PLANNER", department="Planning",
        permissions=["Order Intake (OAR)", "WO Release", "Conversion Module", "Master data (Customer/PO/Schedule/Machine/Shift/Operator)"],
        allowed_modules=["Operations", "Masters", "Reports"],
    ),
    RoleInfo(
        role="engineering", display_name="ENGINEERING", department="Engineering",
        permissions=["Engineering Release"],
        allowed_modules=["Operations (release chain)"],
    ),
    RoleInfo(
        role="manufacturing", display_name="MANUFACTURING", department="Manufacturing",
        permissions=["Manufacturing Release"],
        allowed_modules=["Operations (release chain)"],
    ),
    RoleInfo(
        role="production_manager", display_name="PRODUCTION_MANAGER", department="Production",
        permissions=["Production entry", "Material movement", "WO Release", "Production monitoring"],
        allowed_modules=["Production", "WIP", "Tracking", "Reports"],
    ),
    RoleInfo(
        role="store", display_name="STORE", department="Store",
        permissions=["Authorized material movement", "Melting-entry execution"],
        allowed_modules=["Production (move)", "Rejection Tracking (melting entry)"],
    ),
    RoleInfo(
        role="qa", display_name="QUALITY", department="Quality",
        permissions=["Rejection Tracking disposition approval", "Replacement WO approval", "Quality oversight"],
        allowed_modules=["Rejection Tracking", "Operations (NC)"],
    ),
    RoleInfo(
        role="dispatch", display_name="DISPATCH", department="Dispatch",
        permissions=["Packing / BSR", "Dispatch execution", "Invoice handling"],
        allowed_modules=["Packing", "Dispatch"],
    ),
    RoleInfo(
        role="ceo", display_name="CEO", department="Executive",
        permissions=["Read-only management visibility", "Quality oversight (read-only)"],
        allowed_modules=["Dashboard", "Reports", "Reconciliation"],
    ),
    RoleInfo(
        role="data_analyst", display_name="DATA_ANALYST", department="Analytics",
        permissions=["Read-only reports, analytics, and tracking"],
        allowed_modules=["Reports", "Analytics", "Dashboard"],
    ),
]


@router.get("", response_model=List[RoleInfo])
def list_roles(user: User = Depends(get_current_user)):
    """Informational only. Actual authorization stays entirely in backend RBAC
    (app.core.roles + require_roles) on every other endpoint -- this page changes
    nothing."""
    return _ROLES
