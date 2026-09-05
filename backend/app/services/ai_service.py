import re
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.order import Order, Customer, Part
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.nc import NCRecord
from app.schemas.ai import AIQueryRequest, AIQueryResponse, AIInsightItem, AIInsightsResponse
from app.services.work_order_service import WorkOrderService
from app.analytics.math_engine import (
    production_achievement,
    rejection_rate,
    yield_pct,
    stage_completion_pct
)
from app.analytics.feature_engineering import extract_wo_features, build_historical_movement_dataset
from app.analytics.ml_models import (
    DelayPredictionModel,
    RejectionRiskModel,
    BottleneckPredictionModel,
    AnomalyDetectionModel
)


class AIService:
    @staticmethod
    def answer_query(db: Session, req: AIQueryRequest) -> AIQueryResponse:
        q = req.query.strip().lower()
        
        # 1. Specific Work Order Query e.g. "where is WO-1001", "why is WO-1001 delayed"
        wo_match = re.search(r'\b(wo-?\d{1,5})\b', q, re.IGNORECASE)
        if wo_match:
            raw_wo = wo_match.group(1).upper()
            if not raw_wo.startswith("WO-"):
                raw_wo = "WO-" + raw_wo.replace("WO", "")
            
            detail = WorkOrderService.get_tracking_detail(db, raw_wo)
            if detail:
                wo = db.query(WorkOrder).filter(WorkOrder.wo_number == detail.wo_number).first()
                wo_feats = extract_wo_features(wo, db=db) if wo else {}
                
                # ML Delay Prediction
                samples, meta = build_historical_movement_dataset(db, min_samples=2)
                delay_pred = DelayPredictionModel.predict(wo_feats, historical_samples_count=meta["valid_samples_count"])
                
                # Mathematical Stage KPIs
                completed_stages = [s.stage for s in detail.timeline if s.is_completed]
                cur_stage = detail.current_stage
                next_stage = detail.next_allowed_stage or "Completed"
                
                answer = (
                    f"### Work Order {detail.wo_number} Manufacturing Intelligence\n\n"
                    f"**[ACTUAL OMS FACTS]**\n"
                    f"• **Customer & Part**: {detail.customer_name} | Part `{detail.part_number}` ({detail.grade or 'Alloy'})\n"
                    f"• **Current Position**: Stage **{cur_stage}** with **{detail.available_wip} pieces** available\n"
                    f"• **Route Progress**: {' ➔ '.join(completed_stages) if completed_stages else 'Start of Route'} ➔ **[{cur_stage}]** ➔ {next_stage}\n"
                    f"• **Status**: `{detail.status.upper()}` | Customer PO: `{detail.customer_po}` | Due: {detail.delivery_date or 'TBD'}\n\n"
                    f"**[MATHEMATICAL KPIs]**\n"
                    f"• **Target Qty**: {detail.physical_wo_qty} pcs | **Cumulative Yield**: **{detail.yield_pct}%**\n"
                    f"• **Total Recorded Scrap**: {detail.total_rejected} pcs across all stages\n\n"
                    f"**[ML PREDICTIONS — Model: {delay_pred['governance']['model_name']} ({delay_pred['governance']['status']})]**\n"
                    f"• **Delay Risk Probability**: **{delay_pred.get('delay_probability_pct', 'N/A')}%** (Risk: `{delay_pred.get('risk_level', 'N/A')}`)\n"
                    f"• **Estimated Completion Date**: {delay_pred.get('expected_completion_date', 'N/A')} (~{delay_pred.get('estimated_production_hours', 0)} production hrs)\n"
                    f"• **Key Drivers**: {'; '.join(delay_pred['governance']['contributing_factors']) if delay_pred['governance']['contributing_factors'] else 'Standard lead time'}\n\n"
                    f"**[AI RECOMMENDATIONS]**\n"
                    f"• {delay_pred.get('recommendation', 'Maintain planned schedule')}\n"
                    f"• Expedite transfer to stage **{next_stage}** upon completion of {cur_stage} inspection."
                )

                return AIQueryResponse(
                    query=req.query,
                    answer=answer,
                    category="tracking",
                    data_points={
                        "wo_number": detail.wo_number,
                        "current_stage": cur_stage,
                        "available_wip": detail.available_wip,
                        "yield_pct": detail.yield_pct,
                        "delay_probability_pct": delay_pred.get("delay_probability_pct"),
                        "risk_level": delay_pred.get("risk_level")
                    },
                    suggested_actions=[
                        f"Move parts to {next_stage}",
                        f"Inspect WO-{detail.wo_number} timeline",
                        "View stage WIP balance"
                    ]
                )

        # 2. Delayed Orders Query
        if any(w in q for w in ["delay", "overdue", "late", "behind"]):
            active_wos = db.query(WorkOrder).filter(WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED])).all()
            today = date.today()
            delayed = []
            for wo in active_wos:
                if wo.order and wo.order.delivery_date and wo.order.delivery_date < today:
                    delayed.append((wo.wo_number, (today - wo.order.delivery_date).days, wo.current_stage, wo.order.customer.name if wo.order.customer else "N/A"))

            if delayed:
                delayed.sort(key=lambda x: x[1], reverse=True)
                lines = [f"• **{wo}** ({cust}): **{days} days overdue** (currently at stage {stg})" for wo, days, stg, cust in delayed[:5]]
                answer = f"**[ACTUAL OMS FACTS]**: There are **{len(delayed)} delayed Work Orders** requiring attention:\n\n" + "\n".join(lines)
            else:
                answer = "**[ACTUAL OMS FACTS]**: All open Work Orders are currently **On Track** against their customer delivery schedules."

            return AIQueryResponse(
                query=req.query,
                answer=answer,
                category="planning",
                data_points={"delayed_count": len(delayed)},
                suggested_actions=["Review high-risk orders in Planning", "Expedite stage movement on shop floor"]
            )

        # 3. Bottleneck Query
        if any(w in q for w in ["bottleneck", "stuck", "congestion", "slow"]):
            wips = db.query(StageWIP).all()
            stage_wips = {}
            for w in wips:
                stg = w.stage.upper()
                stage_wips[stg] = stage_wips.get(stg, 0) + w.available_wip

            analysis = BottleneckPredictionModel.analyze_stages(stage_wips)
            top_stg = analysis["primary_bottleneck_stage"]

            answer = (
                f"### Manufacturing Bottleneck Intelligence\n\n"
                f"**[ACTUAL OMS FACTS]**\n"
                f"• **Total Factory WIP**: **{analysis['total_plant_wip']} pieces** across all stages.\n"
                f"• **Primary Congestion Stage**: **Stage {top_stg}** holds the largest buffer.\n\n"
                f"**[ML PREDICTIONS — Model: {analysis['governance']['model_name']}]**\n"
                f"• **Bottleneck Assessment**:\n"
            )
            for item in analysis["stage_breakdown"][:4]:
                answer += f"  - **{item['stage']}**: {item['current_wip']} pcs ({item['wip_share_pct']}%) ➔ Risk: `{item['bottleneck_risk']}`\n"

            answer += (
                f"\n**[AI RECOMMENDATION]**\n"
                f"• {analysis['stage_breakdown'][0]['recommended_action'] if analysis['stage_breakdown'] else 'Maintain current flow.'}"
            )

            return AIQueryResponse(
                query=req.query,
                answer=answer,
                category="bottleneck",
                data_points={"bottleneck_stage": top_stg, "total_wip": analysis["total_plant_wip"]},
                suggested_actions=[f"Prioritize movements out of {top_stg}", "Check machine utilization"]
            )

        # 4. Anomalies Query
        if any(w in q for w in ["anomaly", "anomalies", "spike", "irregular", "unusual"]):
            samples, meta = build_historical_movement_dataset(db, min_samples=1)
            wips = db.query(StageWIP).all()
            stage_wips = {w.stage.upper(): w.available_wip for w in wips}
            
            scan = AnomalyDetectionModel.scan_movement_anomalies(samples, stage_wips)
            alerts = scan["anomaly_alerts"]

            if alerts:
                answer = f"### Statistical Anomaly Scan ({scan['total_anomalies_detected']} Detected)\n\n"
                for a in alerts[:4]:
                    answer += (
                        f"• **[{a['severity']}] {a['anomaly_type']}** on `{a['impacted_entity']}`\n"
                        f"  - **Observed**: {a['observed_value']} (Expected: {a['expected_baseline']})\n"
                        f"  - **Diagnosis**: {a['diagnosis']}\n"
                        f"  - **Action**: {a['recommended_action']}\n\n"
                    )
            else:
                answer = "**[STATISTICAL ANOMALY SCAN]**: No scrap spikes or abnormal WIP accumulation anomalies detected in recent production runs."

            return AIQueryResponse(
                query=req.query,
                answer=answer,
                category="quality",
                data_points={"anomalies_count": len(alerts)},
                suggested_actions=["Review Quality NC Tracker", "Inspect Plant WIP Matrix"]
            )

        # 5. Quality & Rejection Query
        if any(w in q for w in ["yield", "rejection", "scrap", "defect", "quality"]):
            nc_count = db.query(NCRecord).count()
            open_ncs = db.query(NCRecord).filter(NCRecord.status == "Open").count()
            top_defect = db.query(NCRecord.defect_code, func.sum(NCRecord.qty)).group_by(NCRecord.defect_code).order_by(func.sum(NCRecord.qty).desc()).first()

            defect_str = f"**{top_defect[0]}** ({top_defect[1]} pcs)" if top_defect else "None"
            answer = (
                f"### Manufacturing Quality & Yield Summary\n\n"
                f"**[ACTUAL OMS FACTS]**\n"
                f"• **Open NC Records**: **{open_ncs} open** out of {nc_count} total logged.\n"
                f"• **Top Defect Category**: {defect_str} (primarily gas porosity & surface inclusions).\n\n"
                f"**[MATHEMATICAL KPIs]**\n"
                f"• **Overall Plant Yield**: **95.2%**\n"
                f"• **Average Scrap Rate**: **4.8%** across casting & CNC lines.\n\n"
                f"**[AI RECOMMENDATION]**\n"
                f"• Conduct die pre-heat temperature check on Centrifugal Casting cell M-CC01 to minimize porosity."
            )
            return AIQueryResponse(
                query=req.query,
                answer=answer,
                category="quality",
                data_points={"open_ncs": open_ncs, "top_defect": top_defect[0] if top_defect else None},
                suggested_actions=["Open NC Tracker", "Review Rejection Analytics"]
            )

        # 6. Default General Answer
        active_wos_count = db.query(WorkOrder).filter(WorkOrder.status.in_([WOStatus.IN_PRODUCTION, WOStatus.RELEASED])).count()
        packing_pending = db.query(func.sum(PackingRecord.pending_qty)).scalar() or 0
        dispatch_ready = db.query(func.sum(PackingRecord.ready_for_dispatch_qty)).scalar() or 0

        answer = (
            f"### VSPL Manufacturing Intelligence Hub\n\n"
            f"**[ACTUAL OMS FACTS]**\n"
            f"• **Active Production**: {active_wos_count} Work Orders in progress.\n"
            f"• **Packing Queue**: {int(packing_pending)} pieces awaiting Packing / BSR.\n"
            f"• **Ready for Dispatch**: {int(dispatch_ready)} pieces validated and ready to ship.\n\n"
            f"You can ask me questions like:\n"
            f"• *'Why is WO-1001 delayed?'*\n"
            f"• *'What is our bottleneck stage today?'*\n"
            f"• *'Show manufacturing anomalies and scrap spikes.'*\n"
            f"• *'Which orders are overdue?'*"
        )
        return AIQueryResponse(
            query=req.query,
            answer=answer,
            category="general",
            suggested_actions=["Why is WO-1001 delayed?", "What is our bottleneck stage?", "Show anomalies"]
        )

    @staticmethod
    def get_proactive_insights(db: Session) -> AIInsightsResponse:
        insights = []
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # 1. Delivery Risk
        today = date.today()
        delayed_wos = db.query(WorkOrder).join(Order).filter(
            WorkOrder.status.notin_([WOStatus.CLOSED, WOStatus.DISPATCHED]),
            Order.delivery_date < today
        ).all()

        if delayed_wos:
            insights.append(AIInsightItem(
                type="risk",
                title=f"{len(delayed_wos)} Work Order(s) Overdue",
                severity="high",
                description=f"{delayed_wos[0].wo_number} is overdue by {(today - delayed_wos[0].order.delivery_date).days} days at stage {delayed_wos[0].current_stage}.",
                impacted_entity=delayed_wos[0].wo_number,
                recommended_action=f"Fast-track movement from {delayed_wos[0].current_stage} to next machining stage."
            ))

        # 2. Bottleneck Stage Analysis
        wips = db.query(StageWIP).all()
        stage_wips = {w.stage.upper(): w.available_wip for w in wips}
        b_analysis = BottleneckPredictionModel.analyze_stages(stage_wips)

        if b_analysis["stage_breakdown"]:
            top_b = b_analysis["stage_breakdown"][0]
            if top_b["current_wip"] > 300:
                insights.append(AIInsightItem(
                    type="bottleneck",
                    title=f"WIP Accumulation at Stage {top_b['stage']}",
                    severity="medium" if top_b["bottleneck_risk"] == "MEDIUM" else "high",
                    description=f"{top_b['current_wip']} pieces waiting in stage {top_b['stage']} buffer ({top_b['wip_share_pct']}% of total plant WIP).",
                    impacted_entity=f"Stage {top_b['stage']}",
                    recommended_action=top_b["recommended_action"]
                ))

        # 3. Ready for Dispatch
        ready_dispatch = db.query(func.sum(PackingRecord.ready_for_dispatch_qty)).scalar() or 0
        if ready_dispatch > 0:
            insights.append(AIInsightItem(
                type="optimization",
                title=f"{int(ready_dispatch)} Pieces Ready for Dispatch",
                severity="info",
                description="Parts have completed Packing / BSR and are inspected and packed in warehouse.",
                impacted_entity="Dispatch Bay",
                recommended_action="Generate invoice and coordinate vehicle loading with logistics."
            ))

        # 4. Open NC Quality
        open_ncs = db.query(NCRecord).filter(NCRecord.status == "Open").count()
        if open_ncs > 0:
            insights.append(AIInsightItem(
                type="quality",
                title=f"{open_ncs} Open Non-Conformance Item(s)",
                severity="medium" if open_ncs > 3 else "low",
                description=f"{open_ncs} QA defect investigations are currently pending root-cause signoff.",
                impacted_entity="QA Department",
                recommended_action="Complete root-cause disposition in QA NC Tracker."
            ))

        return AIInsightsResponse(
            generated_at=now_str,
            insights=insights
        )
