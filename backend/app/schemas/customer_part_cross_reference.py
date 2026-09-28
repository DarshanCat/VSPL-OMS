from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class CustomerPartCrossReferenceBase(BaseModel):
    customer_part_no: str
    source: Optional[str] = None
    is_active: bool = True


class CustomerPartCrossReferenceCreate(BaseModel):
    customer_id: Optional[UUID] = None
    customer_code: Optional[str] = None
    customer_part_no: str
    part_id: Optional[UUID] = None
    internal_part_code: Optional[str] = None
    source: Optional[str] = None
    is_active: bool = True


class CustomerPartCrossReferenceUpdate(BaseModel):
    part_id: Optional[UUID] = None
    internal_part_code: Optional[str] = None
    source: Optional[str] = None
    is_active: Optional[bool] = None


class CustomerPartCrossReferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    customer_code: str
    customer_name: str
    customer_part_no: str
    part_id: UUID
    internal_part_code: str
    part_description: Optional[str] = None
    part_grade: Optional[str] = None
    source: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by_name: Optional[str] = None


class PartLookupResponse(BaseModel):
    customer_code: str
    customer_name: Optional[str] = None
    customer_part_no: str
    part_id: Optional[UUID] = None
    part_number: Optional[str] = None
    grade: Optional[str] = None
    description: Optional[str] = None
    is_matched: bool = False
    match_type: str = "none"  # "cross_reference" | "direct_internal" | "ambiguous" | "none"
    candidate_parts: List[str] = []
    message: Optional[str] = None
