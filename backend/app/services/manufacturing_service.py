import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.core.roles import MANUFACTURING_RELEASE_ROLES
from app.models.user import User, UserRole
from app.models.work_order import WorkOrder, WOStatus
from app.models.order import Order, Part, Customer
from app.models.machine import Machine
from app.models.operator import Operator
from app.models.production_movement import ProductionMovement
from app.models.production import ProductionUpdate
from app.models.audit import AuditLog
from app.models.continuous_casting import ContinuousCastingRouting, ContinuousCastingCutRecord
from app.services.continuous_casting_gate_service import ContinuousCastingGateService
from app.models.manufacturing import (
    WOManufacturingReadiness,
    ChecklistItemStatus,
)
from app.schemas.manufacturing import (
    ManufacturingKPIs,
    MachineOption,
    OperatorOption,
    WOManufacturingReadinessItemOut,
    WOManufacturingReadinessDetailOut,
    WOManufacturingReadinessUpdate,
    ManufacturingReleaseRequest,
    ManufacturingRevocationRequest,
    ManufacturingReleaseResponse,
)


class ManufacturingService:
    @staticmethod
    def _find_work_order(db: Session, wo_identifier: str) -> WorkOrder:
        """Safely find a WorkOrder by either UUID or human-readable wo_number."""
        clean_id = (wo_identifier or "").strip()
        wo = None
        try:
            val_uuid = uuid.UUID(clean_id)
            wo = db.query(WorkOrder).filter(WorkOrder.id == val_uuid).first()
        except (ValueError, AttributeError):
            pass

        if not wo:
            wo = db.query(WorkOrder).filter(WorkOrder.wo_number == clean_id).first()

        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{wo_identifier}' not found."
            )
        return wo

    @staticmethod
    def get_or_create_wo_readiness(db: Session, wo: WorkOrder) -> WOManufacturingReadiness:
        """Fetch existing readiness record or create a fresh pending record for the Work Order."""
        readiness = db.query(WOManufacturingReadiness).filter(
            WOManufacturingReadiness.work_order_id == wo.id
        ).first()

        if not readiness:
            readiness = WOManufacturingReadiness(
                id=uuid.uuid4(),
                work_order_id=wo.id,
                material_staging_status=ChecklistItemStatus.NOT_READY.value,
                machine_capacity_status=ChecklistItemStatus.NOT_READY.value,
                tooling_fixtures_status=ChecklistItemStatus.NOT_READY.value,
                cnc_program_setup_status=ChecklistItemStatus.NOT_READY.value,
                gauges_quality_status=ChecklistItemStatus.NOT_READY.value,
                operator_manning_status=ChecklistItemStatus.NOT_READY.value,
                readiness_status="RELEASED" if wo.manufacturing_released_at is not None else "PENDING",
            )
            db.add(readiness)
            db.flush()

        return readiness

    @staticmethod
    def _evaluate_item(
        item_name: str,
        item_status: str,
        item_remark: Optional[str],
        allow_na: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """Evaluate a single checklist item:
        - READY: pass, no remark required.
        - NOT_READY: fail, blocks release.
        - N_A: fail if not allowed; if allowed, requires non-empty remark.
        - EXCEPTION: pass only if remark is non-empty.
        """
        status_upper = (item_status or "").strip().upper()
        remark_clean = (item_remark or "").strip()

        if status_upper == ChecklistItemStatus.READY.value:
            return True, None

        if status_upper == ChecklistItemStatus.NOT_READY.value:
            return False, f"{item_name}: Marked as NOT_READY."

        if status_upper == ChecklistItemStatus.N_A.value:
            if not allow_na:
                return False, f"{item_name}: N/A is not permitted for this checklist item."
            if not remark_clean:
                return False, f"{item_name}: N/A requires a mandatory justification remark."
            return True, None

        if status_upper == ChecklistItemStatus.EXCEPTION.value:
            if not remark_clean:
                return False, f"{item_name}: EXCEPTION requires a mandatory deviation/justification remark."
            return True, None

        return False, f"{item_name}: Invalid status '{item_status}'."

    @staticmethod
    def evaluate_readiness(readiness: WOManufacturingReadiness, wo: WorkOrder) -> Tuple[bool, List[str]]:
        """Evaluate if the Work Order satisfies all 6 manufacturing readiness checks and engineering prerequisite."""
        blocking_reasons = []

        # 0. Upstream Engineering Release Check
        if getattr(wo, "engineering_released_at", None) is None:
            blocking_reasons.append("Engineering Release is pending (must be authorized first).")

        # 1. Material Staging & Availability (N/A forbidden)
        p1, r1 = ManufacturingService._evaluate_item(
            "Material Staging & Availability",
            readiness.material_staging_status,
            readiness.material_staging_remark,
            allow_na=False
        )
        if not p1 and r1:
            blocking_reasons.append(r1)

        # 2. Machine Cell & Capacity (N/A forbidden)
        p2, r2 = ManufacturingService._evaluate_item(
            "Machine Cell & Capacity",
            readiness.machine_capacity_status,
            readiness.machine_capacity_remark,
            allow_na=False
        )
        if not p2 and r2:
            blocking_reasons.append(r2)

        # 3. Tooling, Jigs & Fixtures (N/A permitted with remark)
        p3, r3 = ManufacturingService._evaluate_item(
            "Tooling, Jigs & Fixtures",
            readiness.tooling_fixtures_status,
            readiness.tooling_fixtures_remark,
            allow_na=True
        )
        if not p3 and r3:
            blocking_reasons.append(r3)

        # 4. CNC Program & Setup Sheet (N/A permitted with remark)
        p4, r4 = ManufacturingService._evaluate_item(
            "CNC Program & Setup Sheet",
            readiness.cnc_program_setup_status,
            readiness.cnc_program_setup_remark,
            allow_na=True
        )
        if not p4 and r4:
            blocking_reasons.append(r4)

        # 5. Gauges & Quality Inspection (N/A permitted with remark)
        p5, r5 = ManufacturingService._evaluate_item(
            "Gauges & Quality Inspection",
            readiness.gauges_quality_status,
            readiness.gauges_quality_remark,
            allow_na=True
        )
        if not p5 and r5:
            blocking_reasons.append(r5)

        # 6. Operator Manning & Assignment (N/A forbidden)
        p6, r6 = ManufacturingService._evaluate_item(
            "Operator Manning & Assignment",
            readiness.operator_manning_status,
            readiness.operator_manning_remark,
            allow_na=False
        )
        if not p6 and r6:
            blocking_reasons.append(r6)

        can_release = len(blocking_reasons) == 0
        return can_release, blocking_reasons

    @staticmethod
    def get_kpis(db: Session) -> ManufacturingKPIs:
        """Compute live manufacturing readiness KPIs across active Work Orders."""
        wos = db.query(WorkOrder).filter(
            WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED])
        ).all()

        pending_review = 0
        ready_for_release = 0
        released = 0
        blocked = 0
        replacement_count = 0

        for wo in wos:
            if wo.is_replacement:
                replacement_count += 1

            if wo.manufacturing_released_at is not None:
                released += 1
                continue

            readiness = db.query(WOManufacturingReadiness).filter(
                WOManufacturingReadiness.work_order_id == wo.id
            ).first()

            if not readiness:
                pending_review += 1
                continue

            can_rel, _ = ManufacturingService.evaluate_readiness(readiness, wo)
            if can_rel:
                ready_for_release += 1
            elif readiness.readiness_status == "BLOCKED":
                blocked += 1
            else:
                pending_review += 1

        return ManufacturingKPIs(
            pending_review=pending_review,
            ready_for_release=ready_for_release,
            released=released,
            blocked=blocked,
            replacement_count=replacement_count,
        )

    @staticmethod
    def list_readiness(
        db: Session,
        status_filter: Optional[str] = None,
        order_type_filter: Optional[str] = None,
        search: Optional[str] = None,
        is_replacement_filter: Optional[bool] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[WOManufacturingReadinessItemOut]:
        """List filterable Work Orders with their 6-point manufacturing readiness status."""
        query = db.query(WorkOrder).join(Order, WorkOrder.order_id == Order.id).join(Part, Order.part_id == Part.id)

        # Exclude closed/dispatched by default unless explicit
        query = query.filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED]))

        if is_replacement_filter is not None:
            query = query.filter(WorkOrder.is_replacement == is_replacement_filter)

        if order_type_filter:
            if order_type_filter.upper() == "NPD":
                query = query.filter(Order.order_classification == "npd")
            elif order_type_filter.upper() == "REGULAR":
                query = query.filter(Order.order_classification != "npd")

        if search:
            s = f"%{search.strip()}%"
            query = query.join(Customer, Order.customer_id == Customer.id).filter(
                or_(
                    WorkOrder.wo_number.ilike(s),
                    Part.description.ilike(s),
                    Part.part_number.ilike(s),
                    Customer.name.ilike(s),
                )
            )

        query = query.order_by(WorkOrder.created_at.desc())
        wos = query.offset(skip).limit(limit).all()

        results = []
        for wo in wos:
            order = wo.order
            part = order.part if order else None
            customer = order.customer if order else None
            readiness = ManufacturingService.get_or_create_wo_readiness(db, wo)

            # Count passed items (READY, valid N_A, valid EXCEPTION)
            passed = 0
            for name, st, rem, allow_na in [
                ("Material Staging", readiness.material_staging_status, readiness.material_staging_remark, False),
                ("Machine Capacity", readiness.machine_capacity_status, readiness.machine_capacity_remark, False),
                ("Tooling Fixtures", readiness.tooling_fixtures_status, readiness.tooling_fixtures_remark, True),
                ("CNC Program Setup", readiness.cnc_program_setup_status, readiness.cnc_program_setup_remark, True),
                ("Gauges Quality", readiness.gauges_quality_status, readiness.gauges_quality_remark, True),
                ("Operator Manning", readiness.operator_manning_status, readiness.operator_manning_remark, False),
            ]:
                p, _ = ManufacturingService._evaluate_item(name, st, rem, allow_na)
                if p:
                    passed += 1

            can_rel, _ = ManufacturingService.evaluate_readiness(readiness, wo)
            computed_status = "RELEASED" if wo.manufacturing_released_at is not None else ("READY" if can_rel else readiness.readiness_status)

            if status_filter:
                sf = status_filter.strip().upper()
                if sf == "RELEASED" and computed_status != "RELEASED":
                    continue
                if sf == "READY" and computed_status != "READY":
                    continue
                if sf == "PENDING" and computed_status not in ("PENDING", "NOT_READY"):
                    continue
                if sf == "BLOCKED" and computed_status != "BLOCKED":
                    continue

            source_wo_num = None
            if wo.source_wo_id:
                swo = db.query(WorkOrder).filter(WorkOrder.id == wo.source_wo_id).first()
                if swo:
                    source_wo_num = swo.wo_number

            results.append(
                WOManufacturingReadinessItemOut(
                    work_order_id=str(wo.id),
                    work_order_number=wo.wo_number,
                    part_id=str(part.id) if part else "",
                    part_name=(part.description or part.part_number) if part else "",
                    customer_name=customer.name if customer else "",
                    order_type="NPD" if (order and order.order_classification == "npd") else "REGULAR",
                    quantity=wo.physical_wo_qty,
                    target_date=order.delivery_date.isoformat() if (order and order.delivery_date) else None,
                    is_replacement=wo.is_replacement,
                    source_wo_number=source_wo_num,
                    replacement_reason=wo.replacement_reason,
                    engineering_released=wo.engineering_released_at is not None,
                    engineering_released_at=wo.engineering_released_at.isoformat() if wo.engineering_released_at else None,
                    engineering_document_revision=wo.engineering_document_revision,
                    material_staging_status=readiness.material_staging_status,
                    machine_capacity_status=readiness.machine_capacity_status,
                    tooling_fixtures_status=readiness.tooling_fixtures_status,
                    cnc_program_setup_status=readiness.cnc_program_setup_status,
                    gauges_quality_status=readiness.gauges_quality_status,
                    operator_manning_status=readiness.operator_manning_status,
                    machine_code=readiness.machine_code,
                    operator_name=readiness.operator_name,
                    readiness_status=computed_status,
                    is_released=wo.manufacturing_released_at is not None,
                    released_at=wo.manufacturing_released_at.isoformat() if wo.manufacturing_released_at else None,
                    passed_count=passed,
                    total_count=6,
                )
            )

        return results

    @staticmethod
    def get_readiness_detail(db: Session, wo_identifier: str) -> WOManufacturingReadinessDetailOut:
        """Get full manufacturing readiness detail for a Work Order."""
        wo = ManufacturingService._find_work_order(db, wo_identifier)
        order = wo.order
        part = order.part if order else None
        customer = order.customer if order else None
        readiness = ManufacturingService.get_or_create_wo_readiness(db, wo)

        can_rel, blocking = ManufacturingService.evaluate_readiness(readiness, wo)
        computed_status = "RELEASED" if wo.manufacturing_released_at is not None else ("READY" if can_rel else readiness.readiness_status)

        # Source WO info for replacements
        source_wo_num = None
        if wo.source_wo_id:
            swo = db.query(WorkOrder).filter(WorkOrder.id == wo.source_wo_id).first()
            if swo:
                source_wo_num = swo.wo_number

        # Continuous Casting live integration details
        cc_summary = None
        china_routing = ContinuousCastingGateService.active_china_routing(db, wo)
        if china_routing:
            usable_blanks = ContinuousCastingGateService.usable_good_blanks(db, wo, china_routing)
            cc_summary = {
                "is_cc": True,
                "routing_id": str(china_routing.id),
                "routing_version": china_routing.version,
                "required_grade": china_routing.required_grade,
                "planned_blanks": china_routing.planned_blanks,
                "usable_good_blanks": usable_blanks,
                "blank_length_mm": china_routing.blank_length_mm,
                "is_cutting_ready": usable_blanks >= (china_routing.planned_blanks or 0),
            }

        # Available active machines
        machines = db.query(Machine).filter(Machine.is_active == True).order_by(Machine.machine_code).all()
        machine_options = [
            MachineOption(
                id=str(m.id),
                machine_code=m.machine_code,
                machine_name=m.machine_name,
                department=m.department,
                is_active=m.is_active,
            )
            for m in machines
        ]

        # Available active operators
        operators = db.query(Operator).filter(Operator.is_active == True).order_by(Operator.display_name).all()
        operator_options = [
            OperatorOption(
                id=str(op.id),
                operator_code=op.employee_code or "",
                operator_name=op.display_name,
                skill_level="Operator",
                is_active=op.is_active,
            )
            for op in operators
        ]

        return WOManufacturingReadinessDetailOut(
            work_order_id=str(wo.id),
            work_order_number=wo.wo_number,
            part_id=str(part.id) if part else "",
            part_name=(part.description or part.part_number) if part else "",
            customer_name=customer.name if customer else "",
            order_type="NPD" if (order and order.order_classification == "npd") else "REGULAR",
            quantity=wo.physical_wo_qty,
            target_date=order.delivery_date.isoformat() if (order and order.delivery_date) else None,
            is_replacement=wo.is_replacement,
            source_wo_number=source_wo_num,
            replacement_reason=wo.replacement_reason,
            engineering_released=wo.engineering_released_at is not None,
            engineering_released_by=wo.engineering_released_by,
            engineering_released_at=wo.engineering_released_at.isoformat() if wo.engineering_released_at else None,
            engineering_document_revision=wo.engineering_document_revision,
            engineering_document_url=wo.engineering_document_url,
            engineering_remarks=wo.engineering_remarks,
            material_staging_status=readiness.material_staging_status,
            material_staging_remark=readiness.material_staging_remark,
            machine_capacity_status=readiness.machine_capacity_status,
            machine_capacity_remark=readiness.machine_capacity_remark,
            machine_id=str(readiness.machine_id) if readiness.machine_id else None,
            machine_code=readiness.machine_code,
            tooling_fixtures_status=readiness.tooling_fixtures_status,
            tooling_fixtures_remark=readiness.tooling_fixtures_remark,
            fixture_id=readiness.fixture_id,
            cnc_program_setup_status=readiness.cnc_program_setup_status,
            cnc_program_setup_remark=readiness.cnc_program_setup_remark,
            nc_program_number=readiness.nc_program_number,
            setup_sheet_url=readiness.setup_sheet_url,
            gauges_quality_status=readiness.gauges_quality_status,
            gauges_quality_remark=readiness.gauges_quality_remark,
            gauge_set_id=readiness.gauge_set_id,
            operator_manning_status=readiness.operator_manning_status,
            operator_manning_remark=readiness.operator_manning_remark,
            operator_id=str(readiness.operator_id) if readiness.operator_id else None,
            operator_name=readiness.operator_name,
            readiness_status=computed_status,
            remarks=readiness.remarks,
            document_name=readiness.document_name or wo.manufacturing_document_name,
            document_url=readiness.document_url or wo.manufacturing_document_url,
            document_revision=readiness.document_revision or wo.manufacturing_document_revision,
            released_by_id=str(readiness.released_by_id) if readiness.released_by_id else None,
            released_by_name=wo.manufacturing_released_by or readiness.released_by_name,
            released_at=wo.manufacturing_released_at.isoformat() if wo.manufacturing_released_at else (readiness.released_at.isoformat() if readiness.released_at else None),
            is_released=wo.manufacturing_released_at is not None,
            can_release=can_rel,
            blocking_reasons=blocking,
            continuous_casting_summary=cc_summary,
            available_machines=machine_options,
            available_operators=operator_options,
        )

    @staticmethod
    def update_readiness(
        db: Session,
        wo_identifier: str,
        payload: WOManufacturingReadinessUpdate,
        current_user: Optional[User] = None,
    ) -> WOManufacturingReadinessDetailOut:
        """Update checklist statuses, remarks, and machine/operator assignments."""
        wo = ManufacturingService._find_work_order(db, wo_identifier)
        if wo.manufacturing_released_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' is already released for manufacturing. Checklist is locked."
            )

        readiness = ManufacturingService.get_or_create_wo_readiness(db, wo)

        # Validate N/A constraints on update
        if payload.material_staging_status == ChecklistItemStatus.N_A.value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "N/A is not permitted for Material Staging & Availability.")
        if payload.machine_capacity_status == ChecklistItemStatus.N_A.value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "N/A is not permitted for Machine Cell & Capacity.")
        if payload.operator_manning_status == ChecklistItemStatus.N_A.value:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "N/A is not permitted for Operator Manning & Assignment.")

        # Update fields if provided
        for attr in [
            "material_staging_status", "material_staging_remark",
            "machine_capacity_status", "machine_capacity_remark", "machine_code",
            "tooling_fixtures_status", "tooling_fixtures_remark", "fixture_id",
            "cnc_program_setup_status", "cnc_program_setup_remark", "nc_program_number", "setup_sheet_url",
            "gauges_quality_status", "gauges_quality_remark", "gauge_set_id",
            "operator_manning_status", "operator_manning_remark", "operator_name",
            "document_name", "document_url", "document_revision", "remarks",
        ]:
            val = getattr(payload, attr, None)
            if val is not None:
                setattr(readiness, attr, val)

        # Machine ID FK resolution
        if payload.machine_id is not None:
            if payload.machine_id.strip():
                try:
                    m_uuid = uuid.UUID(payload.machine_id.strip())
                    mach = db.query(Machine).filter(Machine.id == m_uuid).first()
                    if mach:
                        readiness.machine_id = mach.id
                        readiness.machine_code = mach.machine_code
                except ValueError:
                    pass
            else:
                readiness.machine_id = None

        # Operator ID FK resolution
        if payload.operator_id is not None:
            if payload.operator_id.strip():
                try:
                    op_uuid = uuid.UUID(payload.operator_id.strip())
                    op = db.query(Operator).filter(Operator.id == op_uuid).first()
                    if op:
                        readiness.operator_id = op.id
                        readiness.operator_name = op.display_name
                except ValueError:
                    pass
            else:
                readiness.operator_id = None

        can_rel, _ = ManufacturingService.evaluate_readiness(readiness, wo)
        readiness.readiness_status = "READY" if can_rel else "PENDING"

        db.commit()
        db.refresh(readiness)
        return ManufacturingService.get_readiness_detail(db, wo.wo_number)

    @staticmethod
    def release_manufacturing(
        db: Session,
        wo_identifier: str,
        payload: ManufacturingReleaseRequest,
        current_user: User,
    ) -> ManufacturingReleaseResponse:
        """Authorize Manufacturing Release for a Work Order after strict 6-point verification."""
        # 1. RBAC authorization check
        if current_user.role not in MANUFACTURING_RELEASE_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role.value}' is not authorized to sign off Manufacturing Release."
            )

        wo = ManufacturingService._find_work_order(db, wo_identifier)

        if wo.manufacturing_released_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' has already received Manufacturing Release on {wo.manufacturing_released_at.isoformat()}."
            )

        # 2. Strict Upstream Engineering Release Check
        if getattr(wo, "engineering_released_at", None) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' cannot receive Manufacturing Release: Engineering Release is pending."
            )

        readiness = ManufacturingService.get_or_create_wo_readiness(db, wo)

        # 3. Full 6-Point Readiness Gate Evaluation
        can_rel, blocking = ManufacturingService.evaluate_readiness(readiness, wo)
        if not can_rel:
            reasons_str = " | ".join(blocking)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot authorize Manufacturing Release for '{wo.wo_number}'. Blocked reasons: {reasons_str}"
            )

        now = datetime.now(timezone.utc)
        doc_name = payload.document_name or readiness.document_name or f"MFG-PLAN-{wo.wo_number}"
        doc_url = payload.document_url or readiness.setup_sheet_url or readiness.document_url
        doc_rev = payload.document_revision or readiness.document_revision or "Rev 01"
        rem = payload.remarks or readiness.remarks or "Manufacturing readiness verified and authorized."

        # 4. Stamp authoritative columns on work_orders
        wo.manufacturing_released_by = current_user.full_name
        wo.manufacturing_released_at = now
        wo.manufacturing_document_name = doc_name
        wo.manufacturing_document_url = doc_url
        wo.manufacturing_document_revision = doc_rev
        wo.manufacturing_remarks = rem

        # 5. Update WOManufacturingReadiness
        readiness.readiness_status = "RELEASED"
        readiness.released_by_id = current_user.id
        readiness.released_by_name = current_user.full_name
        readiness.released_at = now
        readiness.document_name = doc_name
        readiness.document_url = doc_url
        readiness.document_revision = doc_rev
        readiness.remarks = rem

        # 6. Structured Audit Log
        audit = AuditLog(
            user_id=current_user.id,
            user_name=current_user.full_name,
            action="MANUFACTURING_RELEASE",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            new_value=f"Released by {current_user.full_name}, Machine: {readiness.machine_code or 'N/A'}, Operator: {readiness.operator_name or 'N/A'}, Doc: {doc_name} ({doc_rev})",
            details=f"Checklist 6/6 verified. Material: {readiness.material_staging_status}, Machine: {readiness.machine_capacity_status}, Tooling: {readiness.tooling_fixtures_status}, CNC: {readiness.cnc_program_setup_status}, Gauges: {readiness.gauges_quality_status}, Operator: {readiness.operator_manning_status}. Remarks: {rem}",
        )
        db.add(audit)

        db.commit()
        db.refresh(wo)

        return ManufacturingReleaseResponse(
            work_order_id=str(wo.id),
            work_order_number=wo.wo_number,
            status=wo.status.value,
            is_released=True,
            manufacturing_released_by=wo.manufacturing_released_by,
            manufacturing_released_at=wo.manufacturing_released_at.isoformat() if wo.manufacturing_released_at else None,
            message=f"Work Order '{wo.wo_number}' successfully authorized for Manufacturing Release by {current_user.full_name}."
        )

    @staticmethod
    def revoke_manufacturing_release(
        db: Session,
        wo_identifier: str,
        payload: ManufacturingRevocationRequest,
        current_user: User,
    ) -> ManufacturingReleaseResponse:
        """Revoke Manufacturing Release (Admin only, safety gated before shop-floor production movement)."""
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Admin can revoke a Manufacturing Release."
            )

        rev_reason = (payload.revocation_reason or "").strip()
        if not rev_reason:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Revocation reason is mandatory."
            )

        wo = ManufacturingService._find_work_order(db, wo_identifier)

        if wo.manufacturing_released_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' does not have an active Manufacturing Release to revoke."
            )

        # Safety Gate: Prevent revocation if production movement or stage execution has begun on shop floor
        mov_count = db.query(ProductionMovement).filter(ProductionMovement.work_order_id == wo.id).count()
        upd_count = db.query(ProductionUpdate).filter(ProductionUpdate.work_order_id == wo.id).count()
        if mov_count > 0 or upd_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Manufacturing Release cannot be revoked: Shop floor production/movement has already commenced on Work Order '{wo.wo_number}'."
            )

        # Clear authoritative release columns on work_orders
        prev_user = wo.manufacturing_released_by
        prev_at = wo.manufacturing_released_at
        wo.manufacturing_released_by = None
        wo.manufacturing_released_at = None
        wo.manufacturing_document_name = None
        wo.manufacturing_document_url = None
        wo.manufacturing_document_revision = None
        wo.manufacturing_remarks = None

        readiness = ManufacturingService.get_or_create_wo_readiness(db, wo)
        readiness.readiness_status = "PENDING"
        readiness.released_by_id = None
        readiness.released_by_name = None
        readiness.released_at = None

        audit = AuditLog(
            user_id=current_user.id,
            user_name=current_user.full_name,
            action="MANUFACTURING_RELEASE_REVOKED",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            old_value=f"Released by {prev_user} at {prev_at}",
            new_value="REVOKED",
            details=f"Reason: {rev_reason}",
        )
        db.add(audit)

        db.commit()
        db.refresh(wo)

        return ManufacturingReleaseResponse(
            work_order_id=str(wo.id),
            work_order_number=wo.wo_number,
            status=wo.status.value,
            is_released=False,
            manufacturing_released_by=None,
            manufacturing_released_at=None,
            message=f"Manufacturing Release for '{wo.wo_number}' revoked successfully."
        )
