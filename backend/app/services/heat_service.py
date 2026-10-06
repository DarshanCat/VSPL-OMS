import uuid
from typing import List, Optional
from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.heat import Heat, WorkOrderHeatAllocation
from app.models.work_order import WorkOrder, WORoute
from app.models.production_movement import StageWIP
from app.models.dispatch import Dispatch
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.heat import (
    HeatCreate, HeatResponse,
    HeatAllocationCreate, HeatAllocationItem,
    WOHeatAllocationResponse, HeatAllocationResponseItem,
    TraceabilityResponse, StageTraceabilityItem, DispatchTraceabilityItem
)

class HeatService:
    @staticmethod
    def get_heats(
        db: Session,
        grade: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[HeatResponse]:
        query = db.query(Heat)
        if grade:
            query = query.filter(Heat.grade.ilike(f"%{grade.strip()}%"))
        if status_filter:
            query = query.filter(Heat.status == status_filter.strip().upper())
        if search:
            search_term = f"%{search.strip()}%"
            query = query.filter(
                (Heat.heat_number.ilike(search_term)) |
                (Heat.grade.ilike(search_term)) |
                (Heat.tc_number.ilike(search_term))
            )

        heats = query.order_by(Heat.created_at.desc()).offset(offset).limit(limit).all()
        results = []
        for h in heats:
            alloc_sum = db.query(func.coalesce(func.sum(WorkOrderHeatAllocation.allocated_qty), 0)).filter(
                WorkOrderHeatAllocation.heat_id == h.id
            ).scalar()
            results.append(HeatResponse(
                id=str(h.id),
                heat_number=h.heat_number,
                grade=h.grade,
                melt_date=h.melt_date,
                status=h.status,
                tc_number=h.tc_number,
                supplier_or_foundry=h.supplier_or_foundry,
                remarks=h.remarks,
                created_at=h.created_at or datetime.now(),
                total_allocated_qty=int(alloc_sum)
            ))
        return results

    @staticmethod
    def create_heat(db: Session, req: HeatCreate, current_user: Optional[User] = None) -> HeatResponse:
        clean_number = req.heat_number.strip().upper()
        existing = db.query(Heat).filter(Heat.heat_number == clean_number).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Heat number '{clean_number}' already exists in database."
            )

        heat = Heat(
            heat_number=clean_number,
            grade=req.grade.strip(),
            melt_date=req.melt_date,
            status=(req.status or "ACTIVE").strip().upper(),
            tc_number=req.tc_number.strip() if req.tc_number else None,
            supplier_or_foundry=req.supplier_or_foundry.strip() if req.supplier_or_foundry else None,
            remarks=req.remarks
        )
        db.add(heat)

        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Metallurgy Dept",
            action="CREATE_HEAT",
            entity="Heat",
            entity_id=clean_number,
            new_value=f"Grade: {req.grade}, TC: {req.tc_number or 'N/A'}",
            details=f"Created heat batch {clean_number}"
        )
        db.add(audit)
        db.commit()
        db.refresh(heat)

        return HeatResponse(
            id=str(heat.id),
            heat_number=heat.heat_number,
            grade=heat.grade,
            melt_date=heat.melt_date,
            status=heat.status,
            tc_number=heat.tc_number,
            supplier_or_foundry=heat.supplier_or_foundry,
            remarks=heat.remarks,
            created_at=heat.created_at,
            total_allocated_qty=0
        )

    @staticmethod
    def allocate_heats_to_wo(
        db: Session,
        wo_number: str,
        req: HeatAllocationCreate,
        production_update_id: Optional[uuid.UUID] = None,
        current_user: Optional[User] = None
    ) -> WOHeatAllocationResponse:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number.strip()).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{wo_number}' not found."
            )

        total_alloc_req = sum(item.allocated_qty for item in req.allocations)
        if total_alloc_req <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Total allocated quantity must be greater than zero."
            )

        # Validate each heat and create allocation records
        created_allocations = []
        for item in req.allocations:
            clean_heat = item.heat_number.strip().upper()
            heat = db.query(Heat).filter(Heat.heat_number == clean_heat).first()
            if not heat:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Heat '{clean_heat}' not found. Please register heat in Heat Master first."
                )

            if heat.status == "QUARANTINED":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Heat '{clean_heat}' is marked QUARANTINED and cannot be allocated."
                )

            alloc = WorkOrderHeatAllocation(
                work_order_id=wo.id,
                heat_id=heat.id,
                allocated_qty=item.allocated_qty,
                stage=req.stage or "F1",
                production_update_id=production_update_id,
                allocated_by=current_user.id if current_user else None,
                remarks=req.remarks
            )
            db.add(alloc)
            created_allocations.append(alloc)

        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Foundry Operator",
            action="ALLOCATE_HEAT",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            new_value=f"Allocated {total_alloc_req} pcs across {len(req.allocations)} heats",
            details=f"Heats: {', '.join(f'{item.heat_number} ({item.allocated_qty})' for item in req.allocations)}"
        )
        db.add(audit)
        db.commit()

        # Build response with all historic allocations for this WO
        all_allocs = db.query(WorkOrderHeatAllocation).filter(
            WorkOrderHeatAllocation.work_order_id == wo.id
        ).order_by(WorkOrderHeatAllocation.allocated_at.desc()).all()

        response_items = []
        total_allocated = 0
        for a in all_allocs:
            total_allocated += a.allocated_qty
            response_items.append(HeatAllocationResponseItem(
                id=str(a.id),
                heat_number=a.heat.heat_number,
                grade=a.heat.grade,
                tc_number=a.heat.tc_number,
                allocated_qty=a.allocated_qty,
                stage=a.stage,
                allocated_at=a.allocated_at,
                allocated_by=a.allocator.full_name if a.allocator else None,
                remarks=a.remarks
            ))

        return WOHeatAllocationResponse(
            wo_number=wo.wo_number,
            allocations=response_items,
            total_heat_allocated_qty=total_allocated
        )

    @staticmethod
    def get_wo_traceability(db: Session, wo_number: str) -> TraceabilityResponse:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == wo_number.strip()).first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{wo_number}' not found."
            )

        order = wo.order
        customer = order.customer if order else None
        part = order.part if order else None

        # 1. Heat Allocations
        allocs = db.query(WorkOrderHeatAllocation).filter(
            WorkOrderHeatAllocation.work_order_id == wo.id
        ).order_by(WorkOrderHeatAllocation.allocated_at.asc()).all()

        heat_items = []
        total_heat_qty = 0
        for a in allocs:
            total_heat_qty += a.allocated_qty
            heat_items.append(HeatAllocationResponseItem(
                id=str(a.id),
                heat_number=a.heat.heat_number,
                grade=a.heat.grade,
                tc_number=a.heat.tc_number,
                allocated_qty=a.allocated_qty,
                stage=a.stage,
                allocated_at=a.allocated_at,
                allocated_by=a.allocator.full_name if a.allocator else None,
                remarks=a.remarks
            ))

        # 2. Stage Progression
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        wip_map = {w.stage: w for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}

        progression = []
        for r in routes:
            w = wip_map.get(r.stage)
            progression.append(StageTraceabilityItem(
                stage=r.stage,
                sequence=r.sequence,
                target_qty=r.stage_target_qty,
                ok_qty=w.ok_qty if w else 0,
                rejected_qty=w.rejected_qty if w else 0,
                inproc_qty=w.inproc_qty if w else 0,
                onhand_qty=w.onhand_qty if w else 0,
                status=r.stage_status or "Pending"
            ))

        # 3. Dispatches
        dispatches = db.query(Dispatch).filter(Dispatch.work_order_id == wo.id).order_by(Dispatch.dispatch_date.asc()).all()
        dispatch_items = [
            DispatchTraceabilityItem(
                invoice_number=d.invoice_number or "N/A",
                dispatched_qty=d.dispatched_qty,
                dispatch_date=d.dispatch_date,
                customer_po=d.customer_po
            )
            for d in dispatches
        ]

        return TraceabilityResponse(
            wo_number=wo.wo_number,
            oar_number=order.oar_number if order else None,
            customer_code=customer.customer_code if customer else None,
            customer_name=customer.name if customer else None,
            customer_po=order.customer_po if order else None,
            part_number=part.part_number if part else None,
            part_description=part.description if part else None,
            grade=part.grade if part else None,
            physical_wo_qty=wo.physical_wo_qty,
            current_stage=wo.current_stage,
            status=wo.status.value,
            heats=heat_items,
            total_heat_allocated_qty=total_heat_qty,
            stage_progression=progression,
            dispatches=dispatch_items
        )
