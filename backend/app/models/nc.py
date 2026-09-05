import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class NCRecord(Base):
    __tablename__ = "nc_records"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    nc_number = Column(String, unique=True, nullable=False, index=True)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    stage = Column(String, nullable=True)
    defect_code = Column(String, nullable=True)
    qty = Column(Integer, nullable=False)
    root_cause = Column(String, nullable=True)
    disposition = Column(String, nullable=True)
    responsibility = Column(String, nullable=True)
    status = Column(String, default="Open")  # "Open", "Closed"
    date_raised = Column(DateTime(timezone=True), server_default=func.now())
    date_closed = Column(DateTime(timezone=True), nullable=True)
    remarks = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    work_order = relationship("WorkOrder", back_populates="nc_records")
