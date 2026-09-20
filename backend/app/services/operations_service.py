import math
import uuid
from datetime import datetime, date
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.order import Order, Customer, Part, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import StageWIP
from app.models.conversion import Conversion
from app.models.nc import NCRecord
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.operations import (
    OrderIntakeCreate, OrderIntakeResponse,
    WOReleaseCreate, WOReleaseResponse,
    ConversionCreate, ConversionResponse,
    NCRecordCreate, NCRecordUpdate, NCRecordOut
)
from app.services.oms_integration_service import (
    OMSIntegrationService,
    calculate_stage_targets,
    parse_route,
    match_route_stage,
    DEFAULT_YIELDS
)

class OperationsService:
    @staticmethod
    def create_order_intake(db: Session, req: OrderIntakeCreate, current_user: Optional[User] = None) -> OrderIntakeResponse:
        # 1. Customer
        customer = db.query(Customer).filter(Customer.customer_code == req.customer_code.strip().upper()).first()
        if not customer:
            customer = Customer(
                customer_code=req.customer_code.strip().upper(),
                name=req.customer_name.strip()
            )
            db.add(customer)
            db.flush()

        # 2. Part
        part = db.query(Part).filter(Part.part_number == req.part_number.strip().upper()).first()
        if not part:
            part = Part(
                part_number=req.part_number.strip().upper(),
                grade=req.grade or "Standard",
                description=req.part_description or f"Bronze Cast Component {req.part_number}"
            )
            db.add(part)
            db.flush()

        # 3. Order (OAR)
        order_count = db.query(Order).count()
        oar_num = f"OAR-{order_count + 1:04d}"
        
        order = Order(
            oar_number=oar_num,
            customer_id=customer.id,
            part_id=part.id,
            customer_po=req.customer_po.strip(),
            po_qty=req.po_quantity,
            max_batch_size=req.max_batch_size,
            delivery_date=req.delivery_date,
            order_type=req.order_type or "Standard",
            status=req.status
        )
        db.add(order)
        db.flush()

        created_wos = []
        if req.status == OrderStatus.ACCEPT:
            num_wos = math.ceil(req.po_quantity / req.max_batch_size)
            rem_qty = req.po_quantity
            default_route = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
            
            for i in range(num_wos):
                wo_qty = min(req.max_batch_size, rem_qty)
                rem_qty -= wo_qty
                
                wo_count = db.query(WorkOrder).count()
                wo_num = f"WO-{1000 + wo_count + 1}"
                
                wo = WorkOrder(
                    wo_number=wo_num,
                    order_id=order.id,
                    physical_wo_qty=wo_qty,
                    current_stage="F1",
                    projected_final_good=wo_qty,
                    shortfall="No",
                    status=WOStatus.IN_PRODUCTION
                )
                db.add(wo)
                db.flush()
                
                targets = calculate_stage_targets(wo_qty, route=default_route)
                for seq, stg in enumerate(default_route, start=1):
                    r = WORoute(
                        work_order_id=wo.id,
                        stage=stg,
                        sequence=seq,
                        stage_target_qty=targets.get(stg, wo_qty),
                        cumulative_ent_qty=wo_qty if seq == 1 else 0,
                        cumulative_inproc_qty=wo_qty if seq == 1 else 0,
                        stage_status="In-Progress" if seq == 1 else "Pending"
                    )
                    db.add(r)
                
                # Initial stage WIP at F1
                initial_wip = StageWIP(
                    work_order_id=wo.id,
                    stage="F1",
                    ent_qty=wo_qty,
                    ok_qty=0,
                    inproc_qty=wo_qty,
                    onhand_qty=0,
                    rejected_qty=0,
                    received_qty=wo_qty,
                    available_wip=wo_qty,
                    moved_out_qty=0
                )
                db.add(initial_wip)
                created_wos.append(wo_num)

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Sales / Planner",
            action="ORDER_INTAKE",
            entity="Order",
            entity_id=oar_num,
            new_value=f"PO: {req.customer_po}, Qty: {req.po_quantity}, WOs: {', '.join(created_wos)}",
            details=f"Customer: {customer.name}, Part: {part.part_number}, Batch Size: {req.max_batch_size}"
        )
        db.add(audit)

        db.commit()

        return OrderIntakeResponse(
            success=True,
            oar_number=oar_num,
            order_id=str(order.id),
            wos_created=created_wos,
            total_qty=req.po_quantity,
            message=f"Order '{oar_num}' created with {len(created_wos)} Work Order(s)."
        )

    @staticmethod
    def release_work_order(db: Session, req: WOReleaseCreate, current_user: Optional[User] = None) -> WOReleaseResponse:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        stages = [s.strip().upper() for s in req.route_stages if s.strip()]
        if not stages:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Route cannot be empty. At least one stage is required."
            )

        if "DISPATCH" not in stages:
            stages.append("DISPATCH")

        wo.physical_wo_qty = req.physical_wo_qty
        wo.released_by = current_user.full_name if current_user else "Planner"
        wo.release_date = datetime.now()
        wo.status = WOStatus.RELEASED
        wo.current_stage = stages[0]

        # Clear old routes and recalculate stage targets over the released route only
        db.query(WORoute).filter(WORoute.work_order_id == wo.id).delete()
        targets = calculate_stage_targets(req.physical_wo_qty, route=stages)
        
        for seq, stg in enumerate(stages, start=1):
            r = WORoute(
                work_order_id=wo.id,
                stage=stg,
                sequence=seq,
                stage_target_qty=targets.get(stg, req.physical_wo_qty),
                cumulative_ent_qty=req.physical_wo_qty if seq == 1 else 0,
                cumulative_inproc_qty=req.physical_wo_qty if seq == 1 else 0,
                stage_status="In-Progress" if seq == 1 else "Pending"
            )
            db.add(r)

        # Update initial stage WIP
        db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).delete()
        first_wip = StageWIP(
            work_order_id=wo.id,
            stage=stages[0],
            ent_qty=req.physical_wo_qty,
            ok_qty=0,
            inproc_qty=req.physical_wo_qty,
            onhand_qty=0,
            rejected_qty=0,
            received_qty=req.physical_wo_qty,
            available_wip=req.physical_wo_qty,
            moved_out_qty=0
        )
        db.add(first_wip)

        # Recompute OMS state
        OMSIntegrationService.recompute_work_order(db, wo)

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Planner",
            action="WO_RELEASE",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            new_value=f"Qty: {req.physical_wo_qty}, Route: {' -> '.join(stages)}",
            details=req.remarks or "Work Order released to production"
        )
        db.add(audit)

        db.commit()
        db.refresh(wo)

        return WOReleaseResponse(
            success=True,
            wo_number=wo.wo_number,
            released_qty=req.physical_wo_qty,
            route=" -> ".join(stages),
            stage_targets=targets,
            message=f"Work Order '{wo.wo_number}' successfully released with {req.physical_wo_qty} pieces."
        )

    @staticmethod
    def create_conversion(db: Session, req: ConversionCreate, current_user: Optional[User] = None) -> ConversionResponse:
        cwo_num = req.conversion_wo_number.strip()
        existing_wo = db.query(WorkOrder).filter(WorkOrder.wo_number == cwo_num).first()
        if existing_wo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Conversion WO ID '{cwo_num}' already exists. Planner must supply a unique Conversion WO name."
            )

        src_wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.source_wo_number.strip()).with_for_update().first()
        if not src_wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source Work Order '{req.source_wo_number}' not found."
            )

        dest_order = db.query(Order).filter(Order.oar_number == req.destination_oar_number.strip()).first()
        if not dest_order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Destination OAR '{req.destination_oar_number}' not found."
            )

        entry_stage = req.entry_stage.strip().upper()
        
        # Authoritative OMS Debit Stage Lookup:
        # The debit stage is the stage immediately preceding the entry stage on the source WO's route.
        src_routes = db.query(WORoute).filter(WORoute.work_order_id == src_wo.id).order_by(WORoute.sequence).all()
        src_stage_names = [r.stage.upper() for r in src_routes]
        
        if entry_stage in src_stage_names:
            e_idx = src_stage_names.index(entry_stage)
            debit_stage = src_routes[e_idx - 1].stage if e_idx > 0 else src_routes[0].stage
        else:
            # Fallback: last production stage or entry_stage
            debit_stage = entry_stage

        src_wip = db.query(StageWIP).filter(
            StageWIP.work_order_id == src_wo.id,
            StageWIP.stage == debit_stage
        ).with_for_update().first()

        if not src_wip or src_wip.available_wip < req.quantity:
            avail = src_wip.available_wip if src_wip else 0
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Source WO '{src_wo.wo_number}' only has {avail} pieces at debit stage '{debit_stage}', but {req.quantity} pieces requested for conversion."
            )

        # Debit source WO
        src_wip.available_wip -= req.quantity
        src_wip.moved_out_qty += req.quantity
        if src_wip.inproc_qty >= req.quantity:
            src_wip.inproc_qty -= req.quantity
        else:
            src_wip.onhand_qty = max(src_wip.onhand_qty - (req.quantity - src_wip.inproc_qty), 0)
            src_wip.inproc_qty = 0

        # Adjust source WO commitment target
        src_wo.physical_wo_qty = max(0, src_wo.physical_wo_qty - req.quantity)
        OMSIntegrationService.recompute_work_order(db, src_wo)

        # Create Conversion WO
        conv_wo = WorkOrder(
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
        db.add(conv_wo)
        db.flush()

        # Build route from entry stage onward through full sequence
        all_stages = ["F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"]
        entry_idx = all_stages.index(entry_stage) if entry_stage in all_stages else 0
        conv_route = all_stages[entry_idx:]

        conv_targets = calculate_stage_targets(req.quantity, route=conv_route)
        for seq, stg in enumerate(conv_route, start=1):
            r = WORoute(
                work_order_id=conv_wo.id,
                stage=stg,
                sequence=seq,
                stage_target_qty=conv_targets.get(stg, req.quantity),
                cumulative_ent_qty=req.quantity if seq == 1 else 0,
                cumulative_inproc_qty=req.quantity if seq == 1 else 0,
                stage_status="In-Progress" if seq == 1 else "Pending"
            )
            db.add(r)

        # Credit initial WIP to conversion WO at entry_stage
        conv_wip = StageWIP(
            work_order_id=conv_wo.id,
            stage=entry_stage,
            ent_qty=req.quantity,
            ok_qty=0,
            inproc_qty=req.quantity,
            onhand_qty=0,
            rejected_qty=0,
            received_qty=req.quantity,
            available_wip=req.quantity,
            moved_out_qty=0
        )
        db.add(conv_wip)
        OMSIntegrationService.recompute_work_order(db, conv_wo)

        # Log Conversion Record
        conv_record = Conversion(
            conversion_wo_number=cwo_num,
            source_wo_id=src_wo.id,
            destination_order_id=dest_order.id,
            conversion_wo_id=conv_wo.id,
            entry_stage=entry_stage,
            quantity=req.quantity,
            reason=req.reason,
            planner=current_user.full_name if current_user else "Planner"
        )
        db.add(conv_record)

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Planner",
            action="CONVERSION",
            entity="Conversion",
            entity_id=cwo_num,
            old_value=f"From WO: {src_wo.wo_number}, Debited: {req.quantity} at {debit_stage}",
            new_value=f"To WO: {cwo_num}, OAR: {dest_order.oar_number}",
            details=req.reason
        )
        db.add(audit)

        db.commit()

        return ConversionResponse(
            success=True,
            conversion_wo_number=cwo_num,
            source_wo_number=src_wo.wo_number,
            quantity=req.quantity,
            entry_stage=entry_stage,
            message=f"Successfully converted {req.quantity} pieces from {src_wo.wo_number} to {cwo_num} at stage {entry_stage}."
        )

    @staticmethod
    def get_nc_records(db: Session, limit: int = 500, offset: int = 0) -> List[NCRecordOut]:
        records = (
            db.query(NCRecord).order_by(NCRecord.date_raised.desc())
            .offset(offset).limit(limit).all()
        )
        results = []
        today = date.today()
        for r in records:
            wo = r.work_order
            part_no = wo.order.part.part_number if (wo and wo.order and wo.order.part) else "N/A"
            raised_dt = r.date_raised.date() if r.date_raised else today
            closed_dt = r.date_closed.date() if r.date_closed else None
            days_open = (closed_dt - raised_dt).days if closed_dt else (today - raised_dt).days
            
            results.append(NCRecordOut(
                id=str(r.id),
                nc_number=r.nc_number,
                wo_number=wo.wo_number if wo else "N/A",
                part_number=part_no,
                stage=r.stage or "F1",
                defect_code=r.defect_code or "DEF-POROSITY",
                qty=r.qty,
                root_cause=r.root_cause,
                disposition=r.disposition,
                responsibility=r.responsibility,
                status=r.status or "Open",
                days_open=days_open,
                date_raised=r.date_raised or datetime.now(),
                date_closed=r.date_closed,
                remarks=r.remarks
            ))
        return results

    @staticmethod
    def create_nc(db: Session, req: NCRecordCreate, current_user: Optional[User] = None) -> NCRecordOut:
        wo = db.query(WorkOrder).filter(WorkOrder.wo_number == req.wo_number.strip()).first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order '{req.wo_number}' not found."
            )

        count = db.query(NCRecord).count()
        nc_num = f"NC-{count + 1:05d}"
        now = datetime.now()

        nc = NCRecord(
            nc_number=nc_num,
            work_order_id=wo.id,
            stage=req.stage.strip().upper(),
            defect_code=req.defect_code.strip(),
            qty=req.qty,
            root_cause=req.root_cause,
            disposition=req.disposition or "Scrap",
            responsibility=req.responsibility or "Production",
            status="Open",
            date_raised=now,
            remarks=req.remarks
        )
        db.add(nc)

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "QA Officer",
            action="NC_CREATE",
            entity="NCRecord",
            entity_id=nc_num,
            new_value=f"WO: {wo.wo_number}, Qty: {req.qty}, Defect: {req.defect_code}",
            details=req.root_cause or "Non-Conformance raised"
        )
        db.add(audit)

        db.commit()
        db.refresh(nc)

        part_no = wo.order.part.part_number if (wo.order and wo.order.part) else "N/A"
        return NCRecordOut(
            id=str(nc.id),
            nc_number=nc.nc_number,
            wo_number=wo.wo_number,
            part_number=part_no,
            stage=nc.stage,
            defect_code=nc.defect_code,
            qty=nc.qty,
            root_cause=nc.root_cause,
            disposition=nc.disposition,
            responsibility=nc.responsibility,
            status=nc.status,
            days_open=0,
            date_raised=now,
            date_closed=None,
            remarks=nc.remarks
        )

    @staticmethod
    def update_nc(db: Session, req: NCRecordUpdate, current_user: Optional[User] = None) -> NCRecordOut:
        nc = db.query(NCRecord).filter(NCRecord.nc_number == req.nc_number.strip()).first()
        if not nc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"NC Record '{req.nc_number}' not found."
            )

        if req.status.upper() == "CLOSED":
            nc.status = "Closed"
            nc.date_closed = datetime.now()
        elif req.status.upper() == "OPEN":
            nc.status = "Open"
            nc.date_closed = None

        if req.root_cause is not None:
            nc.root_cause = req.root_cause
        if req.disposition is not None:
            nc.disposition = req.disposition
        if req.remarks is not None:
            nc.remarks = req.remarks

        # Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "QA Officer",
            action="NC_UPDATE",
            entity="NCRecord",
            entity_id=nc.nc_number,
            new_value=f"Status: {nc.status}, Root Cause: {nc.root_cause}, Disp: {nc.disposition}",
            details=req.remarks or "NC Record updated"
        )
        db.add(audit)

        db.commit()
        db.refresh(nc)

        wo = nc.work_order
        part_no = wo.order.part.part_number if (wo and wo.order and wo.order.part) else "N/A"
        today = date.today()
        raised_dt = nc.date_raised.date() if nc.date_raised else today
        closed_dt = nc.date_closed.date() if nc.date_closed else None
        days_open = (closed_dt - raised_dt).days if closed_dt else (today - raised_dt).days

        return NCRecordOut(
            id=str(nc.id),
            nc_number=nc.nc_number,
            wo_number=wo.wo_number if wo else "N/A",
            part_number=part_no,
            stage=nc.stage,
            defect_code=nc.defect_code,
            qty=nc.qty,
            root_cause=nc.root_cause,
            disposition=nc.disposition,
            responsibility=nc.responsibility,
            status=nc.status,
            days_open=days_open,
            date_raised=nc.date_raised or datetime.now(),
            date_closed=nc.date_closed,
            remarks=nc.remarks
        )
