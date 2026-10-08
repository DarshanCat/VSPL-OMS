"""Continuous Casting READ service (Phase 11C): the read-only application layer over the China module.

Nothing here is a second source of truth. Field classes used throughout:
  A  a direct authoritative column (the cached stock balances are authoritative: every write reconciles them with
     the append-only ledger before it commits)
  B  an existing deterministic calculation (free = remaining - reserved - issued; plan remaining = planned -
     reserved - issued - consumed; the allocation-eligibility predicate)
  C  ledger-derived (adjustment totals, the optional integrity comparison, last hold event, ledger history)
  D  relationship-derived (numbers and names reached through unit / inward / allocation / routing / work order)

Every method only reads: no flush, no commit, no write, and nothing is repaired. A ledger-derived inconsistency is
reported as an informational flag, never raised (unlike the mutation-time reconciliation, which refuses to commit).
Lists use one envelope {items, total, limit, offset}; the page and its COUNT are separate queries, balances over
many units come from one grouped SQL aggregate, and numbers from related tables come from joins or one batched
lookup per page, so the query count does not grow with the page size.
"""
import re
from datetime import datetime
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import and_, func, not_
from sqlalchemy.orm import Session, aliased, contains_eager

from app.models.audit import AuditLog
from app.models.nc import NCRecord
from app.models.production_movement import StageWIP
from app.models.work_order import WorkOrder, WORoute
from app.models.continuous_casting import (
    ContinuousCastingAllocation, ContinuousCastingCutRecord, ContinuousCastingInward, ContinuousCastingMaterial,
    ContinuousCastingRouting, ContinuousCastingStockLedger, ContinuousCastingStockUnit, ALLOCATABLE_QA_STATUS,
    MATERIAL_SOURCE_CONTINUOUS_CASTING, UNIT_STATUS_IN_STOCK, allocation_ineligibility_reason,
)
from app.schemas.continuous_casting_read import (
    CCAllocationListResponse, CCAllocationOut, CCConservation, CCCutAvailableListResponse, CCCutAvailableOut,
    CCCutResultListResponse, CCCutResultOut, CCGateStatus, CCInwardDetail, CCInwardListResponse, CCInwardStockOut,
    CCLastHold, CCLedgerListResponse, CCLedgerOut, CCMaterialListResponse, CCMaterialOut,
    CCMaterialStockSummaryOut, CCMaterialStockSummaryResponse, CCMaterialStockSummaryTotals, CCQADecisionInfo,
    CCRoutingDetail, CCRoutingListResponse, CCRoutingOut, CCStockUnitDetail, CCStockUnitListResponse,
    CCStockUnitOut, CCTraceInward, CCTraceInwardRollup, CCTraceUnit, CCTraceWorkOrder, CCTraceWorkOrderRollup,
    CCUnitChild, CCUnitIntegrity,
)
from app.services.continuous_casting_gate_service import ContinuousCastingGateService
from app.services.continuous_casting_reservation_service import (
    ROUTING_ACTIVE, ROUTING_SUPERSEDED, _derive, _derive_remaining, _ledger_totals,
)

Material, Inward, Unit = ContinuousCastingMaterial, ContinuousCastingInward, ContinuousCastingStockUnit
Routing, Alloc = ContinuousCastingRouting, ContinuousCastingAllocation
Ledger, Cut = ContinuousCastingStockLedger, ContinuousCastingCutRecord

TRACE_UNIT_CAP = 500
TRACE_ALLOCATION_CAP = 1000
TRACE_CUT_RESULT_CAP = 500
TRACE_LEDGER_RECENT = 100
TRACE_LIMITATIONS = [
    "Allocation is the join between a stock unit and a Work Order; one inward can feed many Work Orders and one "
    "Work Order can draw on many inwards.",
    "Downstream component traceability is not available: OMS production quantities are aggregate stage counters, so "
    "a specific OMS piece cannot be attributed to a specific cut result or inward. The material gate only caps the "
    "first-stage total by the usable good blanks.",
    "The schema has no heat, lot or serial number; only the GRN reference on the inward.",
]


def _s(value) -> Optional[str]:
    return None if value is None else str(value)


def _free(remaining, reserved, issued) -> int:
    return int(remaining) - int(reserved) - int(issued)


def _contains(column, text: Optional[str]):
    return column.ilike(f"%{text.strip()}%")


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found.")


def _bad(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail)


# ================================================================== row -> response helpers
def _alloc_out(a, routing, wo, unit, inward) -> CCAllocationOut:
    return CCAllocationOut(
        allocation_id=str(a.id), allocation_number=a.allocation_number, routing_id=str(routing.id),
        routing_version=routing.version, routing_status=routing.status, work_order_id=str(wo.id),
        wo_number=wo.wo_number, inward_id=str(inward.id), inward_number=inward.inward_number,
        stock_unit_id=str(unit.id), stock_unit_number=unit.unit_number, planned_length_mm=a.planned_length_mm,
        reserved_length_mm=a.reserved_length_mm, issued_length_mm=a.issued_length_mm,
        consumed_length_mm=a.consumed_length_mm,
        plan_remaining_length_mm=a.planned_length_mm - a.reserved_length_mm - a.issued_length_mm - a.consumed_length_mm,
        status=a.status,
    )


def _unit_out(unit, parent_numbers: dict) -> CCStockUnitOut:
    """`unit.inward` (and its material) must already be loaded."""
    inward = unit.inward
    reason = allocation_ineligibility_reason(unit)                   # B: the frozen eligibility predicate
    return CCStockUnitOut(
        unit_id=str(unit.id), unit_number=unit.unit_number, inward_id=str(inward.id), inward_number=inward.inward_number,
        inward_qa_status=inward.qa_status, material_id=str(inward.material_id),
        material_code=inward.material.material_code, parent_unit_id=_s(unit.parent_unit_id),
        parent_unit_number=parent_numbers.get(unit.parent_unit_id), original_length_mm=unit.original_length_mm,
        remaining_length_mm=unit.remaining_length_mm, reserved_length_mm=unit.reserved_length_mm,
        issued_length_mm=unit.issued_length_mm, consumed_length_mm=unit.consumed_length_mm,
        scrapped_length_mm=unit.scrapped_length_mm,
        free_length_mm=_free(unit.remaining_length_mm, unit.reserved_length_mm, unit.issued_length_mm),
        piece_quantity=1, status=unit.status, location=unit.location, created_at=unit.created_at,
        allocation_eligible=reason is None, allocation_ineligible_reason=reason,
    )


