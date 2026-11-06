from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, desc

from app.models.vendor import VendorDispatch
from app.models.work_order import WorkOrder, WORoute
from app.models.order import Order, Customer, Part
from app.models.production_movement import StageWIP, ProductionMovement
from app.models.audit import AuditLog
from app.models.user import User
from app.services.oms_integration_service import OMSIntegrationService


class VendorService:
    @staticmethod
    def list_dispatches(
        db: Session,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        query = db.query(VendorDispatch).join(WorkOrder, VendorDispatch.work_order_id == WorkOrder.id).join(Order).join(Customer)
        
        if status_filter and status_filter.upper() != "ALL":
            query = query.filter(VendorDispatch.status == status_filter.upper())
            
        if search and search.strip():
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    VendorDispatch.dc_number.ilike(s),
                    VendorDispatch.vendor_name.ilike(s),
                    WorkOrder.wo_number.ilike(s),
                    Order.oar_number.ilike(s),
                    Customer.name.ilike(s)
                )
            )
            
        dispatches = query.order_by(desc(VendorDispatch.dispatched_at)).offset(offset).limit(limit).all()
        
        results = []
        now = datetime.now()
        for d in dispatches:
            wo = d.work_order
            order = wo.order if wo else None
            part = order.part if order else None
            customer = order.customer if order else None
            
            # Calculate days at vendor
            disp_date = d.dispatched_at
            days_at_vendor = (now.date() - disp_date.date()).days if disp_date else 0
            
            results.append({
                "id": str(d.id),
                "work_order_id": str(wo.id) if wo else None,
                "wo_number": wo.wo_number if wo else "N/A",
                "oar_number": order.oar_number if order else "N/A",
                "customer_name": customer.name if customer else "N/A",
                "part_number": part.part_number if part else "N/A",
                "part_name": part.name if part else "N/A",
                "dispatch_stage": d.dispatch_stage or "F2",
                "vendor_name": d.vendor_name,
                "dc_number": d.dc_number,
                "dispatched_qty": d.dispatched_qty,
                "received_qty": d.received_qty or 0,
                "scrap_qty": d.scrap_qty or 0,
                "pending_qty": max(d.dispatched_qty - (d.received_qty or 0) - (d.scrap_qty or 0), 0),
                "status": d.status,
                "dispatched_at": d.dispatched_at,
                "received_at": d.received_at,
                "inward_dc_number": d.inward_dc_number,
                "remarks": d.remarks,
                "days_at_vendor": max(days_at_vendor, 0)
            })
            
        return results

    @staticmethod
    def get_summary(db: Session) -> Dict[str, Any]:
        all_dispatches = db.query(VendorDispatch).all()
        active = [d for d in all_dispatches if d.status in ("AT_VENDOR", "PARTIALLY_RECEIVED")]
        received = [d for d in all_dispatches if d.status == "RECEIVED"]
        
        total_active_pcs = sum(max(d.dispatched_qty - (d.received_qty or 0) - (d.scrap_qty or 0), 0) for d in active)
        total_received_pcs = sum(d.received_qty or 0 for d in all_dispatches)
        
        # Unique vendors
        vendors = list({d.vendor_name for d in all_dispatches if d.vendor_name})
        
        return {
            "active_dispatches_count": len(active),
            "completed_dispatches_count": len(received),
            "total_pieces_at_vendor": total_active_pcs,
            "total_pieces_received": total_received_pcs,
            "active_vendor_count": len(vendors)
        }

    @staticmethod
    def receive_from_vendor(
        db: Session,
        dispatch_id: str,
        received_qty: int,
        scrap_qty: int = 0,
        inward_dc: Optional[str] = None,
        remarks: Optional[str] = None,
        current_user: Optional[User] = None
    ) -> Dict[str, Any]:
        """Receives material returned from an outside subcontractor and lands it
        DIRECTLY into FI (Final Inspection) StageWIP, ready for inspection and move to BSR."""
        now = datetime.now()
        
        dispatch = db.query(VendorDispatch).filter(VendorDispatch.id == dispatch_id).with_for_update().first()
        if not dispatch:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vendor dispatch record '{dispatch_id}' not found."
            )
            
        if dispatch.status == "RECEIVED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Challan DC #{dispatch.dc_number} has already been fully received."
            )
            
        remaining_at_vendor = max(dispatch.dispatched_qty - (dispatch.received_qty or 0) - (dispatch.scrap_qty or 0), 0)
        total_incoming = received_qty + scrap_qty
        
        if total_incoming <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Received quantity must be greater than zero."
            )
            
        if total_incoming > remaining_at_vendor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot receive {total_incoming} pcs ({received_qty} OK + {scrap_qty} Scrap). Only {remaining_at_vendor} pcs are currently pending at vendor '{dispatch.vendor_name}' for DC #{dispatch.dc_number}."
            )
            
        wo = db.query(WorkOrder).filter(WorkOrder.id == dispatch.work_order_id).with_for_update().first()
        if not wo:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Work Order linked to dispatch was not found."
            )
            
        # 1. Update VendorDispatch record
        dispatch.received_qty = (dispatch.received_qty or 0) + received_qty
        dispatch.scrap_qty = (dispatch.scrap_qty or 0) + scrap_qty
        dispatch.inward_dc_number = inward_dc.strip() if inward_dc and inward_dc.strip() else dispatch.inward_dc_number
        if remarks and remarks.strip():
            dispatch.remarks = f"{dispatch.remarks or ''} | Inward: {remarks.strip()}".strip(" | ")
            
        if (dispatch.received_qty + dispatch.scrap_qty) >= dispatch.dispatched_qty:
            dispatch.status = "RECEIVED"
            dispatch.received_at = now
        else:
            dispatch.status = "PARTIALLY_RECEIVED"

        # 2. Consume from F2 onhand_qty
        f2_wip = db.query(StageWIP).filter(
            StageWIP.work_order_id == wo.id,
            StageWIP.stage == dispatch.dispatch_stage
        ).with_for_update().first()
        if f2_wip:
            f2_wip.onhand_qty = max(f2_wip.onhand_qty - total_incoming, 0)
            f2_wip.available_wip = max(f2_wip.available_wip - total_incoming, 0)

        # 3. Land directly in FI (Final Inspection) StageWIP
        # Intermediate in-house stages (such as SP) are bypassed because vendor finished external machining
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        route_stages = [r.stage for r in routes]
        
        # Ensure FI exists in route
        if "FI" not in route_stages:
            max_seq = max((r.sequence for r in routes), default=0)
            fi_route = WORoute(
                work_order_id=wo.id,
                stage="FI",
                sequence=max_seq + 1,
                stage_target_qty=wo.physical_wo_qty,
                stage_status="In-Progress"
            )
            db.add(fi_route)
            db.flush()

        fi_wip = db.query(StageWIP).filter(
            StageWIP.work_order_id == wo.id,
            StageWIP.stage == "FI"
        ).with_for_update().first()
        
        if not fi_wip:
            fi_wip = StageWIP(
                work_order_id=wo.id,
                stage="FI",
                ent_qty=received_qty,
                ok_qty=0,
                inproc_qty=received_qty,
                onhand_qty=0,
                rejected_qty=0,
                available_wip=received_qty,
                received_qty=received_qty
            )
            db.add(fi_wip)
        else:
            fi_wip.ent_qty += received_qty
            fi_wip.inproc_qty += received_qty
            fi_wip.available_wip += received_qty
            fi_wip.received_qty += received_qty

        # Set Work Order current stage to FI
        wo.current_stage = "FI"

        # 4. Record Immutable ProductionMovement ledger row
        mov = ProductionMovement(
            work_order_id=wo.id,
            from_stage=f"{dispatch.dispatch_stage} (VENDOR)",
            to_stage="FI",
            quantity_moved=received_qty,
            rejected_quantity=scrap_qty,
            production_type="VENDOR",
            vendor_name=dispatch.vendor_name,
            dc_number=inward_dc or dispatch.dc_number,
            operator_name=current_user.full_name if current_user else "Store / Quality Receiver",
            movement_date=str(now.date()),
            movement_time=now.strftime("%H:%M:%S"),
            heat_number=wo.heat_number,
            remarks=f"Inward from Vendor '{dispatch.vendor_name}' (Out DC #{dispatch.dc_number}, In DC #{inward_dc or 'N/A'}) directly to FI.",
            created_by=current_user.id if current_user else None
        )
        db.add(mov)

        # 5. Audit Log
        audit = AuditLog(
            user_id=current_user.id if current_user else None,
            user_name=current_user.full_name if current_user else "Store / Quality Receiver",
            action="VENDOR_MATERIAL_RECEIVED_TO_FI",
            entity="WorkOrder",
            entity_id=wo.wo_number,
            old_value=f"At Vendor: {dispatch.vendor_name} (DC #{dispatch.dc_number})",
            new_value=f"Received: {received_qty} pcs, Scrap: {scrap_qty} pcs -> Landed in FI",
            details=f"Inward reception from vendor {dispatch.vendor_name} to Final Inspection. Inward DC: {inward_dc or 'N/A'}"
        )
        db.add(audit)

        # 6. Recompute Work Order
        OMSIntegrationService.recompute_work_order(db, wo)
        
        db.commit()
        db.refresh(dispatch)
        
        return {
            "success": True,
            "message": f"Successfully received {received_qty} pcs from {dispatch.vendor_name} directly into Final Inspection (FI).",
            "dispatch_id": str(dispatch.id),
            "wo_number": wo.wo_number,
            "received_qty": received_qty,
            "scrap_qty": scrap_qty,
            "status": dispatch.status,
            "current_stage": "FI"
        }
