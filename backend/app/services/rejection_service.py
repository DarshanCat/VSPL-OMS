from typing import Optional, List
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func as sa_func
from app.models.nc import NCRecord
from app.models.rejection_disposition import RejectionDisposition
from app.models.rejection_type import RejectionType
from app.models.conversion import Conversion
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.order import Order, Customer
from app.models.audit import AuditLog
from app.models.user import User
from app.core.roles import PLANNING_ROLES, QUALITY_APPROVAL_ROLES, MELTING_ENTRY_ROLES
from app.schemas.rejection import (
    ExcessNonMovingCreate, DispositionCreate, DispositionResponse, DispositionOut,
    RejectionListItem, RejectionDetail, RejectionSourceBlock, RejectionBalance,
    RejectionOutcomeBreakdown, RejectionSummary, CWODetail,
    MeltingEntryCreate, MeltingEntryResponse,
    ReplacementCreate, ReplacementResponse,
    RejectionTypeCreate, RejectionTypeUpdate, RejectionTypeOut
)
from app.services.oms_integration_service import OMSIntegrationService, calculate_stage_targets
from app.services.conversion_mapping_service import ConversionMappingService

# Actions that create a brand-new destination Work Order -- these are planning/release
# decisions (same class of action as WO release / direct conversion).
WO_CREATING_ACTIONS = ("CONVERT_PART", "SAME_PART", "CWO")
# Actions that do not create a new WO -- these are quality/oversight decisions (same
# class of action as NC disposition).
TERMINAL_ACTIONS = ("SCRAP", "DEVIATION_ACCEPT")
VALID_ACTIONS = WO_CREATING_ACTIONS + TERMINAL_ACTIONS
VALID_SOURCE_TYPES = ("EXCESS_PRODUCTION", "NON_MOVING")
ALL_ROUTE_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]


def _consumed_qty(db: Session, nc_id) -> int:
    total = db.query(sa_func.coalesce(sa_func.sum(RejectionDisposition.quantity), 0)).filter(
        RejectionDisposition.nc_record_id == nc_id
    ).scalar()
    return int(total or 0)


def _require_role(current_user: Optional[User], allowed: tuple, action_label: str):
    if current_user is None or current_user.role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role.value if current_user else 'anonymous'}' is not authorized to {action_label}."
        )


def validate_active_rejection_type(db: Session, code: Optional[str]) -> None:
    """Backend-authoritative gate for Production Entry / Move Parts: a NEW rejection
    transaction (rejected_quantity > 0) must always select an existing, ACTIVE
    RejectionType by its code -- never arbitrary free text. Unconditionally
    mandatory (not backward-compatible/optional) -- the Rejection Type master is
    never actually empty in a real deployment because `seed_database_if_empty`
    (app/services/seed_service.py) seeds a default set of types covering every
    historically-used defect code, in every environment including production, so
    Quality never has to manually create the first type before this gate works.

    This has no effect on historical data: NCRecord.defect_code is a plain string
    column, never rewritten by this check or by anything in the RejectionType
    master -- a historical row keeps displaying exactly the code it was recorded
    with, active/inactive/deleted-type or not."""
    if not code or not code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A Rejection Type is required when Rejected Qty > 0."
        )
    rt = db.query(RejectionType).filter(RejectionType.code == code.strip().upper()).first()
    if not rt or not rt.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rejection Type '{code}' does not exist or is inactive."
        )


def _rejection_type_out(rt: RejectionType) -> RejectionTypeOut:
    return RejectionTypeOut(
        id=str(rt.id), code=rt.code, name=rt.name, description=rt.description,
        is_active=rt.is_active, created_by=rt.created_by, updated_by=rt.updated_by,
        created_at=rt.created_at, updated_at=rt.updated_at
    )