def _routing_out(r, wo_number: str, material_code: Optional[str], allocation_count: int) -> CCRoutingOut:
    return CCRoutingOut(
        routing_id=str(r.id), work_order_id=str(r.work_order_id), wo_number=wo_number, version=r.version,
        status=r.status, is_active=r.status == ROUTING_ACTIVE, material_source=r.material_source,
        validated_material_id=_s(r.validated_material_id), validated_material_code=material_code,
        required_grade=r.required_grade, required_section=r.required_section,
        finished_dimension_a_mm=r.finished_dimension_a_mm, finished_dimension_b_mm=r.finished_dimension_b_mm,
        finished_axial_length_mm=r.finished_axial_length_mm, machining_stock_a_mm=r.machining_stock_a_mm,
        machining_stock_b_mm=r.machining_stock_b_mm, blank_length_mm=r.blank_length_mm,
        planned_blanks=r.planned_blanks, planned_cuts=r.planned_cuts, kerf_mm=r.kerf_mm, end_trim_mm=r.end_trim_mm,
        gross_required_length_mm=r.gross_required_length_mm, validated_by=r.validated_by,
        validated_at=r.validated_at, superseded_at=r.superseded_at, superseded_by=r.superseded_by,
        supersede_reason=r.supersede_reason, created_by=r.created_by, created_at=r.created_at,
        allocation_count=int(allocation_count or 0),
    )


def _cut_usable(cut, ledger, routing) -> bool:
    """The Phase 10 gate's own conditions, for one record: RECONCILED with zero variance, on the WO's ACTIVE China
    routing, and backed by a real CUT_CONSUME row with the same allocation, unit and consumed length."""
    return bool(
        cut.reconciliation_status == "RECONCILED" and cut.variance_mm == 0
        and routing.status == ROUTING_ACTIVE and routing.material_source == MATERIAL_SOURCE_CONTINUOUS_CASTING
        and routing.work_order_id == cut.work_order_id and ledger is not None
        and ledger.movement_type == "CUT_CONSUME" and ledger.allocation_id == cut.allocation_id
        and ledger.stock_unit_id == cut.stock_unit_id and ledger.length_mm == cut.consumed_length_mm)


def _cut_out(row) -> CCCutResultOut:
    cut, ledger, alloc, routing, wo, unit, inward = row
    return CCCutResultOut(
        cut_result_id=str(cut.id), cut_number=cut.cut_number,
        ledger_transaction_number=ledger.transaction_number if ledger is not None else None,
        work_order_id=str(wo.id), wo_number=wo.wo_number, routing_id=str(routing.id),
        routing_version=routing.version, routing_status=routing.status, allocation_id=str(alloc.id),
        allocation_number=alloc.allocation_number, stock_unit_id=str(unit.id), stock_unit_number=unit.unit_number,
        inward_number=inward.inward_number, planned_blanks=cut.planned_blanks, actual_cuts=cut.actual_cuts,
        actual_good_blanks=cut.actual_good_blanks, rejected_blanks=cut.rejected_blanks,
        blank_length_mm=cut.blank_length_mm, kerf_mm=cut.kerf_mm, end_trim_mm=cut.end_trim_mm,
        consumed_length_mm=cut.consumed_length_mm, reconciliation_status=cut.reconciliation_status,
        variance_mm=cut.variance_mm, remarks=cut.remarks, performed_by=cut.performed_by_name,
        created_at=cut.created_at, usable_for_oms=_cut_usable(cut, ledger, routing),
    )


def _ledger_out(row) -> CCLedgerOut:
    entry, unit_number, inward_number, allocation_number, routing_id, routing_version, wo_number, rel_number, nc_number = row
    return CCLedgerOut(
        transaction_number=entry.transaction_number, movement_type=entry.movement_type, inward_id=str(entry.inward_id),
        inward_number=inward_number, stock_unit_id=str(entry.stock_unit_id), stock_unit_number=unit_number,
        allocation_id=_s(entry.allocation_id), allocation_number=allocation_number, routing_id=_s(routing_id),
        routing_version=routing_version, wo_number=wo_number, length_mm=entry.length_mm, piece_qty=entry.piece_qty,
        unit_remaining_after_mm=entry.unit_remaining_after_mm, related_stock_unit_id=_s(entry.related_stock_unit_id),
        related_stock_unit_number=rel_number, nc_record_id=_s(entry.nc_record_id), nc_number=nc_number,
        reason=entry.reason, reference=entry.reference, performed_by=entry.performed_by_name,
        created_at=entry.created_at,
    )


# ================================================================== query builders
def _alloc_query(db: Session):
    return (db.query(Alloc, Routing, WorkOrder, Unit, Inward)
            .join(Routing, Routing.id == Alloc.routing_id)
            .join(WorkOrder, WorkOrder.id == Routing.work_order_id)
            .join(Unit, Unit.id == Alloc.stock_unit_id)
            .join(Inward, Inward.id == Unit.inward_id))


def _ledger_query(db: Session):
    related = aliased(Unit)
    query = (db.query(Ledger, Unit.unit_number, Inward.inward_number, Alloc.allocation_number, Routing.id,
                      Routing.version, WorkOrder.wo_number, related.unit_number, NCRecord.nc_number)
             .join(Unit, Unit.id == Ledger.stock_unit_id)
             .join(Inward, Inward.id == Ledger.inward_id)
             .outerjoin(Alloc, Alloc.id == Ledger.allocation_id)
             .outerjoin(Routing, Routing.id == Alloc.routing_id)
             .outerjoin(WorkOrder, WorkOrder.id == Routing.work_order_id)
             .outerjoin(related, related.id == Ledger.related_stock_unit_id)
             .outerjoin(NCRecord, NCRecord.id == Ledger.nc_record_id))
    return query


