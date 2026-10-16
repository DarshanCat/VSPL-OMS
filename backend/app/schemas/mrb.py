from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class MRBReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    mrb_number: str
    production_update_id: Optional[str] = None
    movement_id: Optional[str] = None
    work_order_id: str
    wo_number: str
    part_number: Optional[str] = None
    part_name: Optional[str] = None
    customer_name: Optional[str] = None
    stage: str
    machine_id: Optional[str] = None
    operator_name: Optional[str] = None
    shift: Optional[str] = None
    heat_number: Optional[str] = None

    reported_ok_qty: int
    reported_reject_qty: int
    reported_defect_code: Optional[str] = None
    floor_remarks: Optional[str] = None

    verified_ok_qty: Optional[int] = None
    verified_reject_qty: Optional[int] = None
    verified_defect_code: Optional[str] = None

    status: str  # PENDING, APPROVED, ADJUSTED, REJECTED
    disposition: Optional[str] = None  # PENDING, SCRAP, REWORK, CONCESSION, RETURN_TO_SUPPLIER, RECLASSIFY_OK, VERIFIED_OK

    reviewed_by_id: Optional[str] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class MRBReviewDecisionRequest(BaseModel):
    action: str = Field(..., description="Decision action: 'APPROVE', 'ADJUST', or 'REJECT'")
    verified_ok_qty: Optional[int] = Field(None, ge=0, description="Verified OK quantity (required for ADJUST)")
    verified_reject_qty: Optional[int] = Field(None, ge=0, description="Verified rejection quantity (required for ADJUST)")
    verified_defect_code: Optional[str] = Field(None, max_length=100, description="Verified defect classification")
    disposition: Optional[str] = Field("SCRAP", description="Disposition: SCRAP, REWORK, CONCESSION, RETURN_TO_SUPPLIER, RECLASSIFY_OK, VERIFIED_OK")
    review_notes: Optional[str] = Field(None, max_length=2000, description="Quality / Planner review comments")


class MRBListResponse(BaseModel):
    total_count: int
    pending_count: int
    approved_count: int
    adjusted_count: int
    rejected_count: int
    items: List[MRBReviewItem]


class MRBDecisionResponse(BaseModel):
    success: bool
    message: str
    item: MRBReviewItem
