import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from app.models.work_order import WorkOrder, WOStatus
from app.models.order import Order, Part, Customer
from app.models.production_movement import ProductionMovement
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.models.engineering import PartEngineeringRevision, WOEngineeringReadiness
from app.schemas.engineering import (
    EngineeringRevisionCreate,
    EngineeringRevisionUpdate,
    EngineeringRevisionOut,
    WOReadinessItemOut,
    WOReadinessDetailOut,
    WOReadinessChecklistUpdate,
    EngineeringReleaseRequest,
    EngineeringRevocationRequest,
    EngineeringReleaseResponse,
)
from app.core.roles import ENGINEERING_RELEASE_ROLES


class EngineeringService:

    @staticmethod
    def _find_work_order(db: Session, wo_identifier: str, for_update: bool = False) -> Optional[WorkOrder]:
        ident = str(wo_identifier).strip()
        query = db.query(WorkOrder)
        if for_update:
            query = query.with_for_update()
        try:
            uuid_obj = uuid.UUID(ident)
            return query.filter(or_(WorkOrder.wo_number == ident, WorkOrder.id == uuid_obj)).first()
        except (ValueError, AttributeError):
            return query.filter(WorkOrder.wo_number == ident).first()

    # -----------------------------------------------------------------------
    # Part Engineering Revision Master
    # -----------------------------------------------------------------------

    @staticmethod
    def list_revisions(
        db: Session,
        part_id: Optional[str] = None,
        part_number: Optional[str] = None,
        active_only: bool = False
    ) -> List[EngineeringRevisionOut]:
        query = db.query(PartEngineeringRevision).join(Part, PartEngineeringRevision.part_id == Part.id)
        if part_id:
            query = query.filter(PartEngineeringRevision.part_id == part_id)
        if part_number:
            query = query.filter(Part.part_number == part_number.strip().upper())
        if active_only:
            query = query.filter(PartEngineeringRevision.is_active.is_(True))

        revisions = query.order_by(Part.part_number, PartEngineeringRevision.drawing_revision).all()
        result = []
        for r in revisions:
            item = EngineeringRevisionOut.model_validate(r)
            item.part_number = r.part.part_number if r.part else None
            result.append(item)
        return result

    @staticmethod
    def create_revision(
        db: Session,
        req: EngineeringRevisionCreate,
        current_user: Optional[User] = None
    ) -> EngineeringRevisionOut:
        part = db.query(Part).filter(Part.id == req.part_id).first()
        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Part with ID '{req.part_id}' not found."
            )

        # Enforce uniqueness of (part_id, drawing_revision)
        existing = db.query(PartEngineeringRevision).filter(
            PartEngineeringRevision.part_id == part.id,
            PartEngineeringRevision.drawing_revision == req.drawing_revision.strip().upper()
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Engineering Revision '{req.drawing_revision}' already exists for Part '{part.part_number}'."
            )

        # If this new revision is set active, optionally deactivate other revisions for this part
        if req.is_active:
            db.query(PartEngineeringRevision).filter(
                PartEngineeringRevision.part_id == part.id
            ).update({"is_active": False})

        rev = PartEngineeringRevision(
            part_id=part.id,
            drawing_number=req.drawing_number.strip(),
            drawing_revision=req.drawing_revision.strip().upper(),
            drawing_url=req.drawing_url.strip() if req.drawing_url else None,
            customer_spec_ref=req.customer_spec_ref.strip() if req.customer_spec_ref else None,
            process_sheet_number=req.process_sheet_number.strip() if req.process_sheet_number else None,
            pattern_number=req.pattern_number.strip() if req.pattern_number else None,
            tooling_id=req.tooling_id.strip() if req.tooling_id else None,
            is_active=req.is_active,
            created_by_id=current_user.id if current_user else None
        )
        db.add(rev)
        db.commit()
        db.refresh(rev)

        out = EngineeringRevisionOut.model_validate(rev)
        out.part_number = part.part_number
        return out

    @staticmethod
    def update_revision(
        db: Session,
        revision_id: str,
        req: EngineeringRevisionUpdate,
        current_user: Optional[User] = None
    ) -> EngineeringRevisionOut:
        rev = db.query(PartEngineeringRevision).filter(PartEngineeringRevision.id == revision_id).first()
        if not rev:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Engineering Revision '{revision_id}' not found."
            )

        if req.drawing_revision is not None and req.drawing_revision.strip().upper() != rev.drawing_revision:
            new_rev = req.drawing_revision.strip().upper()
            duplicate = db.query(PartEngineeringRevision).filter(
                PartEngineeringRevision.part_id == rev.part_id,
                PartEngineeringRevision.drawing_revision == new_rev,
                PartEngineeringRevision.id != rev.id
            ).first()
            if duplicate:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Engineering Revision '{new_rev}' already exists for Part."
                )
            rev.drawing_revision = new_rev

        if req.drawing_number is not None:
            rev.drawing_number = req.drawing_number.strip()
        if req.drawing_url is not None:
            rev.drawing_url = req.drawing_url.strip() or None
        if req.customer_spec_ref is not None:
            rev.customer_spec_ref = req.customer_spec_ref.strip() or None
        if req.process_sheet_number is not None:
            rev.process_sheet_number = req.process_sheet_number.strip() or None
        if req.pattern_number is not None:
            rev.pattern_number = req.pattern_number.strip() or None
        if req.tooling_id is not None:
            rev.tooling_id = req.tooling_id.strip() or None

        if req.is_active is True:
            db.query(PartEngineeringRevision).filter(
                PartEngineeringRevision.part_id == rev.part_id,
                PartEngineeringRevision.id != rev.id
            ).update({"is_active": False})
            rev.is_active = True
        elif req.is_active is False:
            rev.is_active = False

        db.commit()
        db.refresh(rev)
        out = EngineeringRevisionOut.model_validate(rev)
        out.part_number = rev.part.part_number if rev.part else None
        return out

    # -----------------------------------------------------------------------
    # WO Engineering Readiness Checklist & Verification
    # -----------------------------------------------------------------------

    @staticmethod
    def get_or_create_wo_readiness(db: Session, wo: WorkOrder) -> WOEngineeringReadiness:
        readiness = db.query(WOEngineeringReadiness).filter(
            WOEngineeringReadiness.work_order_id == wo.id
        ).first()

        if readiness:
            return readiness

        # Initialize new readiness record
        order = wo.order
        part = order.part if order else None
        active_rev = None
        if part:
            active_rev = db.query(PartEngineeringRevision).filter(
                PartEngineeringRevision.part_id == part.id,
                PartEngineeringRevision.is_active.is_(True)
            ).first()

        is_npd = str(getattr(order, "order_classification", "")).lower() == "npd"

        # Defaults for Regular orders vs strict NPD
        drawing_available = False
        drawing_revision_verified = False
        customer_spec_verified = False
        process_sheet_verified = False
        pattern_ready = False
        tooling_ready = False

        verified_revision = getattr(wo, "engineering_document_revision", None)
        drawing_url = getattr(wo, "engineering_document_url", None)
        pattern_number = None
        tooling_id = None

        if active_rev:
            verified_revision = verified_revision or active_rev.drawing_revision
            drawing_url = drawing_url or active_rev.drawing_url
            pattern_number = active_rev.pattern_number
            tooling_id = active_rev.tooling_id

            if not is_npd:
                # Regular repeat orders can inherit verified flags if active revision has valid specs
                drawing_available = bool(active_rev.drawing_url)
                drawing_revision_verified = bool(active_rev.drawing_revision)
                customer_spec_verified = bool(active_rev.customer_spec_ref)
                process_sheet_verified = bool(active_rev.process_sheet_number)
                pattern_ready = bool(active_rev.pattern_number)
                tooling_ready = bool(active_rev.tooling_id)

        # If WO was already released in legacy flow, reflect that
        if getattr(wo, "engineering_released_at", None) is not None:
            readiness_status = "RELEASED"
            drawing_available = True
            drawing_revision_verified = True
            customer_spec_verified = True
            process_sheet_verified = True
            pattern_ready = True
            tooling_ready = True
        else:
            all_passed = (
                drawing_available and drawing_revision_verified and
                customer_spec_verified and process_sheet_verified and
                pattern_ready and tooling_ready and bool(verified_revision)
            )
            readiness_status = "READY" if all_passed else "PENDING"

        readiness = WOEngineeringReadiness(
            work_order_id=wo.id,
            engineering_revision_id=active_rev.id if active_rev else None,
            drawing_available=drawing_available,
            drawing_revision_verified=drawing_revision_verified,
            customer_spec_verified=customer_spec_verified,
            process_sheet_verified=process_sheet_verified,
            pattern_ready=pattern_ready,
            tooling_ready=tooling_ready,
            verified_revision=verified_revision,
            drawing_url=drawing_url,
            pattern_number=pattern_number,
            tooling_id=tooling_id,
            readiness_status=readiness_status,
            engineer_name=getattr(wo, "engineering_released_by", None),
            released_at=getattr(wo, "engineering_released_at", None),
            remarks=getattr(wo, "engineering_remarks", None)
        )
        db.add(readiness)
        db.commit()
        db.refresh(readiness)
        return readiness

    @staticmethod
    def list_readiness(
        db: Session,
        search: Optional[str] = None,
        status_filter: Optional[str] = None,
        customer_code: Optional[str] = None,
        classification: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[WOReadinessItemOut]:
        query = db.query(WorkOrder).join(Order, WorkOrder.order_id == Order.id).join(Customer, Order.customer_id == Customer.id).join(Part, Order.part_id == Part.id)

        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    WorkOrder.wo_number.ilike(s),
                    Customer.name.ilike(s),
                    Customer.customer_code.ilike(s),
                    Part.part_number.ilike(s),
                    Order.customer_po.ilike(s),
                    Order.oar_number.ilike(s),
                )
            )

        if customer_code:
            query = query.filter(Customer.customer_code == customer_code.strip())

        if classification:
            query = query.filter(Order.order_classification == classification.strip().lower())

        work_orders = query.order_by(WorkOrder.created_at.desc()).offset(offset).limit(limit).all()

        results = []
        for wo in work_orders:
            readiness = EngineeringService.get_or_create_wo_readiness(db, wo)

            # Check if status filter applies
            if status_filter:
                f = status_filter.strip().upper()
                if readiness.readiness_status != f:
                    continue

            checks = [
                readiness.drawing_available,
                readiness.drawing_revision_verified,
                readiness.customer_spec_verified,
                readiness.process_sheet_verified,
                readiness.pattern_ready,
                readiness.tooling_ready,
            ]
            passed_count = sum(1 for c in checks if c)
            is_complete = passed_count == 6 and bool(readiness.verified_revision)

            item = WOReadinessItemOut(
                id=str(readiness.id),
                work_order_id=str(wo.id),
                wo_number=wo.wo_number,
                oar_number=wo.order.oar_number if wo.order else None,
                customer_code=wo.order.customer.customer_code if wo.order and wo.order.customer else "",
                customer_name=wo.order.customer.name if wo.order and wo.order.customer else "",
                customer_po=wo.order.customer_po if wo.order else "",
                part_number=wo.order.part.part_number if wo.order and wo.order.part else "",
                part_name=wo.order.part.description if wo.order and wo.order.part else None,
                grade=wo.order.part.grade if wo.order and wo.order.part else None,
                order_classification=wo.order.order_classification if wo.order else "regular",
                physical_wo_qty=wo.physical_wo_qty,
                current_stage=wo.current_stage or "F1",
                is_replacement=getattr(wo, "is_replacement", False),
                replacement_reason=getattr(wo, "replacement_reason", None),
                engineering_revision_id=str(readiness.engineering_revision_id) if readiness.engineering_revision_id else None,
                verified_revision=readiness.verified_revision,
                drawing_available=readiness.drawing_available,
                drawing_revision_verified=readiness.drawing_revision_verified,
                customer_spec_verified=readiness.customer_spec_verified,
                process_sheet_verified=readiness.process_sheet_verified,
                pattern_ready=readiness.pattern_ready,
                tooling_ready=readiness.tooling_ready,
                checklist_passed_count=passed_count,
                checklist_total_count=6,
                is_checklist_complete=is_complete,
                readiness_status=readiness.readiness_status,
                engineering_released_by=wo.engineering_released_by,
                engineering_released_at=wo.engineering_released_at,
                remarks=readiness.remarks,
                created_at=readiness.created_at or datetime.now()
            )
            results.append(item)

        return results

    @staticmethod
    def get_readiness_detail(db: Session, wo_identifier: str) -> WOReadinessDetailOut:
        wo = EngineeringService._find_work_order(db, wo_identifier)
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{wo_identifier}' not found."
            )

        readiness = EngineeringService.get_or_create_wo_readiness(db, wo)
        part = wo.order.part if wo.order else None
        available_revs = []
        if part:
            available_revs = EngineeringService.list_revisions(db, part_id=str(part.id))

        checks = [
            readiness.drawing_available,
            readiness.drawing_revision_verified,
            readiness.customer_spec_verified,
            readiness.process_sheet_verified,
            readiness.pattern_ready,
            readiness.tooling_ready,
        ]
        passed_count = sum(1 for c in checks if c)
        is_complete = passed_count == 6 and bool(readiness.verified_revision)

        return WOReadinessDetailOut(
            id=str(readiness.id),
            work_order_id=str(wo.id),
            wo_number=wo.wo_number,
            oar_number=wo.order.oar_number if wo.order else None,
            customer_code=wo.order.customer.customer_code if wo.order and wo.order.customer else "",
            customer_name=wo.order.customer.name if wo.order and wo.order.customer else "",
            customer_po=wo.order.customer_po if wo.order else "",
            part_number=wo.order.part.part_number if wo.order and wo.order.part else "",
            part_name=wo.order.part.description if wo.order and wo.order.part else None,
            grade=wo.order.part.grade if wo.order and wo.order.part else None,
            order_classification=wo.order.order_classification if wo.order else "regular",
            physical_wo_qty=wo.physical_wo_qty,
            current_stage=wo.current_stage or "F1",
            is_replacement=getattr(wo, "is_replacement", False),
            replacement_reason=getattr(wo, "replacement_reason", None),
            engineering_revision_id=str(readiness.engineering_revision_id) if readiness.engineering_revision_id else None,
            verified_revision=readiness.verified_revision,
            drawing_available=readiness.drawing_available,
            drawing_revision_verified=readiness.drawing_revision_verified,
            customer_spec_verified=readiness.customer_spec_verified,
            process_sheet_verified=readiness.process_sheet_verified,
            pattern_ready=readiness.pattern_ready,
            tooling_ready=readiness.tooling_ready,
            checklist_passed_count=passed_count,
            checklist_total_count=6,
            is_checklist_complete=is_complete,
            readiness_status=readiness.readiness_status,
            engineering_released_by=wo.engineering_released_by,
            engineering_released_at=wo.engineering_released_at,
            remarks=readiness.remarks,
            drawing_url=readiness.drawing_url,
            pattern_number=readiness.pattern_number,
            tooling_id=readiness.tooling_id,
            engineer_id=str(readiness.engineer_id) if readiness.engineer_id else None,
            engineer_name=readiness.engineer_name,
            available_revisions=available_revs,
            created_at=readiness.created_at or datetime.now()
        )

    @staticmethod
    def update_checklist(
        db: Session,
        wo_identifier: str,
        req: WOReadinessChecklistUpdate,
        current_user: Optional[User] = None
    ) -> WOReadinessDetailOut:
        wo = EngineeringService._find_work_order(db, wo_identifier, for_update=True)
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{wo_identifier}' not found."
            )

        if getattr(wo, "engineering_released_at", None) is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' has already received Engineering Release. Revoke release before modifying checklist."
            )

        readiness = EngineeringService.get_or_create_wo_readiness(db, wo)

        if req.engineering_revision_id is not None:
            rev = db.query(PartEngineeringRevision).filter(
                PartEngineeringRevision.id == req.engineering_revision_id
            ).first()
            if rev:
                readiness.engineering_revision_id = rev.id
                if not readiness.verified_revision:
                    readiness.verified_revision = rev.drawing_revision
                if not readiness.drawing_url:
                    readiness.drawing_url = rev.drawing_url
                if not readiness.pattern_number:
                    readiness.pattern_number = rev.pattern_number
                if not readiness.tooling_id:
                    readiness.tooling_id = rev.tooling_id

        if req.drawing_available is not None:
            readiness.drawing_available = req.drawing_available
        if req.drawing_revision_verified is not None:
            readiness.drawing_revision_verified = req.drawing_revision_verified
        if req.customer_spec_verified is not None:
            readiness.customer_spec_verified = req.customer_spec_verified
        if req.process_sheet_verified is not None:
            readiness.process_sheet_verified = req.process_sheet_verified
        if req.pattern_ready is not None:
            readiness.pattern_ready = req.pattern_ready
        if req.tooling_ready is not None:
            readiness.tooling_ready = req.tooling_ready

        if req.verified_revision is not None:
            readiness.verified_revision = req.verified_revision.strip() or None
        if req.drawing_url is not None:
            readiness.drawing_url = req.drawing_url.strip() or None
        if req.pattern_number is not None:
            readiness.pattern_number = req.pattern_number.strip() or None
        if req.tooling_id is not None:
            readiness.tooling_id = req.tooling_id.strip() or None
        if req.remarks is not None:
            readiness.remarks = req.remarks.strip() or None

        # Re-evaluate status
        checks = [
            readiness.drawing_available,
            readiness.drawing_revision_verified,
            readiness.customer_spec_verified,
            readiness.process_sheet_verified,
            readiness.pattern_ready,
            readiness.tooling_ready,
        ]
        all_passed = all(checks) and bool(readiness.verified_revision)
        readiness.readiness_status = "READY" if all_passed else "PENDING"
        readiness.engineer_id = current_user.id if current_user else None
        readiness.engineer_name = current_user.full_name if current_user else None

        db.commit()
        db.refresh(readiness)
        return EngineeringService.get_readiness_detail(db, wo.wo_number)

    # -----------------------------------------------------------------------
    # Engineering Release Gate Execution
    # -----------------------------------------------------------------------

    @staticmethod
    def release_engineering(
        db: Session,
        wo_identifier: str,
        req: EngineeringReleaseRequest,
        current_user: User
    ) -> EngineeringReleaseResponse:
        # Caller authorization check
        if current_user.role not in ENGINEERING_RELEASE_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User '{current_user.full_name}' ({current_user.role.value}) is not authorized to perform Engineering Release."
            )

        wo = EngineeringService._find_work_order(db, wo_identifier, for_update=True)
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{wo_identifier}' not found."
            )

        # Idempotency: if already released by this or another user
        if getattr(wo, "engineering_released_at", None) is not None:
            return EngineeringReleaseResponse(
                success=True,
                wo_number=wo.wo_number,
                readiness_status="RELEASED",
                engineering_released_by=wo.engineering_released_by or current_user.full_name,
                engineering_released_at=wo.engineering_released_at,
                engineering_document_revision=wo.engineering_document_revision,
                message=f"Work Order '{wo.wo_number}' is already released by Engineering."
            )

        readiness = EngineeringService.get_or_create_wo_readiness(db, wo)

        # Apply payload values if provided
        if req.engineering_revision_id:
            rev = db.query(PartEngineeringRevision).filter(
                PartEngineeringRevision.id == req.engineering_revision_id
            ).first()
            if rev:
                readiness.engineering_revision_id = rev.id
                if not readiness.verified_revision:
                    readiness.verified_revision = rev.drawing_revision
                if not readiness.drawing_url:
                    readiness.drawing_url = rev.drawing_url
                if not readiness.pattern_number:
                    readiness.pattern_number = rev.pattern_number
                if not readiness.tooling_id:
                    readiness.tooling_id = rev.tooling_id

        if req.verified_revision:
            readiness.verified_revision = req.verified_revision.strip()
        if req.drawing_url:
            readiness.drawing_url = req.drawing_url.strip()
        if req.pattern_number:
            readiness.pattern_number = req.pattern_number.strip()
        if req.tooling_id:
            readiness.tooling_id = req.tooling_id.strip()
        if req.remarks:
            readiness.remarks = req.remarks.strip()

        # Strict Verification Checklist Validation
        missing_checks = []
        if not readiness.drawing_available:
            missing_checks.append("Drawing is not available or unconfirmed")
        if not readiness.drawing_revision_verified:
            missing_checks.append("Drawing revision is not verified against PO")
        if not readiness.customer_spec_verified:
            missing_checks.append("Customer & material specification is unverified")
        if not readiness.process_sheet_verified:
            missing_checks.append("Process / method sheet is unverified")
        if not readiness.pattern_ready:
            missing_checks.append("Pattern / Core box readiness is unverified")
        if not readiness.tooling_ready:
            missing_checks.append("Tooling / Jigs / Fixtures readiness is unverified")
        if not readiness.verified_revision or not readiness.verified_revision.strip():
            missing_checks.append("Verified drawing revision cannot be empty")

        if getattr(wo, "is_replacement", False):
            if not req.replacement_reason_acknowledged and not getattr(wo, "replacement_reason", None):
                missing_checks.append("Replacement Work Order requires replacement reason acknowledgement")

        if missing_checks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Engineering Release blocked. Missing mandatory verifications: {'; '.join(missing_checks)}."
            )

        now = datetime.now()

        # Update readiness record
        readiness.readiness_status = "RELEASED"
        readiness.engineer_id = current_user.id
        readiness.engineer_name = current_user.full_name
        readiness.released_at = now

        # Update authoritative columns on work_orders
        wo.engineering_released_by = current_user.full_name
        wo.engineering_released_at = now
        wo.engineering_document_name = "Engineering Drawing"
        wo.engineering_document_url = readiness.drawing_url
        wo.engineering_document_revision = readiness.verified_revision
        wo.engineering_remarks = readiness.remarks

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id,
            user_name=current_user.full_name,
            action="ENGINEERING_RELEASE",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            new_value=f"Revision: {readiness.verified_revision}, Status: RELEASED",
            details=f"Drawing: {readiness.drawing_url or 'N/A'}, Remarks: {readiness.remarks or 'None'}"
        )
        db.add(audit)

        db.commit()
        db.refresh(wo)

        return EngineeringReleaseResponse(
            success=True,
            wo_number=wo.wo_number,
            readiness_status="RELEASED",
            engineering_released_by=wo.engineering_released_by,
            engineering_released_at=wo.engineering_released_at,
            engineering_document_revision=wo.engineering_document_revision,
            message=f"Work Order '{wo.wo_number}' successfully released by Engineering."
        )

    # -----------------------------------------------------------------------
    # Engineering Release Revocation (Admin Only)
    # -----------------------------------------------------------------------

    @staticmethod
    def revoke_engineering_release(
        db: Session,
        wo_identifier: str,
        req: EngineeringRevocationRequest,
        current_user: User
    ) -> dict:
        # Only SUPER_ADMIN / ADMIN may revoke an Engineering Release
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only System Administrator can revoke an Engineering Release."
            )

        wo = EngineeringService._find_work_order(db, wo_identifier, for_update=True)
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{wo_identifier}' not found."
            )

        if getattr(wo, "engineering_released_at", None) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Work Order '{wo.wo_number}' has not been released by Engineering."
            )

        # Revocation Safety Gate 1: Manufacturing Release must not have been performed yet
        if getattr(wo, "manufacturing_released_at", None) is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Engineering Release cannot be revoked: Work Order '{wo.wo_number}' has already received Manufacturing Release."
            )

        # Revocation Safety Gate 2: Shop Floor Production Movement must not have started
        movement_count = db.query(ProductionMovement).filter(
            ProductionMovement.work_order_id == wo.id
        ).count()
        if movement_count > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Engineering Release cannot be revoked: Work Order '{wo.wo_number}' already has recorded shop-floor production movements."
            )

        old_released_by = wo.engineering_released_by
        old_released_at = wo.engineering_released_at
        old_rev = wo.engineering_document_revision

        # Clear authoritative release fields on work_orders
        wo.engineering_released_by = None
        wo.engineering_released_at = None

        # Reset readiness status to PENDING
        readiness = db.query(WOEngineeringReadiness).filter(
            WOEngineeringReadiness.work_order_id == wo.id
        ).first()
        if readiness:
            readiness.readiness_status = "PENDING"
            readiness.released_at = None
            readiness.remarks = f"[REVOKED by {current_user.full_name}: {req.revocation_reason}] " + (readiness.remarks or "")

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id,
            user_name=current_user.full_name,
            action="ENGINEERING_RELEASE_REVOKED",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            old_value=f"Released By: {old_released_by}, At: {old_released_at}, Rev: {old_rev}",
            new_value="Release Revoked (Status: PENDING)",
            details=f"Reason: {req.revocation_reason}"
        )
        db.add(audit)

        db.commit()
        db.refresh(wo)

        return {
            "success": True,
            "wo_number": wo.wo_number,
            "readiness_status": "PENDING",
            "message": f"Engineering Release for Work Order '{wo.wo_number}' was revoked. Reason: {req.revocation_reason}"
        }