def _cut_query(db: Session):
    return (db.query(Cut, Ledger, Alloc, Routing, WorkOrder, Unit, Inward)
            .outerjoin(Ledger, Ledger.id == Cut.ledger_entry_id)
            .join(Alloc, Alloc.id == Cut.allocation_id)
            .join(Routing, Routing.id == Alloc.routing_id)
            .join(WorkOrder, WorkOrder.id == Cut.work_order_id)
            .join(Unit, Unit.id == Cut.stock_unit_id)
            .join(Inward, Inward.id == Unit.inward_id))


def _unit_aggregate(db: Session):
    """One grouped SQL aggregate of the cached unit balances per inward."""
    return db.query(
        Unit.inward_id.label("inward_id"), func.count(Unit.id).label("unit_count"),
        func.coalesce(func.sum(Unit.remaining_length_mm), 0).label("remaining"),
        func.coalesce(func.sum(Unit.reserved_length_mm), 0).label("reserved"),
        func.coalesce(func.sum(Unit.issued_length_mm), 0).label("issued"),
        func.coalesce(func.sum(Unit.consumed_length_mm), 0).label("consumed"),
        func.coalesce(func.sum(Unit.scrapped_length_mm), 0).label("scrapped"),
        func.coalesce(func.sum(Unit.remaining_length_mm - Unit.reserved_length_mm - Unit.issued_length_mm), 0).label("free"),
    ).group_by(Unit.inward_id).subquery()


def _inward_stock_query(db: Session):
    agg = _unit_aggregate(db)
    query = (db.query(Inward, Material.material_code, agg.c.unit_count, agg.c.remaining, agg.c.reserved,
                      agg.c.issued, agg.c.consumed, agg.c.scrapped, agg.c.free)
             .join(Material, Material.id == Inward.material_id)
             .outerjoin(agg, agg.c.inward_id == Inward.id))
    return query, agg


def _inward_stock_out(row, cls=CCInwardStockOut, **extra):
    inward, material_code, unit_count, remaining, reserved, issued, consumed, scrapped, free = row
    return cls(
        inward_id=str(inward.id), inward_number=inward.inward_number, material_id=str(inward.material_id),
        material_code=material_code, grade=inward.grade, section=inward.section,
        stock_dimension_a_mm=inward.stock_dimension_a_mm, stock_dimension_b_mm=inward.stock_dimension_b_mm,
        received_piece_count=inward.received_piece_count, received_total_length_mm=inward.received_total_length_mm,
        grn_reference=inward.grn_reference, qa_status=inward.qa_status, location=inward.location,
        received_at=inward.received_at, unit_count=int(unit_count or 0), remaining_length_mm=int(remaining or 0),
        reserved_length_mm=int(reserved or 0), issued_length_mm=int(issued or 0),
        consumed_length_mm=int(consumed or 0), scrapped_length_mm=int(scrapped or 0), free_length_mm=int(free or 0),
        **extra)


def _parent_numbers(db: Session, units) -> dict:
    parent_ids = {u.parent_unit_id for u in units if u.parent_unit_id is not None}
    if not parent_ids:
        return {}
    return dict(db.query(Unit.id, Unit.unit_number).filter(Unit.id.in_(parent_ids)).all())


def _routing_rows(db: Session):
    counts = db.query(Alloc.routing_id.label("routing_id"), func.count(Alloc.id).label("n")).group_by(
        Alloc.routing_id).subquery()
    query = (db.query(Routing, WorkOrder.wo_number, Material.material_code, counts.c.n)
             .join(WorkOrder, WorkOrder.id == Routing.work_order_id)
             .outerjoin(Material, Material.id == Routing.validated_material_id)
             .outerjoin(counts, counts.c.routing_id == Routing.id))
    return query


