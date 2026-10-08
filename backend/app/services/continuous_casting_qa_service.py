"""Continuous Casting inward QA decision (Phase 11A).

Every inward starts PENDING_QA and nothing could move it, so no stock was ever allocatable through the
application. This is the dedicated China operation Quality uses to record its decision on one inward receipt:

    PENDING_QA -> ACCEPTED | REJECTED | ON_HOLD

It reuses the existing inward qa_status vocabulary and makes the existing, unchanged allocation eligibility
predicate (allocation_ineligibility_reason / qa_allocation_block_reason) effective. It is NOT a China QA engine
and does not touch the OMS NC / Quality workflow.

  * Only a PENDING_QA inward can receive a decision. Any later attempt -- the same decision again, or another
    one such as REJECTED -> ACCEPTED -- is refused, so a recorded decision is never silently rewritten. A later,
    controlled QA re-review capability is left for a future phase.
  * A reason is required for REJECTED and ON_HOLD, optional for ACCEPTED.
  * Not a physical stock movement: no ledger row, and no change to any StockUnit (its physical status and
    balances are untouched; an inward ON_HOLD / REJECTED never cascades to unit status).
  * The decision is auditable (an audit row records who, the old and the new status and the reason).
  * One atomic transaction that commits inside the service; the inward row is locked (FOR UPDATE, re-read after
    the lock), so two concurrent decisions cannot both succeed.
"""
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.roles import CC_QA_ROLES
from app.models.audit import AuditLog
from app.models.user import User
from app.models.continuous_casting import (
    ContinuousCastingInward, INWARD_INITIAL_QA_STATUS, qa_allocation_block_reason,
)
from app.schemas.continuous_casting import CCInwardQADecisionCreate, CCInwardQADecisionResult
from app.services.continuous_casting_service import _require_role, _bad_request
from app.services.continuous_casting_reservation_service import _lock, _run

Inward = ContinuousCastingInward
DECISIONS = ("ACCEPTED", "REJECTED", "ON_HOLD")
REASON_REQUIRED = ("REJECTED", "ON_HOLD")


def _decide(db: Session, req: CCInwardQADecisionCreate, user: User) -> CCInwardQADecisionResult:
    if req.inward_id is None:
        raise _bad_request("inward_id is required.")
    decision = req.decision
    if decision not in DECISIONS:
        raise _bad_request(f"decision must be one of {', '.join(DECISIONS)}.")
    reason = req.reason.strip() if isinstance(req.reason, str) and req.reason.strip() else None
    if decision in REASON_REQUIRED and reason is None:
        raise _bad_request(f"A reason is required for a {decision} decision.")

    inward = _lock(db, Inward, req.inward_id)                             # re-read after the lock
    if inward is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Continuous casting inward not found.")
    previous = inward.qa_status
    if previous != INWARD_INITIAL_QA_STATUS:
        same = "The same decision cannot be recorded again. " if previous == decision else ""
        raise _bad_request(
            f"Inward {inward.inward_number} is already {previous}; only a {INWARD_INITIAL_QA_STATUS} inward can "
            f"receive a QA decision. {same}A recorded decision is never rewritten through this operation.")

    actor = user.full_name
    inward.qa_status = decision
    inward.updated_by = actor
    db.add(AuditLog(
        user_id=user.id, user_name=actor, action="CC_INWARD_QA_DECISION", entity="ContinuousCastingInward",
        entity_id=inward.inward_number, old_value=previous, new_value=decision, details=reason,
    ))
    db.flush()
    block = qa_allocation_block_reason(inward.qa_status)
    return CCInwardQADecisionResult(
        success=True, inward_id=str(inward.id), inward_number=inward.inward_number, previous_qa_status=previous,
        qa_status=inward.qa_status, reason=reason, decided_by=actor, qa_allows_allocation=block is None,
        qa_block_reason=block,
        message=(f"Inward {inward.inward_number} {decision}." + (
            " Its stock units are now allocatable (subject to the unchanged unit-status and free-length rules)."
            if block is None else " Its stock units stay non-allocatable.")),
    )


class ContinuousCastingQAService:
    @staticmethod
    def decide(db: Session, req: CCInwardQADecisionCreate,
               current_user: Optional[User] = None) -> CCInwardQADecisionResult:
        """Record Quality's decision on one PENDING_QA inward. Audited; no ledger row; no unit change."""
        _require_role(current_user, CC_QA_ROLES, "record a continuous-casting inward QA decision")
        return _run(db, lambda: _decide(db, req, current_user))
