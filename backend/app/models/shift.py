"""Shift master. `shift_code` is the stable natural key referenced as free-text
`shift` on ProductionUpdate/ProductionMovement -- never physically delete a row that
may be referenced by historical transactions; deactivate it instead."""
import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    shift_code = Column(String, unique=True, nullable=False, index=True)
    shift_name = Column(String, nullable=False)
    start_time = Column(String, nullable=True)  # "HH:MM" -- no timezone/date context needed
    end_time = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
