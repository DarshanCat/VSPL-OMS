import re
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship, Session
from sqlalchemy.sql import func
from app.core.database import Base, GUID

_MRB_NUMBER_RE = re.compile(r"^MRB-(\d+)$")


def next_mrb_number(db: Session) -> str:
    """Collision-resistant MRB ticket number generation (MRB-00001)."""
    highest = 0
    for (mrb_number,) in db.query(MRBReview.mrb_number).all():
        m = _MRB_NUMBER_RE.match(mrb_number or "")
        if m:
            highest = max(highest, int(m.group(1)))
    for obj in getattr(db, "new", []):
        if isinstance(obj, MRBReview) and getattr(obj, "mrb_number", None):
            m = _MRB_NUMBER_RE.match(obj.mrb_number)
            if m:
                highest = max(highest, int(m.group(1)))
    return f"MRB-{highest + 1:05d}"


class MRBReview(Base):
    """Material Review Board (MRB) review record.
    Captures shop floor production/movement entries with OK and Rejection quantities,
    allowing Quality, Planner, Admin, and CEO to review, verify, approve, or adjust
    reported floor quantities and defect classifications.
    """
    __tablename__ = "mrb_reviews"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    mrb_number = Column(String, unique=True, nullable=False, index=True)
    production_update_id = Column(GUID, ForeignKey("production_updates.id"), nullable=True)
    movement_id = Column(GUID, ForeignKey("production_movements.id"), nullable=True)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False)
    stage = Column(String, nullable=False)
    machine_id = Column(String, nullable=True)
    operator_name = Column(String, nullable=True)
    shift = Column(String, nullable=True)
    heat_number = Column(String, nullable=True)

    # Floor Operator reported quantities
    reported_ok_qty = Column(Integer, default=0, nullable=False)
    reported_reject_qty = Column(Integer, default=0, nullable=False)
    reported_defect_code = Column(String, nullable=True)
    floor_remarks = Column(String, nullable=True)

    # Quality / Planner / Admin verified quantities
    verified_ok_qty = Column(Integer, nullable=True)
    verified_reject_qty = Column(Integer, nullable=True)
    verified_defect_code = Column(String, nullable=True)

    # Status: PENDING, APPROVED, ADJUSTED, REJECTED
    status = Column(String, default="PENDING", nullable=False, index=True)
    # Disposition: PENDING, SCRAP, REWORK, CONCESSION, RETURN_TO_SUPPLIER, RECLASSIFY_OK, VERIFIED_OK
    disposition = Column(String, default="PENDING", nullable=True)

    # Audit & Review metadata
    reviewed_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    reviewed_by_name = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder")
    production_update = relationship("ProductionUpdate")
    movement = relationship("ProductionMovement")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
