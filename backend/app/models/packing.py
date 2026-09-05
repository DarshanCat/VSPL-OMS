import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class PackingRecord(Base):
    """Tracks physical parts between Final Inspection (FI), Packing/BSR, and Dispatch."""
    __tablename__ = "packing_records"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    
    fi_approved_qty = Column(Integer, default=0)
    available_for_packing = Column(Integer, default=0)
    received_qty = Column(Integer, default=0)
    packed_qty = Column(Integer, default=0)
    pending_qty = Column(Integer, default=0)
    ready_for_dispatch_qty = Column(Integer, default=0)
    dispatched_qty = Column(Integer, default=0)
    
    status = Column(String, default="Pending")  # "Pending", "In-Packing", "Ready-for-Dispatch", "Fully-Dispatched"
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder", back_populates="packing_records")