class RejectionTypeService:
    """The dedicated Rejection Type master. Deliberately kept inside the existing
    rejection subsystem (this file / rejection.py / schemas/rejection.py) rather
    than as a new module -- it is part of Rejection Tracking, not a separate
    concern. `code` is the same natural key already used as NCRecord.defect_code;
    historical rows are never rewritten, only validated against going forward
    (see validate_active_rejection_type)."""

    @staticmethod
    def list_types(db: Session, include_inactive: bool = False) -> List[RejectionTypeOut]:
        q = db.query(RejectionType)
        if not include_inactive:
            q = q.filter(RejectionType.is_active.is_(True))
        return [_rejection_type_out(rt) for rt in q.order_by(RejectionType.name).all()]

    @staticmethod
    def create_type(db: Session, req: RejectionTypeCreate, current_user: Optional[User] = None) -> RejectionTypeOut:
        code = req.code.strip().upper()
        if db.query(RejectionType).filter(RejectionType.code == code).first():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Rejection Type code '{code}' already exists.")
        actor = current_user.full_name if current_user else "System"
        rt = RejectionType(
            code=code, name=req.name.strip(), description=req.description,
            is_active=True, created_by=actor, updated_by=actor,
        )
        db.add(rt)
        db.flush()
        db.add(AuditLog(
            user_id=current_user.id if current_user else None, user_name=actor,
            action="REJECTION_TYPE_CREATED", entity="RejectionType", entity_id=code,
            new_value=f"Name: {rt.name}"
        ))
        db.commit()
        db.refresh(rt)
        return _rejection_type_out(rt)

    @staticmethod
    def update_type(db: Session, req: RejectionTypeUpdate, current_user: Optional[User] = None) -> RejectionTypeOut:
        rt = db.query(RejectionType).filter(RejectionType.id == req.id).first()
        if not rt:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rejection Type not found.")
        old_active = rt.is_active
        if req.name is not None:
            rt.name = req.name.strip()
        if req.description is not None:
            rt.description = req.description
        if req.is_active is not None:
            # Never physically deleted -- historical NCRecord.defect_code values
            # keep resolving/displaying regardless of active status.
            rt.is_active = req.is_active
        rt.updated_by = current_user.full_name if current_user else "System"
        db.add(AuditLog(
            user_id=current_user.id if current_user else None, user_name=rt.updated_by,
            action="REJECTION_TYPE_UPDATED", entity="RejectionType", entity_id=rt.code,
            old_value=f"Active: {old_active}", new_value=f"Active: {rt.is_active}"
        ))
        db.commit()
        db.refresh(rt)
        return _rejection_type_out(rt)


