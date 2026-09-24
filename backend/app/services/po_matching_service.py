from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.order import Order, Customer, Part
from app.models.master_data import POLine, POMaster, ScheduleMaster, ScheduleStatus
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.master_data import (
    MatchCandidate, DuplicateCheckResult, MatchConfirmRequest, MatchConfirmResponse
)


def _audit(db: Session, actor: Optional[User], action: str, entity_id: str, details: str = "") -> None:
    db.add(AuditLog(
        user_id=actor.id if actor else None,
        user_name=actor.full_name if actor else "System",
        action=action,
        entity="Order",
        entity_id=entity_id,
        details=details,
    ))


def _quantity_match(schedule_qty: int, po_qty: int) -> tuple[str, Optional[str]]:
    if schedule_qty == po_qty:
        return "EXACT", None
    if po_qty < schedule_qty:
        diff = schedule_qty - po_qty
        return "PO_BELOW_SCHEDULE", f"Quantity mismatch: PO is {diff} below schedule"
    diff = po_qty - schedule_qty
    return "PO_ABOVE_SCHEDULE", f"Quantity mismatch: PO is {diff} above schedule"


def _awaiting_schedules_for(db: Session, customer_id, part_id) -> List[ScheduleMaster]:
    """Schedule-based demand not yet matched to a PO, for this exact customer+part --
    never a different part or customer, even if quantities happen to coincide."""
    return (
        db.query(ScheduleMaster)
        .filter(
            ScheduleMaster.customer_id == customer_id,
            ScheduleMaster.part_id == part_id,
            ScheduleMaster.po_status.in_([ScheduleStatus.SCHEDULED, ScheduleStatus.AWAITING_PO]),
        )
        .order_by(ScheduleMaster.created_at.asc())
        .all()
    )


class POMatchingService:
    @staticmethod
    def check_duplicate(db: Session, customer_code: str, part_number: str) -> DuplicateCheckResult:
        """Called before creating a brand-new PO-based OAR: is there already a
        schedule-based OAR for this exact customer+part that should be matched
        instead of creating a second, duplicate OAR?"""
        customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
        part = db.query(Part).filter(Part.part_number == part_number.strip().upper()).first()
        if not customer or not part:
            return DuplicateCheckResult(has_candidate=False, candidates=[])

        schedules = _awaiting_schedules_for(db, customer.id, part.id)
        if not schedules:
            return DuplicateCheckResult(has_candidate=False, candidates=[])

        candidates = []
        for s in schedules:
            linked = s.orders[0] if s.orders else None
            candidates.append(MatchCandidate(
                schedule_id=str(s.id), schedule_number=s.schedule_number, part_number=part.part_number,
                scheduled_qty=s.scheduled_qty, required_date=s.required_date,
                oar_number=linked.oar_number if linked else None,
                quantity_match="EXACT", mismatch_message=None,  # unknown until a PO qty is compared
            ))
        return DuplicateCheckResult(
            has_candidate=True, candidates=candidates,
            message="Existing schedule-based OAR found. Match this PO instead of creating a new OAR.",
        )

    @staticmethod
    def get_match_candidates(db: Session, po_line_id: str) -> List[MatchCandidate]:
        po_line = db.query(POLine).filter(POLine.id == po_line_id).first()
        if not po_line:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO line not found.")
        po = po_line.po

        schedules = _awaiting_schedules_for(db, po.customer_id, po_line.part_id)
        candidates = []
        for s in schedules:
            match_type, message = _quantity_match(s.scheduled_qty, po_line.po_qty)
            linked = s.orders[0] if s.orders else None
            candidates.append(MatchCandidate(
                schedule_id=str(s.id), schedule_number=s.schedule_number, part_number=po_line.part.part_number,
                scheduled_qty=s.scheduled_qty, required_date=s.required_date,
                oar_number=linked.oar_number if linked else None,
                quantity_match=match_type, mismatch_message=message,
            ))
        return candidates

    @staticmethod
    def confirm_match(db: Session, req: MatchConfirmRequest, current_user: Optional[User] = None) -> MatchConfirmResponse:
        po_line = db.query(POLine).filter(POLine.id == req.po_line_id).with_for_update().first()
        if not po_line:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO line not found.")
        schedule = db.query(ScheduleMaster).filter(ScheduleMaster.id == req.schedule_id).with_for_update().first()
        if not schedule:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found.")

        if schedule.po_status not in (ScheduleStatus.SCHEDULED, ScheduleStatus.AWAITING_PO):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Schedule '{schedule.schedule_number}' is already '{schedule.po_status.value}' and cannot be matched again.")

        po = po_line.po
        if po.customer_id != schedule.customer_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PO and schedule belong to different customers -- cannot match.")
        if po_line.part_id != schedule.part_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PO line and schedule are for different parts -- cannot match.")

        match_type, mismatch_message = _quantity_match(schedule.scheduled_qty, po_line.po_qty)
        if match_type != "EXACT" and not req.acknowledge_mismatch:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=mismatch_message + " -- planner must explicitly acknowledge the mismatch to proceed.",
            )

        linked_order = schedule.orders[0] if schedule.orders else None
        if not linked_order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No OAR is linked to schedule '{schedule.schedule_number}'.")

        # Link PO/PO line to the EXISTING schedule-based OAR -- never create a new one.
        linked_order.po_line_id = po_line.id
        linked_order.customer_po = po.po_number
        linked_order.oar_po_status = "po_matched"
        schedule.po_status = ScheduleStatus.MATCHED

        _audit(
            db, current_user, "PO_SCHEDULE_MATCHED", str(linked_order.id),
            details=f"schedule={schedule.schedule_number}, po={po.po_number}, po_line={po_line.id}, match={match_type}",
        )
        db.commit()
        db.refresh(linked_order)

        return MatchConfirmResponse(
            success=True, oar_number=linked_order.oar_number, schedule_number=schedule.schedule_number,
            po_number=po.po_number, quantity_match=match_type,
            message=mismatch_message or f"Schedule '{schedule.schedule_number}' matched to PO '{po.po_number}' -- exact quantity match.",
        )
