from typing import Optional, List, Any
from datetime import datetime, date
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Part Engineering Revision Master Schemas
# ---------------------------------------------------------------------------

class EngineeringRevisionCreate(BaseModel):
    part_id: str
    drawing_number: str = Field(..., max_length=100)
    drawing_revision: str = Field(..., max_length=50)
    drawing_url: Optional[str] = Field(None, max_length=1000)
    customer_spec_ref: Optional[str] = Field(None, max_length=200)
    process_sheet_number: Optional[str] = Field(None, max_length=100)
    pattern_number: Optional[str] = Field(None, max_length=100)
    tooling_id: Optional[str] = Field(None, max_length=100)
    is_active: bool = True


class EngineeringRevisionUpdate(BaseModel):
    drawing_number: Optional[str] = Field(None, max_length=100)
    drawing_revision: Optional[str] = Field(None, max_length=50)
    drawing_url: Optional[str] = Field(None, max_length=1000)
    customer_spec_ref: Optional[str] = Field(None, max_length=200)
    process_sheet_number: Optional[str] = Field(None, max_length=100)
    pattern_number: Optional[str] = Field(None, max_length=100)
    tooling_id: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None


class EngineeringRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    part_id: str
    part_number: Optional[str] = None
    drawing_number: str
    drawing_revision: str
    drawing_url: Optional[str] = None
    customer_spec_ref: Optional[str] = None
    process_sheet_number: Optional[str] = None
    pattern_number: Optional[str] = None
    tooling_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("id", "part_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: Any) -> str:
        return str(v) if v is not None else v


# ---------------------------------------------------------------------------
# Work Order Engineering Readiness Schemas
# ---------------------------------------------------------------------------

class WOReadinessItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    work_order_id: str
    wo_number: str
    oar_number: Optional[str] = None
    customer_code: str
    customer_name: str
    customer_po: str
    part_number: str
    part_name: Optional[str] = None
    grade: Optional[str] = None
    order_classification: str
    physical_wo_qty: int
    current_stage: str
    is_replacement: bool
    replacement_reason: Optional[str] = None

    # Readiness & Checklist Progress
    engineering_revision_id: Optional[str] = None
    verified_revision: Optional[str] = None
    drawing_available: bool
    drawing_revision_verified: bool
    customer_spec_verified: bool
    process_sheet_verified: bool
    pattern_ready: bool
    tooling_ready: bool
    checklist_passed_count: int
    checklist_total_count: int = 6
    is_checklist_complete: bool

    # Release status
    readiness_status: str  # PENDING | READY | RELEASED | BLOCKED
    engineering_released_by: Optional[str] = None
    engineering_released_at: Optional[datetime] = None
    remarks: Optional[str] = None
    created_at: datetime

    @field_validator("id", "work_order_id", "engineering_revision_id", mode="before")
    @classmethod
    def coerce_uuid_to_str(cls, v: Any) -> Optional[str]:
        return str(v) if v is not None else None


class WOReadinessDetailOut(WOReadinessItemOut):
    drawing_url: Optional[str] = None
    pattern_number: Optional[str] = None
    tooling_id: Optional[str] = None
    engineer_id: Optional[str] = None
    engineer_name: Optional[str] = None
    available_revisions: List[EngineeringRevisionOut] = []


class WOReadinessChecklistUpdate(BaseModel):
    engineering_revision_id: Optional[str] = None
    drawing_available: Optional[bool] = None
    drawing_revision_verified: Optional[bool] = None
    customer_spec_verified: Optional[bool] = None
    process_sheet_verified: Optional[bool] = None
    pattern_ready: Optional[bool] = None
    tooling_ready: Optional[bool] = None
    verified_revision: Optional[str] = Field(None, max_length=50)
    drawing_url: Optional[str] = Field(None, max_length=1000)
    pattern_number: Optional[str] = Field(None, max_length=100)
    tooling_id: Optional[str] = Field(None, max_length=100)
    remarks: Optional[str] = None


class EngineeringReleaseRequest(BaseModel):
    engineering_revision_id: Optional[str] = None
    verified_revision: Optional[str] = None
    drawing_url: Optional[str] = None
    pattern_number: Optional[str] = None
    tooling_id: Optional[str] = None
    remarks: Optional[str] = None
    replacement_reason_acknowledged: Optional[bool] = None


class EngineeringRevocationRequest(BaseModel):
    revocation_reason: str = Field(..., min_length=5, max_length=1000, description="Mandatory reason for revoking engineering release")


class EngineeringReleaseResponse(BaseModel):
    success: bool
    wo_number: str
    readiness_status: str
    engineering_released_by: str
    engineering_released_at: datetime
    engineering_document_revision: Optional[str] = None
    message: str
