import uuid
import re
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID


def next_return_number(db) -> str:
    """Generate collision-free sequential return reference: RET-2026-0001."""
    curr_year = datetime.now().year
    prefix = f"RET-{curr_year}-"
    result = db.execute(
        text("SELECT return_number FROM customer_returns WHERE return_number LIKE :pfx ORDER BY created_at DESC"),
        {"pfx": f"{prefix}%"}
    ).fetchall()

    highest = 0
    pattern = re.compile(rf"^RET-{curr_year}-(\d+)$")
    for row in result:
        num_str = row[0]
        m = pattern.match(num_str or "")
        if m:
            val = int(m.group(1))
            if val > highest:
                highest = val

    return f"{prefix}{highest + 1:04d}"


class CustomerReturn(Base):
    __tablename__ = "customer_returns"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    return_number = Column(String(50), unique=True, nullable=False, index=True)
    
    # Customer Details
    customer_id = Column(GUID, ForeignKey("customers.id"), nullable=True)
    customer_code = Column(String(50), nullable=False, index=True)
    customer_name = Column(String(200), nullable=False)
    customer_po = Column(String(100), nullable=True)
    invoice_number = Column(String(100), nullable=True, index=True)
    
    # Originating Work Order
    original_wo_id = Column(GUID, ForeignKey("work_orders.id"), nullable=True)
    original_wo_number = Column(String(100), nullable=True, index=True)
    
    # Part Details
    part_id = Column(GUID, ForeignKey("parts.id"), nullable=True)
    part_number = Column(String(100), nullable=False, index=True)
    
    # Return Quantity & Commercial Value
    returned_qty = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False, default=0.0)
    total_return_value = Column(Float, nullable=False, default=0.0)
    
    # Complaint & Cause
    complaint_reason = Column(String(2000), nullable=False)
    complaint_date = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(50), nullable=False, default="SENT_TO_CONVERSION")
    
    # Conversion into New Work Order
    conversion_wo_id = Column(GUID, ForeignKey("work_orders.id"), nullable=True)
    conversion_wo_number = Column(String(100), nullable=False, index=True)
    entry_stage = Column(String(50), nullable=False, default="F1")
    destination_oar_id = Column(GUID, ForeignKey("orders.id"), nullable=True)
    destination_oar_number = Column(String(100), nullable=True)
    
    # User / Audit
    created_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    customer = relationship("Customer", foreign_keys=[customer_id])
    part = relationship("Part", foreign_keys=[part_id])
    original_wo = relationship("WorkOrder", foreign_keys=[original_wo_id])
    conversion_wo = relationship("WorkOrder", foreign_keys=[conversion_wo_id])
    destination_order = relationship("Order", foreign_keys=[destination_oar_id])
    created_by_user = relationship("User", foreign_keys=[created_by_id])
