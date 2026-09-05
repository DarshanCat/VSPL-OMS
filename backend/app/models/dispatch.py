import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class Dispatch(Base):
    __tablename__ = "dispatches"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    customer_po = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True, index=True)
    dispatched_qty = Column(Integer, nullable=False)
    dispatch_date = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)

    work_order = relationship("WorkOrder", back_populates="dispatches")
    dispatcher = relationship("User", foreign_keys=[created_by])
