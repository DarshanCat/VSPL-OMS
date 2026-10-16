import uuid
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class Dispatch(Base):
    __tablename__ = "dispatches"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    client_request_id = Column(String, unique=True, nullable=True, index=True)
    customer_po = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True, index=True)
    dispatched_qty = Column(Integer, nullable=False)
    dispatch_date = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(GUID, ForeignKey("users.id"), nullable=True)

    # Invoice Commercial Value & Payment Tracking
    unit_price = Column(Float, nullable=False, default=0.0)  # per piece rate
    total_invoice_value = Column(Float, nullable=False, default=0.0)  # dispatched_qty * unit_price
    payment_status = Column(String(50), nullable=False, default="UNPAID", index=True)  # UNPAID, PAID, PARTIALLY_PAID, OVERDUE
    paid_amount = Column(Float, nullable=False, default=0.0)
    payment_date = Column(DateTime(timezone=True), nullable=True)
    payment_reference = Column(String(200), nullable=True)  # UTR, Cheque No, Transaction ID
    payment_remarks = Column(String(1000), nullable=True)

    work_order = relationship("WorkOrder", back_populates="dispatches")
    dispatcher = relationship("User", foreign_keys=[created_by])
