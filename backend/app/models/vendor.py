import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class VendorDispatch(Base):
    """Tracks Work Order material dispatched to outside subcontracting vendors (e.g. from F2)
    and inward reception directly into Final Inspection (FI)."""
    __tablename__ = "vendor_dispatches"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, index=True)
    dispatch_stage = Column(String(50), default="F2", nullable=False)
    vendor_name = Column(String(200), nullable=False, index=True)
    dc_number = Column(String(100), nullable=False, index=True)
    dispatched_qty = Column(Integer, nullable=False)
    received_qty = Column(Integer, default=0, nullable=False)
    scrap_qty = Column(Integer, default=0, nullable=False)
    
    # Status: AT_VENDOR, PARTIALLY_RECEIVED, RECEIVED
    status = Column(String(50), default="AT_VENDOR", nullable=False, index=True)
    
    dispatched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=True)
    inward_dc_number = Column(String(100), nullable=True)
    remarks = Column(String, nullable=True)
    
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder")
