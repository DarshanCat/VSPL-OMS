from datetime import datetime
from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.mrb import MRBReview, next_mrb_number
from app.models.work_order import WorkOrder
from app.models.order import Order, Customer, Part
from app.models.production import ProductionUpdate
from app.models.production_movement import StageWIP
from app.models.nc import NCRecord
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.mrb import (
    MRBReviewItem,
    MRBReviewDecisionRequest,
    MRBListResponse,
    MRBDecisionResponse
)
from app.services.oms_integration_service import OMSIntegrationService


class MRBService:
    @staticmethod
    def backfill_mrb_from_production_updates(db: Session) -> int:
        """Ensures all existing shop floor production entries have corresponding
        MRB review tickets so the Quality, Planner, and Admin board is complete."""
        existing_pu_ids = {
            r[0] for r in db.query(MRBReview.production_update_id)
            .filter(MRBReview.production_update_id.isnot(None)).all()
        }
        all_pus = db.query(ProductionUpdate).all()
        created = 0
        for pu in all_pus:
            if pu.id not in existing_pu_ids:
                mrb_num = next_mrb_number(db)
                mrb = MRBReview(
                    mrb_number=mrb_num,
                    production_update_id=pu.id,
                    work_order_id=pu.work_order_id,
                    stage=pu.stage,
                    machine_id=pu.machine,
                    operator_name=pu.operator_name or "Floor Operator",
                    shift=pu.shift or "Shift A",
                    heat_number=pu.heat_number,
                    reported_ok_qty=pu.good_qty or 0,
                    reported_reject_qty=pu.reject_qty or 0,
                    reported_defect_code=None,
                    floor_remarks=pu.remarks or "Historical floor production entry",
                    verified_ok_qty=pu.good_qty or 0,
                    verified_reject_qty=pu.reject_qty or 0,
                    status="PENDING",
                    disposition="PENDING",
                    created_at=pu.created_at or datetime.now()
                )
                db.add(mrb)
                existing_pu_ids.add(pu.id)
                created += 1
        if created > 0:
            db.commit()
        return created

    @staticmethod
    def _to_review_item(mrb: MRBReview, wo: Optional[WorkOrder] = None) -> MRBReviewItem:
        work_order = wo or mrb.work_order
        wo_number = work_order.wo_number if work_order else "N/A"
        part_number = None
        part_name = None
        customer_name = None

        if work_order and work_order.order:
            if work_order.order.part:
                part_number = work_order.order.part.part_number
                part_name = work_order.order.part.description
            if work_order.order.customer:
                customer_name = work_order.order.customer.name

        return MRBReviewItem(
            id=str(mrb.id),
            mrb_number=mrb.mrb_number,
            production_update_id=str(mrb.production_update_id) if mrb.production_update_id else None,
            movement_id=str(mrb.movement_id) if mrb.movement_id else None,
            work_order_id=str(mrb.work_order_id),
            wo_number=wo_number,
            part_number=part_number,
            part_name=part_name,
            customer_name=customer_name,
            stage=mrb.stage,
            machine_id=mrb.machine_id,
            operator_name=mrb.operator_name,
            shift=mrb.shift,
            heat_number=mrb.heat_number,
            reported_ok_qty=mrb.reported_ok_qty,
            reported_reject_qty=mrb.reported_reject_qty,
            reported_defect_code=mrb.reported_defect_code,
            floor_remarks=mrb.floor_remarks,
            verified_ok_qty=mrb.verified_ok_qty,
            verified_reject_qty=mrb.verified_reject_qty,
            verified_defect_code=mrb.verified_defect_code,
            status=mrb.status,
            disposition=mrb.disposition,
            reviewed_by_id=str(mrb.reviewed_by_id) if mrb.reviewed_by_id else None,
            reviewed_by_name=mrb.reviewed_by_name,
            reviewed_at=mrb.reviewed_at,
            review_notes=mrb.review_notes,
            created_at=mrb.created_at,
            updated_at=mrb.updated_at
        )

    @classmethod
    def list_reviews(
        cls,
        db: Session,
        status_filter: Optional[str] = None,
        stage: Optional[str] = None,
        wo_number: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 200,
        offset: int = 0
    ) -> MRBListResponse:
        # Auto-backfill to guarantee all production entries are present
        cls.backfill_mrb_from_production_updates(db)

        query = db.query(MRBReview).join(WorkOrder, MRBReview.work_order_id == WorkOrder.id)

        # Filters
        if status_filter and status_filter.upper() != "ALL":
            query = query.filter(MRBReview.status == status_filter.upper())
        if stage and stage.strip():
            query = query.filter(MRBReview.stage == stage.strip().upper())
        if wo_number and wo_number.strip():
            query = query.filter(WorkOrder.wo_number.ilike(f"%{wo_number.strip()}%"))
        if search and search.strip():
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    MRBReview.mrb_number.ilike(s),
                    WorkOrder.wo_number.ilike(s),
                    MRBReview.operator_name.ilike(s),
                    MRBReview.machine_id.ilike(s),
                    MRBReview.heat_number.ilike(s),
                    MRBReview.reported_defect_code.ilike(s)
                )
            )

        # Summary KPIs across entire dataset
        total_count = db.query(MRBReview).count()
        pending_count = db.query(MRBReview).filter(MRBReview.status == "PENDING").count()
        approved_count = db.query(MRBReview).filter(MRBReview.status == "APPROVED").count()
        adjusted_count = db.query(MRBReview).filter(MRBReview.status == "ADJUSTED").count()
        rejected_count = db.query(MRBReview).filter(MRBReview.status == "REJECTED").count()

        items = query.order_by(
            # Prioritize PENDING tickets first, then newest
            MRBReview.status.desc(),
            MRBReview.created_at.desc()
        ).offset(offset).limit(limit).all()

        return MRBListResponse(
            total_count=total_count,
            pending_count=pending_count,
            approved_count=approved_count,
            adjusted_count=adjusted_count,
            rejected_count=rejected_count,
            items=[cls._to_review_item(item) for item in items]
        )

    @staticmethod
    def _find_review(db: Session, review_id: str, for_update: bool = False) -> Optional[MRBReview]:
        import uuid
        is_uuid = False
        try:
            uuid.UUID(str(review_id).strip())
            is_uuid = True
        except (ValueError, AttributeError):
            pass

        query = db.query(MRBReview)
        if is_uuid:
            query = query.filter(or_(MRBReview.id == review_id.strip(), MRBReview.mrb_number == review_id.strip()))
        else:
            query = query.filter(MRBReview.mrb_number == review_id.strip())

        if for_update and db.bind and db.bind.dialect.name != "sqlite":
            query = query.with_for_update()
        return query.first()

    @classmethod
    def get_review(cls, db: Session, review_id: str) -> MRBReviewItem:
        review = cls._find_review(db, review_id)
        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MRB Review ticket '{review_id}' not found."
            )
        return cls._to_review_item(review)

    @classmethod
    def process_review_decision(
        cls,
        db: Session,
        review_id: str,
        req: MRBReviewDecisionRequest,
        current_user: User
    ) -> MRBDecisionResponse:
        review = cls._find_review(db, review_id, for_update=True)

        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MRB Review ticket '{review_id}' not found."
            )

        action = req.action.upper().strip()
        now = datetime.now()
        wo = db.query(WorkOrder).filter(WorkOrder.id == review.work_order_id).first()

        if action == "APPROVE":
            # Verification confirms the reported floor quantities
            v_ok = req.verified_ok_qty if req.verified_ok_qty is not None else review.reported_ok_qty
            v_rej = req.verified_reject_qty if req.verified_reject_qty is not None else review.reported_reject_qty
            v_defect = req.verified_defect_code or review.reported_defect_code

            # If user submitted adjustments during approval, process quantity diffs
            if v_ok != review.reported_ok_qty or v_rej != review.reported_reject_qty:
                cls._apply_quantity_adjustments(db, review, wo, v_ok, v_rej, v_defect)
                review.status = "ADJUSTED"
            else:
                review.status = "APPROVED"

            review.verified_ok_qty = v_ok
            review.verified_reject_qty = v_rej
            review.verified_defect_code = v_defect
            review.disposition = req.disposition or ("SCRAP" if v_rej > 0 else "VERIFIED_OK")
            msg = f"MRB Review {review.mrb_number} successfully approved by {current_user.full_name}."

        elif action == "ADJUST":
            if req.verified_ok_qty is None or req.verified_reject_qty is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Adjust action requires verified_ok_qty and verified_reject_qty."
                )

            v_ok = req.verified_ok_qty
            v_rej = req.verified_reject_qty
            v_defect = req.verified_defect_code or review.reported_defect_code

            cls._apply_quantity_adjustments(db, review, wo, v_ok, v_rej, v_defect)

            review.verified_ok_qty = v_ok
            review.verified_reject_qty = v_rej
            review.verified_defect_code = v_defect
            review.status = "ADJUSTED"
            review.disposition = req.disposition or "SCRAP"
            msg = f"MRB Review {review.mrb_number} quantities adjusted (OK: {v_ok}, Rej: {v_rej}) by {current_user.full_name}."

        elif action == "REJECT":
            review.status = "REJECTED"
            review.disposition = req.disposition or "FLAGGED_FOR_INVESTIGATION"
            review.verified_ok_qty = req.verified_ok_qty if req.verified_ok_qty is not None else 0
            review.verified_reject_qty = req.verified_reject_qty if req.verified_reject_qty is not None else 0
            msg = f"MRB Review {review.mrb_number} rejected/flagged for investigation by {current_user.full_name}."

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported MRB action '{req.action}'. Must be 'APPROVE', 'ADJUST', or 'REJECT'."
            )

        review.reviewed_by_id = current_user.id
        review.reviewed_by_name = current_user.full_name
        review.reviewed_at = now
        review.review_notes = req.review_notes

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id,
            user_name=current_user.full_name,
            action=f"MRB_{review.status}",
            entity="MRBReview",
            entity_id=review.mrb_number,
            old_value=f"Reported OK: {review.reported_ok_qty}, Rej: {review.reported_reject_qty}",
            new_value=f"Verified OK: {review.verified_ok_qty}, Rej: {review.verified_reject_qty}, Disposition: {review.disposition}",
            details=f"MRB Decision on WO {wo.wo_number if wo else 'N/A'} at {review.stage}: {req.review_notes or 'No notes'}"
        )
        db.add(audit)
        db.commit()
        db.refresh(review)

        return MRBDecisionResponse(
            success=True,
            message=msg,
            item=cls._to_review_item(review, wo)
        )

    @staticmethod
    def _apply_quantity_adjustments(
        db: Session,
        review: MRBReview,
        wo: Optional[WorkOrder],
        new_ok: int,
        new_rej: int,
        defect_code: Optional[str]
    ) -> None:
        """Adjusts StageWIP, ProductionUpdate, and NC records when MRB modifies
        floor reported quantities."""
        prior_ok = review.verified_ok_qty if review.verified_ok_qty is not None else review.reported_ok_qty
        prior_rej = review.verified_reject_qty if review.verified_reject_qty is not None else review.reported_reject_qty

        diff_ok = new_ok - prior_ok
        diff_rej = new_rej - prior_rej

        if diff_ok == 0 and diff_rej == 0:
            return

        if wo:
            wip = db.query(StageWIP).filter(
                StageWIP.work_order_id == wo.id,
                StageWIP.stage == review.stage
            ).with_for_update().first()

            if wip:
                adj_ok = wip.ok_qty + diff_ok
                adj_rej = wip.rejected_qty + diff_rej
                if adj_ok < 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Adjustment of OK qty would result in negative stage OK count ({adj_ok})."
                    )
                if adj_rej < 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Adjustment of Rejection qty would result in negative stage Rejection count ({adj_rej})."
                    )
                wip.ok_qty = adj_ok
                wip.rejected_qty = adj_rej

        # Adjust ProductionUpdate if linked
        if review.production_update_id:
            pu = db.query(ProductionUpdate).filter(
                ProductionUpdate.id == review.production_update_id
            ).first()
            if pu:
                pu.good_qty = new_ok
                pu.reject_qty = new_rej

        # Sync NC Record if one exists for this rejection
        if diff_rej != 0 and wo:
            nc = db.query(NCRecord).filter(
                NCRecord.work_order_id == wo.id,
                NCRecord.stage == review.stage
            ).order_by(NCRecord.created_at.desc()).first()
            if nc and nc.qty == prior_rej:
                nc.qty = new_rej
                if defect_code:
                    nc.defect_code = defect_code

        # Recompute entire WO downstream targets and status
        if wo:
            OMSIntegrationService.recompute_work_order(db, wo)