class RejectionService:
    @staticmethod
    def list_rejections(
        db: Session,
        search: Optional[str] = None,
        wo_number: Optional[str] = None,
        oar_number: Optional[str] = None,
        part_number: Optional[str] = None,
        customer_code: Optional[str] = None,
        stage: Optional[str] = None,
        source_type: Optional[str] = None,
        status_filter: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 500,
        offset: int = 0
    ) -> List[RejectionListItem]:
        query = db.query(NCRecord).join(WorkOrder, NCRecord.work_order_id == WorkOrder.id).join(Order).join(Customer)

        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    NCRecord.nc_number.ilike(s),
                    WorkOrder.wo_number.ilike(s),
                    Order.oar_number.ilike(s),
                    Customer.name.ilike(s)
                )
            )
        if wo_number:
            query = query.filter(WorkOrder.wo_number == wo_number.strip())
        if oar_number:
            query = query.filter(Order.oar_number == oar_number.strip())
        if customer_code:
            query = query.filter(Customer.customer_code == customer_code.strip().upper())
        if stage:
            query = query.filter(NCRecord.stage == stage.strip().upper())
        if source_type:
            query = query.filter(NCRecord.source_type == source_type.strip().upper())
        if status_filter:
            query = query.filter(NCRecord.status == status_filter.strip())
        if date_from:
            query = query.filter(NCRecord.date_raised >= date_from)
        if date_to:
            query = query.filter(NCRecord.date_raised <= date_to)

        records = query.order_by(NCRecord.date_raised.desc()).offset(offset).limit(limit).all()

        results = []
        for r in records:
            wo = r.work_order
            order = wo.order if wo else None
            part_no = order.part.part_number if (order and order.part) else None
            if part_number and part_no != part_number.strip().upper():
                continue
            consumed = _consumed_qty(db, r.id)
            results.append(RejectionListItem(
                nc_number=r.nc_number,
                wo_number=wo.wo_number if wo else "N/A",
                oar_number=order.oar_number if order else None,
                customer_code=order.customer.customer_code if (order and order.customer) else None,
                customer_name=order.customer.name if (order and order.customer) else None,
                part_number=part_no,
                stage=r.stage,
                source_type=r.source_type or "REJECTION",
                qty=r.qty,
                consumed_qty=consumed,
                remaining_qty=max(r.qty - consumed, 0),
                reason=r.defect_code,
                status=r.status or "Open",
                disposition=r.disposition,
                date_raised=r.date_raised or datetime.now()
            ))
        return results

    @staticmethod
    def get_rejection_detail(db: Session, nc_number: str) -> Optional[RejectionDetail]:
        r = db.query(NCRecord).filter(NCRecord.nc_number == nc_number.strip()).first()
        if not r:
            return None

        wo = r.work_order
        order = wo.order if wo else None

        dispositions = (
            db.query(RejectionDisposition)
            .filter(RejectionDisposition.nc_record_id == r.id)
            .order_by(RejectionDisposition.created_at.asc())
            .all()
        )

        history = []
        outcome = RejectionOutcomeBreakdown()
        consumed = 0
        for d in dispositions:
            conv_wo_num = d.conversion.conversion_wo_number if d.conversion else d.destination_wo_number
            history.append(DispositionOut(
                id=str(d.id),
                action=d.action,
                quantity=d.quantity,
                destination_wo_number=d.destination_wo_number,
                destination_part_number=d.destination_part_number,
                destination_customer_code=d.destination_customer_code,
                conversion_wo_number=conv_wo_num,
                authorized_by_name=d.authorized_by_name,
                remarks=d.remarks,
                created_at=d.created_at or datetime.now(),
                melting_status=d.melting_status,
                melting_destination=d.melting_destination,
                melting_sent_by_name=d.melting_sent_by_name,
                melting_sent_at=d.melting_sent_at,
                melting_remarks=d.melting_remarks
            ))
            consumed += d.quantity
            if d.action == "CONVERT_PART":
                outcome.another_part_qty += d.quantity
            elif d.action == "SAME_PART":
                outcome.same_part_qty += d.quantity
            elif d.action == "CWO":
                outcome.cwo_qty += d.quantity
            elif d.action == "SCRAP":
                outcome.scrap_qty += d.quantity
            elif d.action == "DEVIATION_ACCEPT":
                outcome.deviation_accept_qty += d.quantity

        outcome.remaining_qty = max(r.qty - consumed, 0)

        return RejectionDetail(
            source=RejectionSourceBlock(
                nc_number=r.nc_number,
                wo_number=wo.wo_number if wo else "N/A",
                oar_number=order.oar_number if order else None,
                part_number=order.part.part_number if (order and order.part) else None,
                customer_code=order.customer.customer_code if (order and order.customer) else None,
                customer_name=order.customer.name if (order and order.customer) else None,
                production_stage=r.stage,
                source_type=r.source_type or "REJECTION",
                original_quantity=r.qty,
                reason=r.defect_code,
                responsibility=r.responsibility,
                date_raised=r.date_raised or datetime.now()
            ),
            disposition_history=history,
            balance=RejectionBalance(
                original_qty=r.qty,
                consumed_qty=consumed,
                remaining_qty=max(r.qty - consumed, 0)
            ),
            final_outcome=outcome,
            status=r.status or "Open"
        )

    @staticmethod
    def create_excess_or_non_moving(db: Session, req: ExcessNonMovingCreate, current_user: Optional[User] = None) -> RejectionListItem:
        source_type = req.source_type.strip().upper()
        if source_type not in VALID_SOURCE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source_type must be one of {VALID_SOURCE_TYPES}."
            )

        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        count = db.query(NCRecord).count()
        nc_num = f"NC-{count + 1:05d}"

        record = NCRecord(
            nc_number=nc_num,
            work_order_id=wo.id,
            stage=(req.stage or wo.current_stage or "F1").strip().upper(),
            defect_code=req.reason.strip(),
            qty=req.qty,
            root_cause=req.reason,
            disposition=None,
            responsibility="Planning" if source_type == "EXCESS_PRODUCTION" else "Sales/Dispatch",
            status="Open",
            source_type=source_type,
            remarks=req.remarks
        )
        db.add(record)

        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Planner",
            action=f"REJECTION_{source_type}_CREATE",
            entity="NCRecord",
            entity_id=nc_num,
            new_value=f"WO: {wo.wo_number}, Qty: {req.qty}, Source: {source_type}",
            details=req.reason
        )
        db.add(audit)
        db.commit()
        db.refresh(record)

        order = wo.order
        return RejectionListItem(
            nc_number=record.nc_number,
            wo_number=wo.wo_number,
            oar_number=order.oar_number if order else None,
            customer_code=order.customer.customer_code if (order and order.customer) else None,
            customer_name=order.customer.name if (order and order.customer) else None,
            part_number=order.part.part_number if (order and order.part) else None,
            stage=record.stage,
            source_type=record.source_type,
            qty=record.qty,
            consumed_qty=0,
            remaining_qty=record.qty,
            reason=record.defect_code,
            status=record.status,
            disposition=record.disposition,
            date_raised=record.date_raised or datetime.now()
        )

    @staticmethod
    def create_disposition(db: Session, req: DispositionCreate, current_user: Optional[User] = None) -> DispositionResponse:
        action = req.action.strip().upper()
        if action not in VALID_ACTIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"action must be one of {VALID_ACTIONS}."
            )

        # Backend-enforced authorization -- never trust the frontend to have already
        # restricted which action a user could submit.
        if action in WO_CREATING_ACTIONS:
            _require_role(current_user, PLANNING_ROLES, f"create a '{action}' disposition")
        else:
            _require_role(current_user, QUALITY_APPROVAL_ROLES, f"create a '{action}' disposition")

        record = db.query(NCRecord).filter(NCRecord.nc_number == req.nc_number.strip()).with_for_update().first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rejection Tracking record '{req.nc_number}' not found."
            )

        consumed = _consumed_qty(db, record.id)
        remaining = record.qty - consumed
        if req.quantity > remaining:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot disposition {req.quantity} pieces. Only {remaining} pieces remain undispositioned on '{record.nc_number}' (source qty {record.qty}, already consumed {consumed})."
            )

        conversion_id = None
        destination_wo_number = None
        destination_part_number = None

        if action in WO_CREATING_ACTIONS:
            if not req.destination_oar_number or not req.entry_stage or not req.conversion_wo_number:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"destination_oar_number, entry_stage, and conversion_wo_number are required for action '{action}'."
                )

            cwo_num = req.conversion_wo_number.strip()
            existing_wo = db.query(WorkOrder).filter(WorkOrder.wo_number == cwo_num).first()
            if existing_wo:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Conversion WO ID '{cwo_num}' already exists. Supply a unique conversion WO name."
                )

            dest_order = db.query(Order).filter(Order.oar_number == req.destination_oar_number.strip()).first()
            if not dest_order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Destination OAR '{req.destination_oar_number}' not found."
                )

            wo = record.work_order
            source_part = wo.order.part if (wo and wo.order) else None
            dest_part = dest_order.part
            if not source_part or not dest_part:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Could not resolve source or destination part for this conversion."
                )
            # Backend-authoritative destination-part validation -- never trust a
            # frontend dropdown to have already filtered this. Same-part conversion is
            # never implicitly allowed just because source and destination match; it
            # requires its own ACTIVE mapping row like any other pair.
            if not ConversionMappingService.is_conversion_allowed(db, source_part.id, dest_part.id, action):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Destination part '{dest_part.part_number}' is not an approved conversion for source part '{source_part.part_number}'."
                )

            entry_stage = req.entry_stage.strip().upper()

            # This is a disposition of already-rejected material (StageWIP.rejected_qty),
            # NOT a mid-route conversion of movable good WIP (StageWIP.available_wip) --
            # the two are deliberately kept separate ledgers (see production_service.py's
            # "Do NOT fake WIP" rule: rejected quantity never becomes movable WIP). So,
            # unlike OperationsService.create_conversion, there is no source StageWIP to
            # debit here; the source of truth for what has been consumed is this
            # RejectionDisposition ledger against the immutable NCRecord.qty.
            new_wo = WorkOrder(
                wo_number=cwo_num,
                order_id=dest_order.id,
                physical_wo_qty=req.quantity,
                current_stage=entry_stage,
                projected_final_good=req.quantity,
                shortfall="No",
                status=WOStatus.IN_PRODUCTION,
                released_by=current_user.full_name if current_user else "Planner",
                release_date=datetime.now()
            )
            db.add(new_wo)
            db.flush()

            entry_idx = ALL_ROUTE_STAGES.index(entry_stage) if entry_stage in ALL_ROUTE_STAGES else 0
            route_stages = ALL_ROUTE_STAGES[entry_idx:]
            targets = calculate_stage_targets(req.quantity, route=route_stages)
            for seq, stg in enumerate(route_stages, start=1):
                db.add(WORoute(
                    work_order_id=new_wo.id,
                    stage=stg,
                    sequence=seq,
                    stage_target_qty=targets.get(stg, req.quantity),
                    cumulative_ent_qty=req.quantity if seq == 1 else 0,
                    cumulative_inproc_qty=req.quantity if seq == 1 else 0,
                    stage_status="In-Progress" if seq == 1 else "Pending"
                ))

            db.add(StageWIP(
                work_order_id=new_wo.id,
                stage=entry_stage,
                ent_qty=req.quantity,
                ok_qty=0,
                inproc_qty=req.quantity,
                onhand_qty=0,
                rejected_qty=0,
                received_qty=req.quantity,
                available_wip=req.quantity,
                moved_out_qty=0
            ))
            OMSIntegrationService.recompute_work_order(db, new_wo)

            conv = Conversion(
                conversion_wo_number=cwo_num,
                source_wo_id=wo.id,
                destination_order_id=dest_order.id,
                conversion_wo_id=new_wo.id,
                entry_stage=entry_stage,
                quantity=req.quantity,
                reason=req.reason,
                planner=current_user.full_name if current_user else "Planner",
                nc_record_id=record.id
            )
            db.add(conv)
            db.flush()
            conversion_id = conv.id
            destination_wo_number = cwo_num
            destination_part_number = dest_order.part.part_number if dest_order.part else None

        disposition = RejectionDisposition(
            nc_record_id=record.id,
            action=action,
            quantity=req.quantity,
            destination_wo_number=destination_wo_number,
            destination_part_number=destination_part_number,
            destination_customer_code=req.destination_customer_code,
            conversion_id=conversion_id,
            authorized_by_id=current_user.id if current_user else None,
            authorized_by_name=current_user.full_name if current_user else "System",
            remarks=req.remarks or req.reason
        )
        db.add(disposition)

        new_remaining = remaining - req.quantity
        if new_remaining <= 0 and record.status != "Closed":
            record.status = "Closed"
            record.date_closed = datetime.now()
        if record.disposition is None or action in WO_CREATING_ACTIONS:
            record.disposition = action

        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "System",
            action=f"REJECTION_DISPOSITION_{action}",
            entity="NCRecord",
            entity_id=record.nc_number,
            old_value=f"Remaining before: {remaining}",
            new_value=f"Action: {action}, Qty: {req.quantity}, Remaining after: {new_remaining}"
                      + (f", Destination WO: {destination_wo_number}" if destination_wo_number else ""),
            details=req.reason
        )
        db.add(audit)

        db.commit()

        return DispositionResponse(
            success=True,
            nc_number=record.nc_number,
            action=action,
            quantity=req.quantity,
            remaining_qty=max(new_remaining, 0),
            conversion_wo_number=destination_wo_number,
            message=f"Recorded {action} disposition of {req.quantity} pcs against '{record.nc_number}'."
                    + (f" New Work Order '{destination_wo_number}' created." if destination_wo_number else "")
        )

    @staticmethod
    def create_replacement(db: Session, req: ReplacementCreate, current_user: Optional[User] = None) -> ReplacementResponse:
        """Quality-controlled: 'Replacement Required'. Raises a brand-new Work Order
        against the SAME OAR as the original, against the same RejectionDisposition
        ledger/NCRecord.qty balance every other disposition action consumes -- but,
        unlike CONVERT_PART/SAME_PART/CWO, it never sets released_by/release_date (no
        automatic release) and never requires a Conversion Part Mapping approval (it is
        the same part replacing rejected material, not a conversion to a different
        destination). The original WO's history, target, and route are NEVER modified.
        A replacement WO must go through the full Engineering Release -> Manufacturing
        Release -> WO Release chain like any other WO before it can be produced --
        enforced by ProductionService._enforce_release_gate and
        OperationsService.release_work_order via WorkOrder.is_replacement."""
        _require_role(current_user, QUALITY_APPROVAL_ROLES, "approve a replacement WO")

        record = db.query(NCRecord).filter(NCRecord.nc_number == req.nc_number.strip()).with_for_update().first()
        if not record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rejection Tracking record '{req.nc_number}' not found."
            )

        consumed = _consumed_qty(db, record.id)
        remaining = record.qty - consumed
        if req.quantity > remaining:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot replace {req.quantity} pieces. Only {remaining} pieces remain undispositioned on '{record.nc_number}' (source qty {record.qty}, already consumed {consumed})."
            )

        original_wo = record.work_order
        if not original_wo:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not resolve the original Work Order for this record.")

        # Atomic lock on the Order to prevent concurrent over-recovery
        order = db.query(Order).filter(Order.id == original_wo.order_id).with_for_update().first()
        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order associated with Work Order not found.")

        # Compute authoritative OAR genealogy and shortfall across all WOs
        from app.services.work_order_service import WorkOrderService
        oar_summary = WorkOrderService.build_oar_summary(db, order)
        total_good_produced = oar_summary.oar_fulfilled
        max_recoverable = oar_summary.oar_shortfall

        if req.quantity > max_recoverable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot create replacement WO for {req.quantity} pieces. Maximum recoverable shortfall for OAR '{order.oar_number}' is {max_recoverable} pieces (Order Qty: {order.po_qty}, Good Produced: {total_good_produced})."
            )

        # Same numbering convention as order intake / conversion WOs: parse-max-and-
        # increment against the real column, never a separate counter table.
        max_wo_num = 1000
        for (existing_num,) in db.query(WorkOrder.wo_number).all():
            if existing_num and existing_num.startswith("WO-") and existing_num[3:].isdigit():
                max_wo_num = max(max_wo_num, int(existing_num[3:]))
        new_wo_num = f"WO-{max_wo_num + 1}"

        replacement_wo = WorkOrder(
            wo_number=new_wo_num,
            order_id=original_wo.order_id,  # SAME OAR
            physical_wo_qty=req.quantity,
            current_stage="F1",
            projected_final_good=req.quantity,
            shortfall="No",
            status=WOStatus.IN_PRODUCTION,
            source_wo_id=original_wo.id,
            is_replacement=True,
            replacement_reason=req.reason.strip(),
        )
        db.add(replacement_wo)
        db.flush()

        targets = calculate_stage_targets(req.quantity, route=ALL_ROUTE_STAGES)
        for seq, stg in enumerate(ALL_ROUTE_STAGES, start=1):
            db.add(WORoute(
                work_order_id=replacement_wo.id, stage=stg, sequence=seq,
                stage_target_qty=targets.get(stg, req.quantity),
                cumulative_ent_qty=req.quantity if seq == 1 else 0,
                cumulative_inproc_qty=req.quantity if seq == 1 else 0,
                stage_status="In-Progress" if seq == 1 else "Pending"
            ))
        db.add(StageWIP(
            work_order_id=replacement_wo.id, stage="F1", ent_qty=req.quantity,
            ok_qty=0, inproc_qty=req.quantity, onhand_qty=0, rejected_qty=0,
            received_qty=req.quantity, available_wip=req.quantity, moved_out_qty=0
        ))
        OMSIntegrationService.recompute_work_order(db, replacement_wo)

        conv = Conversion(
            conversion_wo_number=new_wo_num,
            source_wo_id=original_wo.id,
            destination_order_id=original_wo.order_id,
            conversion_wo_id=replacement_wo.id,
            entry_stage="F1",
            quantity=req.quantity,
            reason=req.reason,
            planner=current_user.full_name if current_user else "Quality",
            nc_record_id=record.id
        )
        db.add(conv)
        db.flush()

        disposition = RejectionDisposition(
            nc_record_id=record.id,
            action="REPLACEMENT",
            quantity=req.quantity,
            destination_wo_number=new_wo_num,
            destination_part_number=original_wo.order.part.part_number if original_wo.order and original_wo.order.part else None,
            conversion_id=conv.id,
            authorized_by_id=current_user.id if current_user else None,
            authorized_by_name=current_user.full_name if current_user else "System",
            remarks=req.remarks or req.reason
        )
        db.add(disposition)

        new_remaining = remaining - req.quantity
        if new_remaining <= 0 and record.status != "Closed":
            record.status = "Closed"
            record.date_closed = datetime.now()
        if record.disposition is None:
            record.disposition = "REPLACEMENT"

        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "System",
            action="REJECTION_DISPOSITION_REPLACEMENT",
            entity="NCRecord",
            entity_id=record.nc_number,
            old_value=f"Source WO: {original_wo.wo_number}, Remaining before: {remaining}",
            new_value=f"Replacement WO: {new_wo_num}, Qty: {req.quantity}, Remaining after: {new_remaining}",
            details=req.reason
        )
        db.add(audit)

        db.commit()
        db.refresh(replacement_wo)

        order = original_wo.order
        return ReplacementResponse(
            success=True,
            nc_number=record.nc_number,
            replacement_wo_number=new_wo_num,
            original_wo_number=original_wo.wo_number,
            oar_number=order.oar_number if order else "N/A",
            quantity=req.quantity,
            remaining_qty=max(new_remaining, 0),
            message=f"Replacement Work Order '{new_wo_num}' created against OAR "
                    f"'{order.oar_number if order else 'N/A'}' for {req.quantity} pieces "
                    f"(source: {original_wo.wo_number}). It must follow the normal release "
                    f"chain (Engineering Release -> Manufacturing Release -> WO Release) before production."
        )

    @staticmethod
    def get_summary(db: Session) -> RejectionSummary:
        records = db.query(NCRecord).all()
        total_rejected = sum(r.qty for r in records if (r.source_type or "REJECTION") == "REJECTION")
        total_excess = sum(r.qty for r in records if r.source_type == "EXCESS_PRODUCTION")
        total_non_moving = sum(r.qty for r in records if r.source_type == "NON_MOVING")

        dispositions = db.query(RejectionDisposition).all()
        total_converted = sum(
            d.quantity for d in dispositions if d.action in ("CONVERT_PART", "SAME_PART", "CWO")
        )
        total_scrap = sum(d.quantity for d in dispositions if d.action == "SCRAP")

        consumed_by_nc = {}
        for d in dispositions:
            consumed_by_nc[d.nc_record_id] = consumed_by_nc.get(d.nc_record_id, 0) + d.quantity
        total_remaining = sum(max(r.qty - consumed_by_nc.get(r.id, 0), 0) for r in records)

        return RejectionSummary(
            total_rejected=total_rejected,
            total_excess=total_excess,
            total_non_moving=total_non_moving,
            total_converted=total_converted,
            total_scrap=total_scrap,
            total_remaining=total_remaining
        )

    @staticmethod
    def get_cwo_detail(db: Session, wo_number: str) -> Optional[CWODetail]:
        """Assemble the source lineage for a Conversion Work Order. A CWO is a normal
        WorkOrder row -- this only reads existing Conversion / NCRecord /
        RejectionDisposition data already recorded when it was created; it computes no
        new quantities of its own."""
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number.strip()).first()
        if not wo:
            return None

        conv = db.query(Conversion).filter(Conversion.conversion_wo_id == wo.id).first()
        if not conv:
            return None  # this WO exists but was not created as a conversion -- not a CWO

        source_wo = conv.source_wo
        source_part = source_wo.order.part if (source_wo and source_wo.order) else None
        dest_part = wo.order.part if wo.order else None

        nc_record = conv.nc_record
        source_nc_number = nc_record.nc_number if nc_record else None
        source_oar_number = source_wo.order.oar_number if (source_wo and source_wo.order) else None

        if nc_record:
            consumed = _consumed_qty(db, nc_record.id)
            converted_qty = consumed
            remaining_qty = max(nc_record.qty - consumed, 0)
        else:
            # Direct mid-route WIP conversion (not disposition-originated) -- no
            # rejection-tracking balance to report against.
            converted_qty = conv.quantity
            remaining_qty = 0

        return CWODetail(
            wo_number=wo.wo_number,
            source_part_number=source_part.part_number if source_part else None,
            source_wo_number=source_wo.wo_number if source_wo else None,
            source_oar_number=source_oar_number,
            source_nc_number=source_nc_number,
            destination_part_number=dest_part.part_number if dest_part else None,
            source_qty=conv.quantity,
            converted_qty=converted_qty,
            remaining_qty=remaining_qty,
            status=wo.status.value,
            created_by=conv.planner,
            created_at=conv.created_at or datetime.now(),
            reason=conv.reason
        )

    @staticmethod
    def record_melting_entry(db: Session, req: MeltingEntryCreate, current_user: Optional[User] = None) -> MeltingEntryResponse:
        """Physical-handling fulfillment of an already-decided SCRAP disposition: record
        that its material was actually sent for melting. This never re-decides or
        re-authorizes the disposition -- it only executes what a QUALITY_APPROVAL_ROLES
        user already approved via create_disposition(action="SCRAP")."""
        _require_role(current_user, MELTING_ENTRY_ROLES, "record a melting entry")

        disposition = db.query(RejectionDisposition).filter(
            RejectionDisposition.id == req.disposition_id
        ).with_for_update().first()
        if not disposition:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Disposition '{req.disposition_id}' not found."
            )
        if disposition.action != "SCRAP":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Melting entry only applies to SCRAP dispositions; this record is '{disposition.action}'."
            )
        if disposition.melting_status == "SENT_FOR_MELTING":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Disposition '{req.disposition_id}' has already been sent for melting on {disposition.melting_sent_at}."
            )

        now = datetime.now()
        disposition.melting_status = "SENT_FOR_MELTING"
        disposition.melting_destination = req.melting_destination
        # The authenticated identity is always the source of truth for who performed
        # this action -- never a client-supplied operator name.
        disposition.melting_sent_by_id = current_user.id if current_user else None
        disposition.melting_sent_by_name = current_user.full_name if current_user else "System"
        disposition.melting_sent_at = now
        disposition.melting_remarks = req.remarks

        record = disposition.nc_record
        wo = record.work_order if record else None
        order = wo.order if wo else None

        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "System",
            action="REJECTION_MELTING_ENTRY",
            entity="RejectionDisposition",
            entity_id=str(disposition.id),
            old_value=f"NC: {record.nc_number if record else 'N/A'}, WO: {wo.wo_number if wo else 'N/A'}, Qty: {disposition.quantity}",
            new_value=f"Sent for melting to '{req.melting_destination or 'unspecified'}' by {disposition.melting_sent_by_name}",
            details=req.remarks
        )
        db.add(audit)
        db.commit()

        return MeltingEntryResponse(
            success=True,
            disposition_id=str(disposition.id),
            nc_number=record.nc_number if record else "N/A",
            wo_number=wo.wo_number if wo else "N/A",
            part_number=order.part.part_number if (order and order.part) else None,
            quantity=disposition.quantity,
            melting_status=disposition.melting_status,
            melting_destination=disposition.melting_destination,
            sent_by=disposition.melting_sent_by_name,
            sent_at=disposition.melting_sent_at,
            message=f"Recorded {disposition.quantity} pcs sent for melting from disposition on '{record.nc_number if record else 'N/A'}'."
        )
