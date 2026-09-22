import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class Conversion(Base):
    __tablename__ = "conversions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    conversion_wo_number = Column(String, nullable=True)
    source_wo_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    destination_order_id = Column(GUID, ForeignKey("orders.id"), nullable=False)
    conversion_wo_id = Column(GUID, ForeignKey("work_orders.id"), nullable=True)
    entry_stage = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(String, nullable=True)
    planner = Column(String, nullable=True)
    # Set only when this conversion originated from a Rejection Tracking disposition
    # decision (CONVERT_PART / SAME_PART / CWO) rather than a direct mid-route WIP
    # conversion. Null for every pre-existing conversion, which remain unaffected.
    nc_record_id = Column(GUID, ForeignKey("nc_records.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source_wo = relationship("WorkOrder", foreign_keys=[source_wo_id])
    destination_order = relationship("Order", foreign_keys=[destination_order_id])
    conversion_wo = relationship("WorkOrder", foreign_keys=[conversion_wo_id])
    nc_record = relationship("NCRecord", foreign_keys=[nc_record_id])
