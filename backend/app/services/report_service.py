import io
import csv
from typing import List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord

class ReportService:
    @staticmethod
    def generate_wip_csv(db: Session) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        
        stages = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
        writer.writerow(["WO Number", "Customer", "Customer PO", "Part Number", "Current Stage", "Status", "Order Qty"] + stages + ["Total WIP"])

        active_wos = db.query(WorkOrder).filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED])).all()
        for wo in active_wos:
            order = wo.order
            cust = order.customer.name if (order and order.customer) else "N/A"
            po = order.customer_po if order else "N/A"
            part = order.part.part_number if (order and order.part) else "N/A"
            
            wips = {w.stage.upper(): w.available_wip for w in db.query(StageWIP).filter(StageWIP.work_order_id == wo.id).all()}
            if not wips:
                wips[wo.current_stage.upper()] = wo.physical_wo_qty

            row = [
                wo.wo_number,
                cust,
                po,
                part,
                wo.current_stage,
                wo.status.value,
                wo.physical_wo_qty
            ]
            for s in stages:
                row.append(wips.get(s, 0))
            row.append(sum(wips.values()))
            writer.writerow(row)

        return output.getvalue()

    @staticmethod
    def generate_movements_csv(db: Session) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Movement ID", "Timestamp", "WO Number", "Part Number", "From Stage", "To Stage", "Qty Moved", "Qty Rejected", "Machine", "Operator", "Shift", "Remarks"])

        movements = db.query(ProductionMovement).order_by(ProductionMovement.created_at.desc()).all()
        for m in movements:
            wo = m.work_order
            part = wo.order.part.part_number if (wo and wo.order and wo.order.part) else "N/A"
            writer.writerow([
                m.movement_id,
                m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "",
                wo.wo_number if wo else "N/A",
                part,
                m.from_stage,
                m.to_stage,
                m.quantity_moved,
                m.rejected_quantity,
                m.machine_id or "",
                m.operator_name or "",
                m.shift or "",
                m.remarks or ""
            ])

        return output.getvalue()

    @staticmethod
    def generate_dispatch_csv(db: Session) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Invoice Number", "Date", "WO Number", "Customer", "Customer PO", "Part Number", "Dispatched Qty", "Dispatcher"])

        dispatches = db.query(Dispatch).order_by(Dispatch.dispatch_date.desc()).all()
        for d in dispatches:
            wo = d.work_order
            order = wo.order if wo else None
            cust = order.customer.name if (order and order.customer) else "N/A"
            po = d.customer_po or (order.customer_po if order else "")
            part = order.part.part_number if (order and order.part) else "N/A"
            dispatcher = d.dispatcher.full_name if d.dispatcher else "Dispatch Dept"

            writer.writerow([
                d.invoice_number,
                d.dispatch_date.strftime("%Y-%m-%d") if d.dispatch_date else "",
                wo.wo_number if wo else "N/A",
                cust,
                po,
                part,
                d.dispatched_qty,
                dispatcher
            ])

        return output.getvalue()
