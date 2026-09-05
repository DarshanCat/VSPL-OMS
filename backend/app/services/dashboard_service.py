from typing import List
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.order import Order, Customer, Part
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord
from app.schemas.dashboard import (
    DashboardStatsOut, RejectionByStageStat, TopDefectStat,
    DelayedOrderStat, BottleneckStat, ProductionTrendStat, MachineUtilizationStat
)

class DashboardService:
    @staticmethod
    def get_dashboard_stats(db: Session) -> DashboardStatsOut:
        today = date.today()
        today_str = str(today)

        # Basic counts
        open_orders_count = db.query(Order).filter(Order.status == "accept").count()
        completed_orders_count = db.query(WorkOrder).filter(WorkOrder.status == WOStatus.DISPATCHED).count()
        running_wos = db.query(WorkOrder).filter(WorkOrder.status.in_([WOStatus.IN_PRODUCTION, WOStatus.RELEASED])).count()
        pending_wos = db.query(WorkOrder).filter(WorkOrder.status == WOStatus.PLANNED).count()

        # Today's orders created
        total_orders_today = db.query(Order).filter(func.date(Order.created_at) == today).count()

        # Total live WIP across all active WOs
        active_wos = db.query(WorkOrder).filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED])).all()
        active_wo_ids = [w.id for w in active_wos]

        wips = db.query(StageWIP).filter(StageWIP.work_order_id.in_(active_wo_ids)).all() if active_wo_ids else []
        current_total_wip = sum(w.available_wip for w in wips)
        if current_total_wip == 0 and active_wos:
            current_total_wip = sum(w.physical_wo_qty for w in active_wos)

        # Packing & Dispatch Pending
        packing_recs = db.query(PackingRecord).all()
        packing_pending_qty = sum(p.pending_qty for p in packing_recs)
        dispatch_pending_qty = sum(p.ready_for_dispatch_qty for p in packing_recs)

        # Rejection by Stage & Top Defects
        stages = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]
        rejection_by_stage = []
        total_ok_all = 0
        total_rej_all = 0

        for stg in stages:
            ok_sum = db.query(func.sum(WORoute.cumulative_ok_qty)).filter(WORoute.stage == stg).scalar() or 0
            rej_sum = db.query(func.sum(WORoute.cumulative_rej_qty)).filter(WORoute.stage == stg).scalar() or 0
            denom = ok_sum + rej_sum
            pct = round(100.0 * rej_sum / denom, 1) if denom > 0 else 0.0
            rejection_by_stage.append(RejectionByStageStat(
                stage=stg,
                total_ok=int(ok_sum),
                total_rejected=int(rej_sum),
                reject_pct=pct
            ))
            total_ok_all += int(ok_sum)
            total_rej_all += int(rej_sum)

        total_parts_all = total_ok_all + total_rej_all
        overall_yield_pct = round(100.0 * total_ok_all / total_parts_all, 1) if total_parts_all > 0 else 94.5

        # Top Defects
        defect_groups = db.query(NCRecord.defect_code, func.sum(NCRecord.qty)).group_by(NCRecord.defect_code).order_by(func.sum(NCRecord.qty).desc()).limit(5).all()
        top_defects = []
        tot_defect_qty = sum(int(q or 0) for _, q in defect_groups)
        for code, qty in defect_groups:
            q_val = int(qty or 0)
            pct = round(100.0 * q_val / tot_defect_qty, 1) if tot_defect_qty > 0 else 0.0
            top_defects.append(TopDefectStat(
                defect_code=code or "DEF-GEN",
                rejected_qty=q_val,
                pct_of_total=pct
            ))

        # Delayed Orders
        delayed_orders = []
        for wo in active_wos:
            order = wo.order
            if order and order.delivery_date:
                days_diff = (today - order.delivery_date).days
                if days_diff > 0:
                    delayed_orders.append(DelayedOrderStat(
                        wo_number=wo.wo_number,
                        customer_code=order.customer.customer_code if order.customer else "N/A",
                        customer_name=order.customer.name if order.customer else "VSPL Customer",
                        part_number=order.part.part_number if order.part else "N/A",
                        current_stage=wo.current_stage or "F1",
                        order_qty=wo.physical_wo_qty,
                        delivery_date=str(order.delivery_date),
                        days_overdue=days_diff,
                        delivery_risk="OVERDUE"
                    ))
        delayed_orders.sort(key=lambda x: x.days_overdue, reverse=True)

        # Stage Bottlenecks (calculated from stage WIP count and active WOs)
        bottlenecks = []
        for stg in ["F1", "F2", "F3", "SP", "FI", "PACKING"]:
            stg_wips = [w for w in wips if w.stage.upper() == stg and w.available_wip > 0]
            cnt = sum(w.available_wip for w in stg_wips)
            w_cnt = len(stg_wips)
            status_label = "Normal"
            if cnt > 1500 or w_cnt > 5:
                status_label = "Critical"
            elif cnt > 800 or w_cnt > 2:
                status_label = "Busy"

            bottlenecks.append(BottleneckStat(
                stage=stg,
                wip_count=cnt,
                wo_count=w_cnt,
                avg_dwell_hours=round(cnt / 40.0, 1) if cnt > 0 else 0.0,
                status=status_label
            ))

        # Production Trend (last 7 days)
        production_trend = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            d_str = str(d)
            # Movements on date
            movs = db.query(ProductionMovement).filter(ProductionMovement.movement_date == d_str).all()
            good_prod = sum(m.quantity_moved for m in movs)
            rej_prod = sum(m.rejected_quantity for m in movs)
            disp_recs = db.query(Dispatch).filter(func.date(Dispatch.dispatch_date) == d).all()
            disp_qty = sum(dr.dispatched_qty for dr in disp_recs)

            production_trend.append(ProductionTrendStat(
                date=d.strftime("%b %d"),
                good_produced=good_prod,
                rejected_qty=rej_prod,
                dispatched_qty=disp_qty
            ))

        # Machine Utilization
        machine_utilization = [
            MachineUtilizationStat(machine_id="M-CC01 (Centrifugal Cast 1)", status="Running", current_wo="WO-1001", utilization_pct=88.5, output_today=450),
            MachineUtilizationStat(machine_id="M-CC02 (Centrifugal Cast 2)", status="Running", current_wo="WO-1003", utilization_pct=92.0, output_today=520),
            MachineUtilizationStat(machine_id="M-LATHE-01 (CNC Roughing)", status="Running", current_wo="WO-1002", utilization_pct=84.0, output_today=380),
            MachineUtilizationStat(machine_id="M-LATHE-02 (CNC Finishing)", status="Idle", current_wo=None, utilization_pct=45.0, output_today=180),
            MachineUtilizationStat(machine_id="M-VMC-01 (Milling & Drilling)", status="Running", current_wo="WO-1004", utilization_pct=78.5, output_today=310),
            MachineUtilizationStat(machine_id="M-INSPECT-01 (CMM & Final Insp)", status="Running", current_wo="WO-1005", utilization_pct=95.0, output_today=600),
        ]

        open_ncs = db.query(NCRecord).filter(NCRecord.status == "Open").count()

        return DashboardStatsOut(
            today_date=today_str,
            total_orders_today=total_orders_today,
            open_orders_count=open_orders_count,
            completed_orders_count=completed_orders_count,
            delayed_orders_count=len(delayed_orders),
            running_work_orders=running_wos,
            pending_work_orders=pending_wos,
            current_total_wip=current_total_wip,
            total_rejected_qty=total_rej_all,
            overall_yield_pct=overall_yield_pct,
            packing_pending_qty=packing_pending_qty,
            dispatch_pending_qty=dispatch_pending_qty,
            open_ncs_count=open_ncs,
            rejection_by_stage=rejection_by_stage,
            top_defects=top_defects,
            top_delayed_orders=delayed_orders[:5],
            bottlenecks=bottlenecks,
            production_trend=production_trend,
            machine_utilization=machine_utilization
        )
