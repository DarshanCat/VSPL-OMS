import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

class RejectionDisposition(Base):
    """A single disposition action taken against a tracked rejection/excess/non-moving
    record (an NCRecord). This is the quantity ledger that makes a record's lifecycle
    (source qty -> consumed qty -> remaining qty) auditable without ever rewriting the
    immutable qty on the NCRecord itself or on any StageWIP row."""
    __tablename__ = "rejection_dispositions"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    nc_record_id = Column(GUID, ForeignKey("nc_records.id"), nullable=False)
    # One of: CONVERT_PART, SAME_PART, CWO, SCRAP, DEVIATION_ACCEPT
    action = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    destination_wo_number = Column(String, nullable=True)
    destination_part_number = Column(String, nullable=True)
    destination_customer_code = Column(String, nullable=True)
    # Links to the Conversion ledger row when this disposition actually created a new
    # Work Order (CONVERT_PART / SAME_PART / CWO). Null for SCRAP / DEVIATION_ACCEPT.
    conversion_id = Column(GUID, ForeignKey("conversions.id"), nullable=True)
    authorized_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    authorized_by_name = Column(String, nullable=True)
    remarks = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Physical material-handling fulfillment of a SCRAP disposition decision: recording
    # that the already-decided scrap quantity was physically sent for melting. This is
    # a separate, later, execution-only event -- it never re-decides or re-authorizes
    # the disposition itself (that authority stays with authorized_by/action above).
    # Null until the physical transfer actually happens.
    melting_status = Column(String, nullable=True)  # None | "SENT_FOR_MELTING"
    melting_destination = Column(String, nullable=True)
    melting_sent_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    melting_sent_by_name = Column(String, nullable=True)
    melting_sent_at = Column(DateTime(timezone=True), nullable=True)
    melting_remarks = Column(String, nullable=True)

    nc_record = relationship("NCRecord", back_populates="dispositions")
    conversion = relationship("Conversion", foreign_keys=[conversion_id])
    authorized_by = relationship("User", foreign_keys=[authorized_by_id])
    melting_sent_by = relationship("User", foreign_keys=[melting_sent_by_id])
