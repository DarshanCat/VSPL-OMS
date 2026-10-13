import uuid
from sqlalchemy import Column, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class OMSException(Base):
    """Stores exception records encountered during OMS ingestion / linking workflows."""
    __tablename__ = "oms_exceptions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    exception_type = Column(String, nullable=False)
    detail = Column(String, nullable=False)
    wo_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