class ContinuousCastingReadService:
    # ============================================================== materials
    @staticmethod
    def list_materials(db: Session, *, search: Optional[str], is_active: Optional[bool], grade: Optional[str],
                       section: Optional[str], limit: int, offset: int) -> CCMaterialListResponse:
        query = db.query(Material)
        if search:
            query = query.filter(_contains(Material.material_code, search))
        if is_active is not None:
            query = query.filter(Material.is_active == is_active)
        if grade:
            query = query.filter(func.lower(Material.grade) == grade.strip().lower())
        if section:
            query = query.filter(func.lower(Material.section) == section.strip().lower())
        total = query.count()
        materials = query.order_by(Material.material_code).offset(offset).limit(limit).all()
        ids = [m.id for m in materials]
        inwards = dict(db.query(Inward.material_id, func.count(Inward.id)).filter(
            Inward.material_id.in_(ids)).group_by(Inward.material_id).all()) if ids else {}
        routings = dict(db.query(Routing.validated_material_id, func.count(Routing.id)).filter(
            Routing.validated_material_id.in_(ids)).group_by(Routing.validated_material_id).all()) if ids else {}
        items = [CCMaterialOut(
            material_id=str(m.id), material_code=m.material_code, grade=m.grade, section=m.section,
            stock_dimension_a_mm=m.stock_dimension_a_mm, stock_dimension_b_mm=m.stock_dimension_b_mm,
            description=m.description, is_active=m.is_active, referenced=bool(inwards.get(m.id) or routings.get(m.id)),
            inward_count=int(inwards.get(m.id, 0)), routing_count=int(routings.get(m.id, 0)),
            created_by=m.created_by, updated_by=m.updated_by, created_at=m.created_at, updated_at=m.updated_at,
        ) for m in materials]
        return CCMaterialListResponse(items=items, total=total, limit=limit, offset=offset)

    @staticmethod
    def list_material_stock_summary(
        db: Session,
        *,
        search: Optional[str] = None,
        grade: Optional[str] = None,
        section: Optional[str] = None,
        status_filter: Optional[str] = None,
        location: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CCMaterialStockSummaryResponse:
        query = db.query(Material)
        if search:
            query = query.filter(_contains(Material.material_code, search))
        if grade:
            query = query.filter(func.lower(Material.grade) == grade.strip().lower())
        if section:
            query = query.filter(func.lower(Material.section) == section.strip().lower())

        all_materials = query.order_by(Material.material_code).all()
        mat_ids = [m.id for m in all_materials]

        inwards_query = db.query(Inward)
        if mat_ids:
            inwards_query = inwards_query.filter(Inward.material_id.in_(mat_ids))
        inwards_list = inwards_query.all()

        inwards_by_mat = {}
        for inw in inwards_list:
            inwards_by_mat.setdefault(inw.material_id, []).append(inw)

        units_query = db.query(Unit).join(Inward, Inward.id == Unit.inward_id)
        if mat_ids:
            units_query = units_query.filter(Inward.material_id.in_(mat_ids))
        if location:
            units_query = units_query.filter(_contains(Unit.location, location))
        if status_filter:
            units_query = units_query.filter(Unit.status == status_filter.strip().upper())

        units_list = units_query.all()
        inw_to_mat = {inw.id: inw.material_id for inw in inwards_list}

        units_by_mat = {}
        for u in units_list:
            mid = inw_to_mat.get(u.inward_id)
            if mid:
                units_by_mat.setdefault(mid, []).append(u)

        all_items = []
        overall_total_bars = 0
        overall_total_length = 0
        overall_total_weight = 0.0

        for m in all_materials:
            m_units = units_by_mat.get(m.id, [])
            m_inwards = inwards_by_mat.get(m.id, [])

            if (location or status_filter) and not m_units:
                continue

            unit_count = len(m_units)
            total_len = sum(u.original_length_mm for u in m_units)
            rem_len = sum(u.remaining_length_mm for u in m_units)
            res_len = sum(u.reserved_length_mm for u in m_units)
            iss_len = sum(u.issued_length_mm for u in m_units)
            cons_len = sum(u.consumed_length_mm for u in m_units)
            scrap_len = sum(u.scrapped_length_mm for u in m_units)
            free_len = sum(_free(u.remaining_length_mm, u.reserved_length_mm, u.issued_length_mm) for u in m_units)

            doc_wt = 0.0
            has_wt = False
            for inw in m_inwards:
                if inw.remarks:
                    match = re.search(r'N\.W\.:\s*([0-9.]+)\s*kg', inw.remarks, re.IGNORECASE)
                    if match:
                        doc_wt += float(match.group(1))
                        has_wt = True

            std_len = m_units[0].original_length_mm if m_units else 1000
            dim_b = m.stock_dimension_b_mm or m.stock_dimension_a_mm
            size_disp = f"{m.stock_dimension_a_mm}×{dim_b}×{std_len} mm"

            if unit_count == 0:
                mat_status = "OUT_OF_STOCK"
            elif all(u.status == "ON_HOLD" for u in m_units):
                mat_status = "ON_HOLD"
            elif any(u.status == "IN_STOCK" and _free(u.remaining_length_mm, u.reserved_length_mm, u.issued_length_mm) > 0 for u in m_units):
                mat_status = "IN_STOCK"
            elif all(u.status == "CONSUMED" for u in m_units):
                mat_status = "CONSUMED"
            else:
                mat_status = "IN_STOCK"

            overall_total_bars += unit_count
            overall_total_length += total_len
            if has_wt:
                overall_total_weight += doc_wt

            all_items.append(CCMaterialStockSummaryOut(
                material_id=str(m.id),
                material_code=m.material_code,
                grade=m.grade,
                section=m.section,
                stock_dimension_a_mm=m.stock_dimension_a_mm,
                stock_dimension_b_mm=m.stock_dimension_b_mm,
                standard_length_mm=std_len,
                size_display=size_disp,
                unit_count=unit_count,
                total_length_mm=total_len,
                remaining_length_mm=rem_len,
                reserved_length_mm=res_len,
                issued_length_mm=iss_len,
                consumed_length_mm=cons_len,
                scrapped_length_mm=scrap_len,
                free_length_mm=free_len,
                documented_weight_kg=round(doc_wt, 2) if has_wt else None,
                status=mat_status,
                inward_count=len(m_inwards),
                inward_numbers=[inw.inward_number for inw in m_inwards],
            ))

        paged_items = all_items[offset:offset + limit]
        return CCMaterialStockSummaryResponse(
            items=paged_items,
            total=len(all_items),
            totals=CCMaterialStockSummaryTotals(
                total_bars=overall_total_bars,
                total_length_mm=overall_total_length,
                total_weight_kg=round(overall_total_weight, 2),
            ),
            limit=limit,
            offset=offset,
        )

    # ============================================================== inwards
    @staticmethod
    def list_inwards(db: Session, *, inward_number: Optional[str], material_id, qa_status: Optional[str],
                     location: Optional[str], received_from: Optional[datetime], received_to: Optional[datetime],
                     has_free_stock: Optional[bool], limit: int, offset: int) -> CCInwardListResponse:
        query, agg = _inward_stock_query(db)
        if inward_number:
            query = query.filter(_contains(Inward.inward_number, inward_number))
        if material_id is not None:
            query = query.filter(Inward.material_id == material_id)
        if qa_status:
            query = query.filter(Inward.qa_status == qa_status.strip().upper())
        if location:
            query = query.filter(_contains(Inward.location, location))
        if received_from is not None:
            query = query.filter(Inward.received_at >= received_from)
        if received_to is not None:
            query = query.filter(Inward.received_at <= received_to)
        if has_free_stock is not None:
            free = func.coalesce(agg.c.free, 0)
            query = query.filter(free > 0 if has_free_stock else free <= 0)
        total = query.count()
        rows = query.order_by(Inward.received_at.desc(), Inward.inward_number.desc()).offset(offset).limit(limit).all()
        return CCInwardListResponse(items=[_inward_stock_out(r) for r in rows], total=total, limit=limit, offset=offset)

    @staticmethod
    def get_inward(db: Session, inward_id) -> CCInwardDetail:
        query, _agg = _inward_stock_query(db)
        row = query.filter(Inward.id == inward_id).first()
        if row is None:
            raise _not_found("Continuous casting inward")
        inward = row[0]
        totals = _ledger_totals(db, Ledger.inward_id == inward.id)                       # C
        adj_in, adj_out = totals.get("ADJUSTMENT_IN", 0), totals.get("ADJUSTMENT_OUT", 0)
        accounted = int(row[3] or 0) + int(row[6] or 0) + int(row[7] or 0)               # remaining + consumed + scrapped
        expected = inward.received_total_length_mm - adj_out + adj_in
        decision = db.query(AuditLog).filter(
            AuditLog.action == "CC_INWARD_QA_DECISION", AuditLog.entity_id == inward.inward_number
        ).order_by(AuditLog.created_at.desc()).first()                                   # D (audit history)
        qa = None if decision is None else CCQADecisionInfo(
            decision=decision.new_value, previous_qa_status=decision.old_value, reason=decision.details,
            decided_by=decision.user_name, decided_at=decision.created_at)
        return _inward_stock_out(
            row, CCInwardDetail, remarks=inward.remarks, created_by=inward.created_by, updated_by=inward.updated_by,
            original_received_length_mm=inward.received_total_length_mm, physical_piece_count=inward.received_piece_count,
            qa_decision=qa, conservation=CCConservation(
                accounted_length_mm=accounted, expected_length_mm=expected, adjustments_in_mm=adj_in,
                adjustments_out_mm=adj_out, consistent=accounted == expected))

    # ============================================================== stock units
    @staticmethod
    def _unit_query(db: Session):
        return (db.query(Unit).join(Inward, Inward.id == Unit.inward_id)
                .join(Material, Material.id == Inward.material_id)
                .options(contains_eager(Unit.inward).contains_eager(Inward.material)))

    @staticmethod
    def list_stock_units(db: Session, *, inward_id, material_id, status_filter: Optional[str], location: Optional[str],
                         on_hold: Optional[bool], available: Optional[bool], parent_unit_id, limit: int,
                         offset: int) -> CCStockUnitListResponse:
        query = ContinuousCastingReadService._unit_query(db)
        if inward_id is not None:
            query = query.filter(Unit.inward_id == inward_id)
        if material_id is not None:
            query = query.filter(Inward.material_id == material_id)
        if status_filter:
            query = query.filter(Unit.status == status_filter.strip().upper())
        if location:
            query = query.filter(_contains(Unit.location, location))
        if on_hold is not None:
            query = query.filter(Unit.status == "ON_HOLD" if on_hold else Unit.status != "ON_HOLD")
        if parent_unit_id is not None:
            query = query.filter(Unit.parent_unit_id == parent_unit_id)
        if available is not None:
            # exactly the conditions of allocation_ineligibility_reason: inward ACCEPTED, unit IN_STOCK, free > 0
            eligible = and_(Inward.qa_status == ALLOCATABLE_QA_STATUS, Unit.status == UNIT_STATUS_IN_STOCK,
                            (Unit.remaining_length_mm - Unit.reserved_length_mm - Unit.issued_length_mm) > 0)
            query = query.filter(eligible if available else not_(eligible))
        total = query.count()
        units = query.order_by(Unit.unit_number).offset(offset).limit(limit).all()
        parents = _parent_numbers(db, units)
        return CCStockUnitListResponse(items=[_unit_out(u, parents) for u in units], total=total, limit=limit,
                                       offset=offset)

    @staticmethod
    def get_stock_unit(db: Session, unit_id) -> CCStockUnitDetail:
        unit = ContinuousCastingReadService._unit_query(db).filter(Unit.id == unit_id).first()
        if unit is None:
            raise _not_found("Stock unit")
        base = _unit_out(unit, _parent_numbers(db, [unit]))
        children = db.query(Unit).filter(Unit.parent_unit_id == unit.id).order_by(Unit.unit_number).all()
        totals = _ledger_totals(db, Ledger.stock_unit_id == unit.id)                     # C
        derived, ledger_remaining = _derive(totals), _derive_remaining(totals)
        consistent = (ledger_remaining == unit.remaining_length_mm and derived["reserved"] == unit.reserved_length_mm
                      and derived["issued"] == unit.issued_length_mm and derived["consumed"] == unit.consumed_length_mm
                      and totals.get("SCRAP", 0) == unit.scrapped_length_mm)
        hold = db.query(Ledger).filter(
            Ledger.stock_unit_id == unit.id, Ledger.movement_type.in_(("HOLD", "HOLD_RELEASE"))
        ).order_by(Ledger.transaction_number.desc()).first()
        allocations = _alloc_query(db).filter(Alloc.stock_unit_id == unit.id).order_by(Alloc.allocation_number).all()
        return CCStockUnitDetail(
            **base.model_dump(),
            children=[CCUnitChild(unit_id=str(c.id), unit_number=c.unit_number, original_length_mm=c.original_length_mm,
                                  remaining_length_mm=c.remaining_length_mm, status=c.status) for c in children],
            net_adjustment_mm=totals.get("ADJUSTMENT_IN", 0) - totals.get("ADJUSTMENT_OUT", 0),
            last_hold_event=None if hold is None else CCLastHold(
                movement_type=hold.movement_type, transaction_number=hold.transaction_number, reason=hold.reason,
                performed_by=hold.performed_by_name, created_at=hold.created_at),
            integrity=CCUnitIntegrity(
                consistent=consistent, ledger_remaining_length_mm=ledger_remaining,
                ledger_reserved_length_mm=derived["reserved"], ledger_issued_length_mm=derived["issued"],
                ledger_consumed_length_mm=derived["consumed"], ledger_scrapped_length_mm=totals.get("SCRAP", 0)),
            allocations=[_alloc_out(*r) for r in allocations])

    # ============================================================== routings / allocations
    @staticmethod
    def list_routings(db: Session, *, wo_number: Optional[str], status_filter: Optional[str],
                      material_source: Optional[str], limit: int, offset: int) -> CCRoutingListResponse:
        query = _routing_rows(db)
        if wo_number:
            query = query.filter(WorkOrder.wo_number == wo_number.strip())
        if status_filter:
            query = query.filter(Routing.status == status_filter.strip().upper())
        if material_source:
            query = query.filter(Routing.material_source == material_source.strip().upper())
        total = query.count()
        rows = query.order_by(WorkOrder.wo_number, Routing.version.desc()).offset(offset).limit(limit).all()
        return CCRoutingListResponse(items=[_routing_out(*r) for r in rows], total=total, limit=limit, offset=offset)

    @staticmethod
    def get_routing(db: Session, routing_id) -> CCRoutingDetail:
        row = _routing_rows(db).filter(Routing.id == routing_id).first()
        if row is None:
            raise _not_found("Continuous casting routing")
        allocations = _alloc_query(db).filter(Alloc.routing_id == routing_id).order_by(Alloc.allocation_number).all()
        return CCRoutingDetail(**_routing_out(*row).model_dump(), allocations=[_alloc_out(*r) for r in allocations])

    @staticmethod
    def list_allocations(db: Session, *, routing_id, wo_number: Optional[str], stock_unit_id, inward_id,
                         status_filter: Optional[str], limit: int, offset: int) -> CCAllocationListResponse:
        query = _alloc_query(db)
        if routing_id is not None:
            query = query.filter(Alloc.routing_id == routing_id)
        if wo_number:
            query = query.filter(WorkOrder.wo_number == wo_number.strip())
        if stock_unit_id is not None:
            query = query.filter(Alloc.stock_unit_id == stock_unit_id)
        if inward_id is not None:
            query = query.filter(Unit.inward_id == inward_id)
        if status_filter:
            query = query.filter(Alloc.status == status_filter.strip().upper())
        total = query.count()
        rows = query.order_by(Alloc.allocation_number).offset(offset).limit(limit).all()
        return CCAllocationListResponse(items=[_alloc_out(*r) for r in rows], total=total, limit=limit, offset=offset)

    # ============================================================== ledger (read-only history)
    @staticmethod
    def list_ledger(db: Session, *, stock_unit_id, inward_id, allocation_id, wo_number: Optional[str], routing_id,
                    movement_type: Optional[str], created_from: Optional[datetime], created_to: Optional[datetime],
                    limit: int, offset: int) -> CCLedgerListResponse:
        query = _ledger_query(db)
        if stock_unit_id is not None:
            query = query.filter(Ledger.stock_unit_id == stock_unit_id)
        if inward_id is not None:
            query = query.filter(Ledger.inward_id == inward_id)
        if allocation_id is not None:
            query = query.filter(Ledger.allocation_id == allocation_id)
        if wo_number:
            query = query.filter(WorkOrder.wo_number == wo_number.strip())
        if routing_id is not None:
            query = query.filter(Routing.id == routing_id)
        if movement_type:
            query = query.filter(Ledger.movement_type == movement_type)
        if created_from is not None:
            query = query.filter(Ledger.created_at >= created_from)
        if created_to is not None:
            query = query.filter(Ledger.created_at <= created_to)
        total = query.count()
        rows = query.order_by(Ledger.transaction_number.desc()).offset(offset).limit(limit).all()
        return CCLedgerListResponse(items=[_ledger_out(r) for r in rows], total=total, limit=limit, offset=offset)

    # ============================================================== cut results
    @staticmethod
    def list_cut_results(db: Session, *, wo_number: Optional[str], routing_id, allocation_id, stock_unit_id,
                         ledger_transaction_number: Optional[str], reconciliation_status: Optional[str],
                         limit: int, offset: int, inward_id=None) -> CCCutResultListResponse:
        query = _cut_query(db)
        if wo_number:
            query = query.filter(WorkOrder.wo_number == wo_number.strip())
        if routing_id is not None:
            query = query.filter(Routing.id == routing_id)
        if allocation_id is not None:
            query = query.filter(Cut.allocation_id == allocation_id)
        if stock_unit_id is not None:
            query = query.filter(Cut.stock_unit_id == stock_unit_id)
        if ledger_transaction_number:
            query = query.filter(Ledger.transaction_number == ledger_transaction_number.strip())
        if reconciliation_status:
            query = query.filter(Cut.reconciliation_status == reconciliation_status.strip().upper())
        if inward_id is not None:
            query = query.filter(Inward.id == inward_id)
        total = query.count()
        rows = query.order_by(Cut.cut_number.desc()).offset(offset).limit(limit).all()
        return CCCutResultListResponse(items=[_cut_out(r) for r in rows], total=total, limit=limit, offset=offset)

    @staticmethod
    def get_cut_result(db: Session, cut_result_id) -> CCCutResultOut:
        row = _cut_query(db).filter(Cut.id == cut_result_id).first()
        if row is None:
            raise _not_found("Cut result")
        return _cut_out(row)

    @staticmethod
    def list_available_cut_consumes(db: Session, *, routing_id, wo_number: Optional[str], limit: int,
                                    offset: int) -> CCCutAvailableListResponse:
        """CUT_CONSUME ledger rows with NO cut result yet, scoped to one routing or one Work Order (never a global
        list), on a CONTINUOUS_CASTING routing that is ACTIVE or SUPERSEDED (what record_cut_result accepts). The
        unique ledger_entry_id decides 'no result yet'; the allocation/unit/routing relationships are the ones the
        record operation validates. No blank count is calculated or suggested."""
        if routing_id is None and not (wo_number and wo_number.strip()):
            raise _bad("routing_id or wo_number is required: the list of CUT_CONSUME transactions is always scoped.")
        query = (db.query(Ledger, Alloc, Routing, WorkOrder, Unit)
                 .join(Alloc, Alloc.id == Ledger.allocation_id)
                 .join(Routing, Routing.id == Alloc.routing_id)
                 .join(WorkOrder, WorkOrder.id == Routing.work_order_id)
                 .join(Unit, Unit.id == Ledger.stock_unit_id)
                 .outerjoin(Cut, Cut.ledger_entry_id == Ledger.id)
                 .filter(Ledger.movement_type == "CUT_CONSUME", Cut.id.is_(None),
                         Ledger.stock_unit_id == Alloc.stock_unit_id,
                         Routing.material_source == MATERIAL_SOURCE_CONTINUOUS_CASTING,
                         Routing.status.in_((ROUTING_ACTIVE, ROUTING_SUPERSEDED))))
        if routing_id is not None:
            query = query.filter(Routing.id == routing_id)
        if wo_number and wo_number.strip():
            query = query.filter(WorkOrder.wo_number == wo_number.strip())
        total = query.count()
        rows = query.order_by(Ledger.transaction_number.desc()).offset(offset).limit(limit).all()
        routing_ids = {r[2].id for r in rows}
        recorded = dict(db.query(Alloc.routing_id, func.coalesce(func.sum(Cut.actual_good_blanks + Cut.rejected_blanks), 0))
                        .select_from(Cut).join(Alloc, Alloc.id == Cut.allocation_id)
                        .filter(Alloc.routing_id.in_(routing_ids)).group_by(Alloc.routing_id).all()) if routing_ids else {}
        items = []
        for ledger, alloc, routing, wo, unit in rows:
            done = int(recorded.get(routing.id, 0))
            items.append(CCCutAvailableOut(
                ledger_transaction_number=ledger.transaction_number, consumed_length_mm=ledger.length_mm,
                allocation_id=str(alloc.id), allocation_number=alloc.allocation_number, stock_unit_id=str(unit.id),
                stock_unit_number=unit.unit_number, routing_id=str(routing.id), routing_version=routing.version,
                routing_status=routing.status, wo_number=wo.wo_number, created_at=ledger.created_at,
                planned_blanks=routing.planned_blanks, blank_length_mm=routing.blank_length_mm, kerf_mm=routing.kerf_mm,
                planned_cuts=routing.planned_cuts, routing_blanks_recorded=done,
                routing_blanks_remaining_in_plan=max(routing.planned_blanks - done, 0)))
        return CCCutAvailableListResponse(items=items, total=total, limit=limit, offset=offset)

    # ============================================================== gate status
    @staticmethod
    def get_gate_status(db: Session, wo_number: str) -> CCGateStatus:
        """What the Phase 10 gate would do for this Work Order right now. Reuses the gate's own predicates
        (active_china_routing, usable_good_blanks); only the final capacity subtraction mirrors the gate's
        comparison, and tests pin it to the real gate. Read-only: it never produces, moves, reserves or cuts."""
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number.strip()).first()
        if wo is None:
            raise _not_found(f"Work Order '{wo_number}'")
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        routing = ContinuousCastingGateService.active_china_routing(db, wo)
        if routing is None:
            if getattr(wo, "casting_process", None) == "CONTINUOUS":
                return CCGateStatus(
                    wo_number=wo.wo_number, gate_applies=True, material_source="CONTINUOUS_CASTING",
                    first_route_stage=routes[0].stage if routes else None, verdict="BLOCKED_NO_ACTIVE_ROUTING",
                    reasons=["Work Order is marked for Continuous Casting but has no active Continuous Casting routing. "
                             "Create and activate a routing in Continuous Casting Planning before production."])
            other = db.query(Routing).filter(Routing.work_order_id == wo.id, Routing.status == ROUTING_ACTIVE).first()
            return CCGateStatus(
                wo_number=wo.wo_number, gate_applies=False, material_source=other.material_source if other else None,
                first_route_stage=routes[0].stage if routes else None, verdict="NOT_GATED",
                reasons=["No ACTIVE continuous-casting routing: the Work Order uses the existing F1 production flow, "
                         "unchanged, and the China material gate does not apply."])
        planned = routing.planned_blanks
        recorded = int(db.query(func.coalesce(func.sum(Cut.actual_good_blanks + Cut.rejected_blanks), 0)).select_from(
            Cut).join(Alloc, Alloc.id == Cut.allocation_id).filter(Alloc.routing_id == routing.id).scalar())
        common = dict(wo_number=wo.wo_number, material_source=routing.material_source, routing_id=str(routing.id),
                      routing_version=routing.version, planned_blanks=planned, recorded_blanks=recorded)
        if not routes:
            return CCGateStatus(**common, gate_applies=False, verdict="NOT_GATED",
                                reasons=["The Work Order has no released route stages, so the gate does not apply yet."])
        first_stage = routes[0].stage
        wip = db.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == first_stage).first()
        good, rejected = (wip.ok_qty or 0, wip.rejected_qty or 0) if wip else (0, 0)
        stage = dict(first_route_stage=first_stage, first_stage_good_qty=good, first_stage_rejected_qty=rejected)
        if first_stage.strip().upper() == "F1":
            return CCGateStatus(**common, **stage, gate_applies=True, first_stage_valid=False,
                                verdict="BLOCKED_F1_FIRST_STAGE",
                                reasons=["Continuous-casting stock bypasses F1, but the released route still starts at "
                                         "F1: first-stage production is rejected until the Work Order is released with "
                                         "its first downstream stage first."])
        usable = ContinuousCastingGateService.usable_good_blanks(db, wo, routing)
        capacity = max(usable - (good + rejected), 0)
        if usable == 0:
            verdict, reasons = "BLOCKED_NO_USABLE_BLANKS", [
                "No RECONCILED cut result of the ACTIVE routing has delivered usable good blanks yet"
                + (f" ({recorded} blank(s) recorded, none usable)." if recorded else ".")]
        elif capacity > 0:
            verdict, reasons = "ALLOWED_UP_TO", [
                f"{usable} usable good blank(s), {good + rejected} already good or rejected at '{first_stage}': "
                f"up to {capacity} more piece(s) can be produced there."]
        else:
            verdict, reasons = "EXHAUSTED", [
                f"All {usable} usable good blank(s) are already good or rejected at '{first_stage}': any further "
                f"first-stage production is rejected until another cut result is reconciled."]
        return CCGateStatus(**common, **stage, gate_applies=True, first_stage_valid=True, usable_good_blanks=usable,
                            remaining_capacity=capacity, verdict=verdict, reasons=reasons)

    # ============================================================== traceability
    @staticmethod
    def _trace_units(db: Session, units, allocation_rows) -> list:
        parents = _parent_numbers(db, units)
        by_unit = {}
        for row in allocation_rows:
            by_unit.setdefault(row[3].id, []).append(_alloc_out(*row))
        return [CCTraceUnit(
            unit_id=str(u.id), unit_number=u.unit_number, parent_unit_number=parents.get(u.parent_unit_id),
            original_length_mm=u.original_length_mm, remaining_length_mm=u.remaining_length_mm,
            reserved_length_mm=u.reserved_length_mm, issued_length_mm=u.issued_length_mm,
            consumed_length_mm=u.consumed_length_mm, scrapped_length_mm=u.scrapped_length_mm,
            free_length_mm=_free(u.remaining_length_mm, u.reserved_length_mm, u.issued_length_mm), status=u.status,
            allocations=by_unit.get(u.id, [])) for u in units]

    @staticmethod
    def trace_inward(db: Session, inward_id) -> CCTraceInward:
        service = ContinuousCastingReadService
        detail = service.get_inward(db, inward_id)
        units_total = db.query(func.count(Unit.id)).filter(Unit.inward_id == inward_id).scalar()
        units = db.query(Unit).filter(Unit.inward_id == inward_id).order_by(Unit.unit_number).limit(TRACE_UNIT_CAP + 1).all()
        units_cut = len(units) > TRACE_UNIT_CAP
        units = units[:TRACE_UNIT_CAP]
        unit_ids = [u.id for u in units]
        alloc_query = _alloc_query(db).filter(Alloc.stock_unit_id.in_(unit_ids)) if unit_ids else None
        allocations_total = alloc_query.count() if alloc_query is not None else 0
        alloc_rows = (alloc_query.order_by(Alloc.allocation_number).limit(TRACE_ALLOCATION_CAP + 1).all()
                      if alloc_query is not None else [])
        allocs_cut = len(alloc_rows) > TRACE_ALLOCATION_CAP
        alloc_rows = alloc_rows[:TRACE_ALLOCATION_CAP]
        wo_roll = {}
        for a, routing, wo, _unit, _inward in alloc_rows:
            r = wo_roll.setdefault(wo.wo_number, dict(versions=set(), active=None, n=0, planned=0, reserved=0,
                                                      issued=0, consumed=0))
            r["versions"].add(routing.version)
            if routing.status == ROUTING_ACTIVE:
                r["active"] = routing.version
            r["n"] += 1
            r["planned"] += a.planned_length_mm
            r["reserved"] += a.reserved_length_mm
            r["issued"] += a.issued_length_mm
            r["consumed"] += a.consumed_length_mm
        cuts = service.list_cut_results(db, wo_number=None, routing_id=None, allocation_id=None, stock_unit_id=None,
                                        ledger_transaction_number=None, reconciliation_status=None,
                                        limit=TRACE_CUT_RESULT_CAP, offset=0, inward_id=inward_id)
        ledger_page = service.list_ledger(db, stock_unit_id=None, inward_id=inward_id, allocation_id=None,
                                          wo_number=None, routing_id=None, movement_type=None, created_from=None,
                                          created_to=None, limit=TRACE_LEDGER_RECENT, offset=0)
        return CCTraceInward(
            inward=detail, units=service._trace_units(db, units, alloc_rows),
            work_orders=[CCTraceWorkOrderRollup(
                wo_number=n, routing_versions=sorted(r["versions"]), active_routing_version=r["active"],
                allocation_count=r["n"], planned_length_mm=r["planned"], reserved_length_mm=r["reserved"],
                issued_length_mm=r["issued"], consumed_length_mm=r["consumed"]) for n, r in sorted(wo_roll.items())],
            cut_results=cuts.items, ledger_totals_by_movement=_ledger_totals(db, Ledger.inward_id == inward_id),
            recent_ledger=ledger_page.items, units_total=int(units_total), allocations_total=int(allocations_total),
            cut_results_total=cuts.total, ledger_rows_total=ledger_page.total,
            truncated=bool(units_cut or allocs_cut or cuts.total > TRACE_CUT_RESULT_CAP
                           or ledger_page.total > TRACE_LEDGER_RECENT),
            limitations=TRACE_LIMITATIONS)

    @staticmethod
    def trace_work_order(db: Session, wo_number: str) -> CCTraceWorkOrder:
        service = ContinuousCastingReadService
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number.strip()).first()
        if wo is None:
            raise _not_found(f"Work Order '{wo_number}'")
        routings = [_routing_out(*r) for r in _routing_rows(db).filter(Routing.work_order_id == wo.id)
                    .order_by(Routing.version.desc()).all()]
        alloc_query = _alloc_query(db).filter(Routing.work_order_id == wo.id)
        allocations_total = alloc_query.count()
        rows = alloc_query.order_by(Alloc.allocation_number).limit(TRACE_ALLOCATION_CAP + 1).all()
        allocs_cut = len(rows) > TRACE_ALLOCATION_CAP
        rows = rows[:TRACE_ALLOCATION_CAP]
        units = {}
        inward_roll = {}
        for a, _routing, _wo, unit, inward in rows:
            units[unit.id] = unit
            r = inward_roll.setdefault(inward.id, dict(number=inward.inward_number, units=set(), n=0, planned=0,
                                                       reserved=0, issued=0, consumed=0))
            r["units"].add(unit.id)
            r["n"] += 1
            r["planned"] += a.planned_length_mm
            r["reserved"] += a.reserved_length_mm
            r["issued"] += a.issued_length_mm
            r["consumed"] += a.consumed_length_mm
        cuts = service.list_cut_results(db, wo_number=wo.wo_number, routing_id=None, allocation_id=None,
                                        stock_unit_id=None, ledger_transaction_number=None,
                                        reconciliation_status=None, limit=TRACE_CUT_RESULT_CAP, offset=0)
        active = ContinuousCastingGateService.active_china_routing(db, wo)
        return CCTraceWorkOrder(
            wo_number=wo.wo_number, work_order_id=str(wo.id), routings=routings,
            active_routing_version=next((r.version for r in routings if r.is_active), None),
            allocations=[_alloc_out(*r) for r in rows],
            inwards=[CCTraceInwardRollup(
                inward_id=str(i), inward_number=r["number"], unit_count=len(r["units"]), allocation_count=r["n"],
                planned_length_mm=r["planned"], reserved_length_mm=r["reserved"], issued_length_mm=r["issued"],
                consumed_length_mm=r["consumed"]) for i, r in sorted(inward_roll.items(), key=lambda kv: kv[1]["number"])],
            units=service._trace_units(db, sorted(units.values(), key=lambda u: u.unit_number), rows),
            cut_results=cuts.items,
            usable_good_blanks=(ContinuousCastingGateService.usable_good_blanks(db, wo, active)
                                if active is not None else None),
            allocations_total=int(allocations_total), cut_results_total=cuts.total,
            truncated=bool(allocs_cut or cuts.total > TRACE_CUT_RESULT_CAP), limitations=TRACE_LIMITATIONS)
