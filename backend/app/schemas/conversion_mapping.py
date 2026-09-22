from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

class ConversionMappingCreate(BaseModel):
    source_part_number: str = Field(..., max_length=100)
    destination_part_number: str = Field(..., max_length=100)
    conversion_type: str = Field(..., description="PART_TO_PART | SAME_PART")
    conversion_factor: Optional[float] = Field(None, gt=0)
    is_active: bool = True

class ConversionMappingUpdate(BaseModel):
    id: str
    is_active: Optional[bool] = None
    conversion_factor: Optional[float] = Field(None, gt=0)

class ConversionMappingOut(BaseModel):
    id: str
    source_part_number: str
    destination_part_number: str
    conversion_type: str
    conversion_factor: Optional[float] = None
    is_active: bool
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_by_name: Optional[str] = None
    updated_at: Optional[datetime] = None
