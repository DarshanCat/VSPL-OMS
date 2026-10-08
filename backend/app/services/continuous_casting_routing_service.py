"""Continuous Casting routing + allocation (Phase 3).

Connects an EXISTING OMS WorkOrder to versioned continuous-casting routings and plans which
physical stock units feed them. It never creates or modifies an Order, WorkOrder, WORoute,
StageWIP or movement -- the WorkOrder is only read -- and allocation reserves nothing: it
records a planning relationship; RESERVE/ISSUE/CUT_CONSUME are later services.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import CC_ROUTING_ROLES, CC_RESERVE_ROLES
from app.models.audit import AuditLog
from app.models.user import User
from app.models.work_order import WorkOrder, WOStatus
from app.models.continuous_casting import (
    ContinuousCastingMaterial, ContinuousCastingRouting, ContinuousCastingAllocation,
    ContinuousCastingStockUnit, MATERIAL_SOURCE_CONTINUOUS_CASTING, allocation_ineligibility_reason,
    next_cc_allocation_number,
)
from app.schemas.continuous_casting import (
    CCRoutingCreate, CCRoutingSupersede, CCRoutingResult, CCAllocationCreate, CCAllocationResult,
    INT32_MAX,
)
from app.services.continuous_casting_service import _require_role, _bad_request, _is_unique_violation

ROUTING_ACTIVE = "ACTIVE"
ROUTING_SUPERSEDED = "SUPERSEDED"
# Allocation statuses that still stand for a live claim on the stock.
OPEN_ALLOCATION_STATUSES = ("PLANNED", "RESERVED", "ISSUED", "PARTIALLY_CONSUMED")
CC_NUMBER_MAX_ATTEMPTS = 3


# ---------------------------------------------------------------- integer-mm calculations
def _whole_mm(name: str, value, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number of millimetres.")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum} mm.")
    return value


def calculate_blank_length_mm(finished_axial_length_mm, machining_stock_a_mm, machining_stock_b_mm) -> int:
    """blank = finished axial length + machining stock A + machining stock B (integer mm)."""
    return (
        _whole_mm("finished_axial_length_mm", finished_axial_length_mm, 1)
        + _whole_mm("machining_stock_a_mm", machining_stock_a_mm, 0)
        + _whole_mm("machining_stock_b_mm", machining_stock_b_mm, 0)
    )


def calculate_gross_required_length_mm(planned_blanks, blank_length_mm, planned_cuts, kerf_mm,
                                       total_end_trim_mm) -> int:
    """gross = planned blanks x blank length + planned cuts x kerf + total end trim (integer mm)."""
    return (
        _whole_mm("planned_blanks", planned_blanks, 1) * _whole_mm("blank_length_mm", blank_length_mm, 1)
        + _whole_mm("planned_cuts", planned_cuts, 0) * _whole_mm("kerf_mm", kerf_mm, 0)
        + _whole_mm("total_end_trim_mm", total_end_trim_mm, 0)
    )


def _validate_routing_fields(req: CCRoutingCreate) -> None:
    """Required continuous-casting fields. The schema enforces these too; this keeps the
    service safe when called without schema validation."""
    if not isinstance(req.wo_number, str) or not req.wo_number.strip():
        raise _bad_request("wo_number is required.")
    if req.validated_material_id is None:
        raise _bad_request("validated_material_id is required: Engineering must validate the stock material.")
    for name in ("required_grade", "required_section"):
        value = getattr(req, name)
        if not isinstance(value, str) or not value.strip():
            raise _bad_request(f"{name} is required.")
    for name, optional in (("finished_dimension_a_mm", False), ("finished_dimension_b_mm", True)):
        value = getattr(req, name)
        if value is None and optional:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise _bad_request(f"{name} must be a positive whole number of millimetres.")


def _derive_lengths(req: CCRoutingCreate):
    _validate_routing_fields(req)
    try:
        blank = calculate_blank_length_mm(
            req.finished_axial_length_mm, req.machining_stock_a_mm, req.machining_stock_b_mm)
        gross = calculate_gross_required_length_mm(
            req.planned_blanks, blank, req.planned_cuts, req.kerf_mm, req.end_trim_mm)
    except ValueError as exc:
        raise _bad_request(str(exc))
    for name, value in (("blank_length_mm", blank), ("gross_required_length_mm", gross)):
        if value > INT32_MAX:
            raise _bad_request(f"Calculated {name} is too large to record.")
    return blank, gross


# ---------------------------------------------------------------- shared lookups
def _load_work_order(db: Session, wo_number: str) -> WorkOrder:
    """The WorkOrder must already exist in OMS; it is only read, never changed."""
    wo = db.query(WorkOrder).filter(WorkOrder.wo_number == (wo_number or "").strip()).first()
    if not wo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Work Order '{wo_number}' not found.")
    if wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED):
        raise _bad_request(f"Work Order '{wo.wo_number}' is {wo.status.value}; it cannot take a material routing.")
    return wo


def _load_material(db: Session, material_id) -> ContinuousCastingMaterial:
    material = db.query(ContinuousCastingMaterial).filter(ContinuousCastingMaterial.id == material_id).first()
    if not material:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Validated continuous casting material not found.")
    if not material.is_active:
        raise _bad_request(f"Material '{material.material_code}' is inactive and cannot be validated for a routing.")
    return material


def _new_routing(req: CCRoutingCreate, wo: WorkOrder, material, version: int, blank: int, gross: int,
                 actor: str, now) -> ContinuousCastingRouting:
    return ContinuousCastingRouting(
        id=uuid.uuid4(), work_order_id=wo.id, version=version,
        material_source=MATERIAL_SOURCE_CONTINUOUS_CASTING, status=ROUTING_ACTIVE,
        required_grade=req.required_grade.strip(), required_section=req.required_section.strip(),
        finished_dimension_a_mm=req.finished_dimension_a_mm,
        finished_dimension_b_mm=req.finished_dimension_b_mm,
        finished_axial_length_mm=req.finished_axial_length_mm,
        planned_blanks=req.planned_blanks, blank_length_mm=blank,
        machining_stock_a_mm=req.machining_stock_a_mm, machining_stock_b_mm=req.machining_stock_b_mm,
        kerf_mm=req.kerf_mm, planned_cuts=req.planned_cuts, end_trim_mm=req.end_trim_mm,
        gross_required_length_mm=gross,
        validated_material_id=material.id, validated_by=actor, validated_at=now,
        created_by=actor,
    )


def _routing_result(routing, wo, material, message, superseded_version=None) -> CCRoutingResult:
    return CCRoutingResult(
        success=True, routing_id=str(routing.id), wo_number=wo.wo_number, version=routing.version,
        status=routing.status, material_source=routing.material_source,
        validated_material_code=material.material_code, blank_length_mm=routing.blank_length_mm,
        gross_required_length_mm=routing.gross_required_length_mm, planned_blanks=routing.planned_blanks,
        planned_cuts=routing.planned_cuts, kerf_mm=routing.kerf_mm, end_trim_mm=routing.end_trim_mm,
        superseded_version=superseded_version, message=message,
    )


def _run_routing_tx(db: Session, work):
    """Run `work()` and commit; any failure rolls everything back. A unique-constraint hit is
    a concurrent routing change (same WO/version, or a second ACTIVE) -> controlled 409."""
    try:
        result = work()
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        if _is_unique_violation(exc):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This Work Order's routing was changed concurrently; nothing was saved. Reload and retry.",
            )
        raise _bad_request("The routing violates an integrity rule and was not saved.")
    except Exception:
        db.rollback()
        raise


class ContinuousCastingRoutingService:
    @staticmethod
    def create_routing(db: Session, req: CCRoutingCreate, current_user: Optional[User] = None) -> CCRoutingResult:
        """First routing (version 1) -- or the next version when none is ACTIVE. If an ACTIVE
        routing exists it must be superseded explicitly, never silently replaced."""
        _require_role(current_user, CC_ROUTING_ROLES, "create a continuous-casting routing")
        blank, gross = _derive_lengths(req)

        def work():
            wo = _load_work_order(db, req.wo_number)
            material = _load_material(db, req.validated_material_id)
            existing = db.query(ContinuousCastingRouting).filter(
                ContinuousCastingRouting.work_order_id == wo.id).all()
            active = next((r for r in existing if r.status == ROUTING_ACTIVE), None)
            if active:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Work Order '{wo.wo_number}' already has ACTIVE routing v{active.version}; "
                    f"supersede it to issue a new version.",
                )
            version = max((r.version for r in existing), default=0) + 1
            actor = current_user.full_name
            routing = _new_routing(req, wo, material, version, blank, gross, actor, datetime.now(timezone.utc))
            db.add(routing)
            db.add(AuditLog(
                user_id=current_user.id, user_name=actor, action="CC_ROUTING_CREATED",
                entity="ContinuousCastingRouting", entity_id=wo.wo_number,
                new_value=f"v{version}, blank {blank} mm, gross {gross} mm, material {material.material_code}",
            ))
            db.flush()
            return _routing_result(routing, wo, material, f"Routing v{version} created for {wo.wo_number}.")

        return _run_routing_tx(db, work)

    @staticmethod
    def supersede_routing(db: Session, req: CCRoutingSupersede, current_user: Optional[User] = None) -> CCRoutingResult:
        """Mark the ACTIVE routing SUPERSEDED and issue the next version, in one transaction.
        The old routing and every allocation on it are left exactly as they were; stock
        reserved under it is released by the later RESERVE/RELEASE service, not here."""
        _require_role(current_user, CC_ROUTING_ROLES, "supersede a continuous-casting routing")
        reason = (req.reason or "").strip()
        if not reason:
            raise _bad_request("A reason is required to supersede a routing.")
        blank, gross = _derive_lengths(req)

        def work():
            wo = _load_work_order(db, req.wo_number)
            material = _load_material(db, req.validated_material_id)
            existing = db.query(ContinuousCastingRouting).filter(
                ContinuousCastingRouting.work_order_id == wo.id).with_for_update().all()
            active = next((r for r in existing if r.status == ROUTING_ACTIVE), None)
            if not active:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"Work Order '{wo.wo_number}' has no ACTIVE routing to supersede.")
            actor = current_user.full_name
            now = datetime.now(timezone.utc)
            old_version = active.version
            active.status = ROUTING_SUPERSEDED
            active.superseded_at = now
            active.superseded_by = actor
            active.supersede_reason = reason
            db.flush()                                    # frees the single ACTIVE slot first
            version = max(r.version for r in existing) + 1
            routing = _new_routing(req, wo, material, version, blank, gross, actor, now)
            db.add(routing)
            db.add(AuditLog(
                user_id=current_user.id, user_name=actor, action="CC_ROUTING_SUPERSEDED",
                entity="ContinuousCastingRouting", entity_id=wo.wo_number,
                old_value=f"v{old_version}", new_value=f"v{version}, blank {blank} mm, gross {gross} mm",
                details=reason,
            ))
            db.flush()
            return _routing_result(
                routing, wo, material, f"Routing v{old_version} superseded by v{version} for {wo.wo_number}.",
                superseded_version=old_version)

        return _run_routing_tx(db, work)


# ---------------------------------------------------------------- allocation
def _unit_free_length_mm(unit: ContinuousCastingStockUnit) -> int:
    return unit.remaining_length_mm - unit.reserved_length_mm - unit.issued_length_mm


def _unit_available_for_planning_mm(db: Session, unit: ContinuousCastingStockUnit) -> int:
    """Physically free length minus the not-yet-reserved remainder of live plans (open
    allocations on ACTIVE routings). Reserved/issued length is already out of the free
    figure; plans on a superseded routing no longer claim anything beyond what they reserved."""
    live = db.query(ContinuousCastingAllocation).join(
        ContinuousCastingRouting, ContinuousCastingAllocation.routing_id == ContinuousCastingRouting.id
    ).filter(
        ContinuousCastingAllocation.stock_unit_id == unit.id,
        ContinuousCastingRouting.status == ROUTING_ACTIVE,
        ContinuousCastingAllocation.status.in_(OPEN_ALLOCATION_STATUSES),
    ).all()
    unreserved_plan = sum(
        max(a.planned_length_mm - a.consumed_length_mm - a.reserved_length_mm - a.issued_length_mm, 0)
        for a in live)
    return _unit_free_length_mm(unit) - unreserved_plan


def _post_allocation(db: Session, req: CCAllocationCreate, current_user: User) -> CCAllocationResult:
    routing = db.query(ContinuousCastingRouting).filter(ContinuousCastingRouting.id == req.routing_id).first()
    if not routing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Routing not found.")
    if routing.material_source != MATERIAL_SOURCE_CONTINUOUS_CASTING:
        raise _bad_request("Only a CONTINUOUS_CASTING routing can take stock allocations.")
    if routing.status != ROUTING_ACTIVE:
        raise _bad_request(f"Routing v{routing.version} is {routing.status}; only an ACTIVE routing can be allocated to.")
    wo = db.query(WorkOrder).filter(WorkOrder.id == routing.work_order_id).first()
    if not wo or wo.status in (WOStatus.CLOSED, WOStatus.DISPATCHED):
        raise _bad_request("The routing's Work Order is closed or missing; it cannot take allocations.")

    # Lock the unit BEFORE validating its free length, so a concurrent reserve/allocation
    # cannot change the figure between this check and the later RESERVE.
    unit = db.query(ContinuousCastingStockUnit).filter(
        ContinuousCastingStockUnit.id == req.stock_unit_id).with_for_update().first()
    if not unit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock unit not found.")

    reason = allocation_ineligibility_reason(unit)
    if reason:
        raise _bad_request(f"Stock unit {unit.unit_number} is not eligible for allocation: {reason}.")
    if unit.inward.material_id != routing.validated_material_id:
        raise _bad_request(
            f"Stock unit {unit.unit_number} is not of the material validated for routing v{routing.version}.")
    if db.query(ContinuousCastingAllocation).filter(
            ContinuousCastingAllocation.routing_id == routing.id,
            ContinuousCastingAllocation.stock_unit_id == unit.id).first():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Stock unit {unit.unit_number} is already allocated to routing v{routing.version}.")

    planned = req.planned_length_mm
    if isinstance(planned, bool) or not isinstance(planned, int) or planned <= 0:
        raise _bad_request("Planned length must be a positive whole number of millimetres.")
    available = _unit_available_for_planning_mm(db, unit)
    if planned > available:
        raise _bad_request(
            f"Cannot allocate {planned} mm from {unit.unit_number}: only {max(available, 0)} mm is "
            f"available for planning ({_unit_free_length_mm(unit)} mm free).")

    actor = current_user.full_name
    allocation = ContinuousCastingAllocation(
        id=uuid.uuid4(), allocation_number=next_cc_allocation_number(db), routing_id=routing.id,
        stock_unit_id=unit.id, planned_length_mm=planned, reserved_length_mm=0, issued_length_mm=0,
        consumed_length_mm=0, status="PLANNED", created_by=actor,
    )
    db.add(allocation)
    db.add(AuditLog(
        user_id=current_user.id, user_name=actor, action="CC_ALLOCATION_CREATED",
        entity="ContinuousCastingAllocation", entity_id=allocation.allocation_number,
        new_value=f"{planned} mm of {unit.unit_number} to {wo.wo_number} routing v{routing.version}",
        details="Planning only; nothing reserved.",
    ))
    db.flush()
    planned_total = db.query(func.coalesce(func.sum(ContinuousCastingAllocation.planned_length_mm), 0)).filter(
        ContinuousCastingAllocation.routing_id == routing.id).scalar()
    return CCAllocationResult(
        success=True, allocation_id=str(allocation.id), allocation_number=allocation.allocation_number,
        routing_id=str(routing.id), routing_version=routing.version, wo_number=wo.wo_number,
        stock_unit_number=unit.unit_number, inward_number=unit.inward.inward_number,
        planned_length_mm=planned, status=allocation.status, reserved_length_mm=0,
        unit_free_length_mm=_unit_free_length_mm(unit),
        unit_available_for_planning_mm=available - planned,
        routing_gross_required_length_mm=routing.gross_required_length_mm,
        routing_planned_total_mm=int(planned_total),
        message=f"Allocation {allocation.allocation_number} planned; no stock reserved.",
    )


class ContinuousCastingAllocationService:
    @staticmethod
    def create_allocation(db: Session, req: CCAllocationCreate, current_user: Optional[User] = None) -> CCAllocationResult:
        """Plan `planned_length_mm` of one QA-accepted, in-stock unit against an ACTIVE routing.
        Does NOT reserve: reserved/issued/remaining and the ledger are untouched. A collision
        on the allocation number is retried (bounded); any other failure rolls back."""
        _require_role(current_user, CC_RESERVE_ROLES, "allocate continuous-casting stock")
        for attempt in range(1, CC_NUMBER_MAX_ATTEMPTS + 1):
            try:
                result = _post_allocation(db, req, current_user)
                db.commit()
                return result
            except IntegrityError as exc:
                db.rollback()
                if not _is_unique_violation(exc):
                    raise _bad_request("The allocation violates an integrity rule and was not saved.")
                message = str(getattr(exc, "orig", exc)).lower()
                if "allocation_number" in message:
                    if attempt == CC_NUMBER_MAX_ATTEMPTS:
                        raise HTTPException(
                            status.HTTP_409_CONFLICT,
                            f"Could not reserve a unique allocation number after {CC_NUMBER_MAX_ATTEMPTS} "
                            f"attempts; nothing was saved. Please retry.")
                    continue
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "That stock unit is already allocated to this routing; nothing was saved.")
            except Exception:
                db.rollback()
                raise
