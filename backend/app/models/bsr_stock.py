import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


class BSRStock(Base):
    """Finished Goods Stock held in BSR (Buyer Stock Reconciliation / Buffer Stock)
    ready to satisfy existing or future customer Purchase Orders."""
    __tablename__ = "bsr_stock"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=False, index=True)
    available_qty = Column(Integer, default=0, nullable=False)
    allocated_qty = Column(Integer, default=0, nullable=False)
    source_wo_id = Column(GUID, ForeignKey("work_orders.id"), nullable=True)
    heat_number = Column(String(100), nullable=True)
    remarks = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    part = relationship("Part")
    source_wo = relationship("WorkOrder")
