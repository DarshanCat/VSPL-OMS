"""Rejection Type master. `code` is the stable natural key selected by Production
Entry (validated against this table -- never accepted as arbitrary free text once
the master has been configured). Never physically delete a row that may be
referenced by historical NCRecord.defect_code values; deactivate it instead."""
import uuid
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class RejectionType(Base):
    __tablename__ = "rejection_types"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    code = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
