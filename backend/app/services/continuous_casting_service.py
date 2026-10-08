"""Continuous Casting (China) raw-material services.

Phase 2: Inward / GRN only. An inward creates China STOCK -- it never creates or touches an
Order, WorkOrder, route or StageWIP. The only existing-OMS table written is audit_logs.
"""
import uuid
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import CC_INWARD_ROLES
from app.models.audit import AuditLog
from app.models.user import User
from app.models.continuous_casting import (
    ContinuousCastingMaterial, ContinuousCastingInward, ContinuousCastingStockUnit,
    ContinuousCastingStockLedger, UNIT_STATUS_IN_STOCK, INWARD_INITIAL_QA_STATUS,
    qa_allocation_block_reason,
    next_cc_inward_number, next_cc_unit_numbers, next_cc_ledger_transaction_numbers,
)
from app.schemas.continuous_casting import CCInwardCreate, CCInwardResult, CCInwardUnitOut, INT32_MAX

# The only numeric limit here is the 32-bit INTEGER column bound (INT32_MAX); the
# specification sets no maximum bar length and no maximum bars per inward.
CC_NUMBER_MAX_ATTEMPTS = 3


def _require_role(current_user: Optional[User], allowed: tuple, action_label: str) -> None:
    if current_user is None or current_user.role not in allowed:
        role = current_user.role.value if current_user else "anonymous"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role}' is not authorized to {action_label}.",
        )


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _is_unique_violation(exc: IntegrityError) -> bool:
    msg = str(getattr(exc, "orig", exc)).lower()
    return "unique" in msg or "duplicate key" in msg


