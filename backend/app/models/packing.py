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


class PackingTransaction(Base):
    """Immutable ledger of every individual packing/BSR transaction posted for a Work Order."""
    __tablename__ = "packing_transactions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    client_request_id = Column(String, unique=True, nullable=True, index=True)
    # Assigned once, at creation of this packing transaction -- unique and immutable
    # for its lifetime. Never regenerated or reassigned.
    packing_unit_code = Column(String, unique=True, nullable=True, index=True)
    packed_quantity = Column(Integer, nullable=False)
    box_count = Column(Integer, nullable=True)
    package_type = Column(String, nullable=True)
    remarks = Column(String, nullable=True)
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    work_order = relationship("WorkOrder")
