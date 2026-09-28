from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class CustomerMappingBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_id: str
    customer_code: str
    customer_name: str
    customer_part_no: str
    source: Optional[str] = None
    is_active: bool = True


class PartMasterItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    part_number: str
    description: Optional[str] = None
    grade: Optional[str] = None
    is_active: bool = True
    customer_count: int = 0
    mapping_count: int = 0
    customer_mappings: List[CustomerMappingBrief] = []


class PartMasterStats(BaseModel):
    total_parts: int
    mapped_parts: int
    unmapped_parts: int
    total_mappings: int
    total_customers: int


class PartMasterListResponse(BaseModel):
    items: List[PartMasterItemOut]
    total: int
    limit: int
    offset: int
    stats: Optional[PartMasterStats] = None


class PartCreate(BaseModel):
    part_number: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    grade: Optional[str] = Field(None, max_length=100)


class PartUpdate(BaseModel):
    description: Optional[str] = Field(None, max_length=500)
    grade: Optional[str] = Field(None, max_length=100)