def _validate_request(req: CCInwardCreate) -> None:
    """Request-only checks. Re-checks what the schema already enforces so the service
    stays safe when called without going through request validation."""
    lengths = list(req.unit_lengths_mm or [])
    if not lengths:
        raise _bad_request("An inward must receive at least one physical bar.")
    for length in lengths:
        if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
            raise _bad_request("Every bar length must be a positive whole number of millimetres.")
    total = sum(lengths)
    if total > INT32_MAX:
        raise _bad_request("Total received length is too large to record.")
    if req.received_piece_count is not None and req.received_piece_count != len(lengths):
        raise _bad_request(
            f"Declared piece count {req.received_piece_count} does not match the {len(lengths)} bars supplied."
        )
    if req.received_total_length_mm is not None and req.received_total_length_mm != total:
        raise _bad_request(
            f"Declared total length {req.received_total_length_mm} mm does not match the "
            f"{total} mm sum of the bars supplied."
        )
    for name in ("stock_dimension_a_mm", "stock_dimension_b_mm"):
        value = getattr(req, name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
            raise _bad_request(f"{name} must be a positive whole number of millimetres.")


def _post_inward(db: Session, req: CCInwardCreate, current_user: User) -> CCInwardResult:
    """One attempt: stage every row, flush, reconcile from the database. Does NOT commit."""
    material = db.query(ContinuousCastingMaterial).filter(
        ContinuousCastingMaterial.id == req.material_id
    ).first()
    if not material:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Continuous casting material not found.")
    if not material.is_active:
        raise _bad_request(f"Material '{material.material_code}' is inactive and cannot be received.")
    if material.stock_dimension_a_mm is None or material.stock_dimension_a_mm <= 0:
        raise _bad_request(f"Material '{material.material_code}' has invalid stock dimensions.")
    # The inward is a homogeneous line of this material, so any supplied dimensions must match it.
    if req.stock_dimension_a_mm is not None and req.stock_dimension_a_mm != material.stock_dimension_a_mm:
        raise _bad_request(
            f"Stock dimension A {req.stock_dimension_a_mm} mm does not match material "
            f"'{material.material_code}' ({material.stock_dimension_a_mm} mm)."
        )
    if req.stock_dimension_b_mm is not None and req.stock_dimension_b_mm != material.stock_dimension_b_mm:
        raise _bad_request(
            f"Stock dimension B {req.stock_dimension_b_mm} mm does not match material "
            f"'{material.material_code}' ({material.stock_dimension_b_mm} mm)."
        )

    lengths = list(req.unit_lengths_mm)
    total = sum(lengths)
    actor = current_user.full_name
    grn = req.grn_reference.strip() if req.grn_reference and req.grn_reference.strip() else None
    location = req.location.strip() if req.location and req.location.strip() else None

    inward_id = uuid.uuid4()
    inward_number = next_cc_inward_number(db)
    unit_numbers = next_cc_unit_numbers(db, len(lengths))
    txn_numbers = next_cc_ledger_transaction_numbers(db, len(lengths))

    db.add(ContinuousCastingInward(
        id=inward_id, inward_number=inward_number, material_id=material.id,
        grade=material.grade, section=material.section,
        stock_dimension_a_mm=material.stock_dimension_a_mm,
        stock_dimension_b_mm=material.stock_dimension_b_mm,
        received_piece_count=len(lengths), received_total_length_mm=total,
        grn_reference=grn, qa_status=INWARD_INITIAL_QA_STATUS, location=location, remarks=req.remarks,
        created_by=actor, updated_by=actor,
    ))
    unit_rows = []
    for length, unit_number, txn_number in zip(lengths, unit_numbers, txn_numbers):
        unit_id = uuid.uuid4()
        db.add(ContinuousCastingStockUnit(
            id=unit_id, unit_number=unit_number, inward_id=inward_id,
            original_length_mm=length, remaining_length_mm=length,
            reserved_length_mm=0, issued_length_mm=0, consumed_length_mm=0,
            status=UNIT_STATUS_IN_STOCK, location=location, created_by=actor,
        ))
        db.add(ContinuousCastingStockLedger(
            id=uuid.uuid4(), transaction_number=txn_number, movement_type="INWARD",
            inward_id=inward_id, stock_unit_id=unit_id, length_mm=length, piece_qty=1,
            unit_remaining_after_mm=length, reason=f"Inward {inward_number}", reference=grn,
            performed_by_id=current_user.id, performed_by_name=actor,
        ))
        unit_rows.append(CCInwardUnitOut(
            unit_number=unit_number, ledger_transaction_number=txn_number,
            original_length_mm=length, remaining_length_mm=length,
        ))
    db.add(AuditLog(
        user_id=current_user.id, user_name=actor, action="CC_INWARD",
        entity="ContinuousCastingInward", entity_id=inward_number,
        new_value=f"{len(lengths)} bar(s), {total} mm, material {material.material_code}",
        details=f"GRN: {grn or 'n/a'}, QA: {INWARD_INITIAL_QA_STATUS}",
    ))
    db.flush()

    # The ledger is authoritative: re-query the database and require the header, the
    # physical units and the INWARD ledger rows to agree exactly before anything commits.
    unit_count, units_orig, units_rem = db.query(
        func.count(ContinuousCastingStockUnit.id),
        func.coalesce(func.sum(ContinuousCastingStockUnit.original_length_mm), 0),
        func.coalesce(func.sum(ContinuousCastingStockUnit.remaining_length_mm), 0),
    ).filter(
        ContinuousCastingStockUnit.inward_id == inward_id,
        ContinuousCastingStockUnit.parent_unit_id.is_(None),    # root units only: a split child is not a receipt
    ).one()
    ledger_rows, ledger_pieces, ledger_len = db.query(
        func.count(ContinuousCastingStockLedger.id),
        func.coalesce(func.sum(ContinuousCastingStockLedger.piece_qty), 0),
        func.coalesce(func.sum(ContinuousCastingStockLedger.length_mm), 0),
    ).filter(
        ContinuousCastingStockLedger.inward_id == inward_id,
        ContinuousCastingStockLedger.movement_type == "INWARD",
    ).one()
    reconciled = (
        unit_count == ledger_rows == ledger_pieces == len(lengths)
        and units_orig == units_rem == ledger_len == total
    )
    if not reconciled:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Inward failed stock reconciliation; nothing was posted.",
        )

    block_reason = qa_allocation_block_reason(INWARD_INITIAL_QA_STATUS)
    return CCInwardResult(
        success=True, inward_id=str(inward_id), inward_number=inward_number,
        material_code=material.material_code, grn_reference=grn,
        qa_status=INWARD_INITIAL_QA_STATUS, physical_stock_status=UNIT_STATUS_IN_STOCK,
        allocation_eligible=block_reason is None, allocation_ineligible_reason=block_reason,
        received_piece_count=len(lengths), received_total_length_mm=total,
        ledger_inward_length_mm=int(ledger_len), units_original_length_mm=int(units_orig),
        units_remaining_length_mm=int(units_rem), reconciled=True, units=unit_rows,
        message=(
            f"Inward {inward_number} posted: {len(lengths)} bar(s), {total} mm, in stock. "
            f"Not allocatable until QA acceptance."
        ),
    )


class ContinuousCastingInwardService:
    @staticmethod
    def create_inward(db: Session, req: CCInwardCreate, current_user: Optional[User] = None) -> CCInwardResult:
        """Post one homogeneous continuous-casting inward atomically: the INW number, one
        stock unit per bar, and one INWARD ledger row per unit, all in a single transaction.

        Business numbers come from the parse-max-and-increment generators, which are NOT
        concurrency-safe by themselves. A collision on a number's unique constraint rolls
        everything back and the whole inward is re-attempted (bounded); only after the last
        attempt does the caller get a 409. There is no inward-level idempotency key: the
        cc_inwards model has no client_request_id, so a double submit creates two inwards."""
        _require_role(current_user, CC_INWARD_ROLES, "post a continuous-casting inward")
        _validate_request(req)
        for attempt in range(1, CC_NUMBER_MAX_ATTEMPTS + 1):
            try:
                result = _post_inward(db, req, current_user)
                db.commit()
                return result
            except IntegrityError as exc:
                db.rollback()
                if not _is_unique_violation(exc):
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        "The inward violates a stock integrity rule and was not posted.",
                    )
                if attempt == CC_NUMBER_MAX_ATTEMPTS:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Could not reserve unique inward/unit/ledger numbers after "
                        f"{CC_NUMBER_MAX_ATTEMPTS} attempts; nothing was posted. Please retry.",
                    )
            except Exception:
                db.rollback()
                raise
