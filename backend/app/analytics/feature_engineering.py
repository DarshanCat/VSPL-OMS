"""
VSPL SMES + OMS - Feature Engineering & Validation Pipeline
Extracts clean, validated feature vectors from raw factory transaction data.

CRITICAL PRINCIPLES:
- Validates data completeness and integrity before feature extraction.
- Rejects dirty, incomplete, or corrupted records.
- Extracts standardized numerical and categorical features for ML models.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.order import Order, Part, Customer
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.nc import NCRecord
from app.analytics.math_engine import cycle_time_hours, rejection_rate, yield_pct, safe_div

STANDARD_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]

# Alloy machinability & casting complexity index (1.0 = baseline PB2, higher = more complex)
ALLOY_COMPLEXITY_INDEX: Dict[str, float] = {
    "PB2 / CuSn11P": 1.0,
    "SAE 660 / RG7": 1.1,
    "AB2 / CuAl10Fe5Ni5": 1.45,  # High-strength Aluminium Bronze
    "CuSn12": 1.15,
    "LG2 / Gunmetal": 1.05,
    "DEFAULT": 1.0
}

# Historical baseline cycle times per stage (hours per standard batch of 100 pcs)
BASELINE_STAGE_CYCLE_HOURS: Dict[str, float] = {
    "F1": 3.5,    # Centrifugal Casting & Knockout
    "F2": 2.5,    # Rough CNC Machining & Turning
    "F3": 4.0,    # Precision CNC Boring / Grooving
    "SP": 24.0,   # Subcontract Heat Treatment / NDT (includes external transit)
    "FI": 2.0,    # CMM & Visual Final Inspection
    "PACKING": 1.5, # Preservation, Box Packing & Banding
    "BSR": 1.0,   # Bond Store Readiness Verification
    "DISPATCH": 1.0 # Loading & Gatepass
}

# Historical benchmark rejection rates per stage
BASELINE_STAGE_SCRAP_RATES: Dict[str, float] = {
    "F1": 3.5,  # Gas porosity / shrinkage
    "F2": 2.0,  # Inclusion / blowhole reveal on skin cut
    "F3": 1.5,  # Dimensional tolerance / taper
    "SP": 0.5,  # Distortion post-heat-treatment
    "FI": 1.0,  # Surface roughness / visual defects
    "PACKING": 0.0,
    "DISPATCH": 0.0
}


def validate_movement_record(movement: ProductionMovement) -> Tuple[bool, str]:
    """
    Validate a single production movement record for data pipeline ingestion.
    Returns (is_valid, validation_message).
    """
    if not movement:
        return False, "Null movement record"
    if movement.quantity_moved < 0:
        return False, f"Negative quantity moved: {movement.quantity_moved}"
    if movement.rejected_quantity < 0:
        return False, f"Negative rejected quantity: {movement.rejected_quantity}"
    if movement.quantity_moved == 0 and movement.rejected_quantity == 0:
        return False, "Zero quantity movement with zero rejection"
    if not movement.from_stage or not movement.to_stage:
        return False, "Missing from_stage or to_stage"
    return True, "Valid"


def extract_wo_features(wo: WorkOrder, db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Extract structured Work Order features.
    """
    order = wo.order
    part = order.part if order else None
    grade = part.grade if part else "DEFAULT"
    complexity = ALLOY_COMPLEXITY_INDEX.get(grade, 1.0)
    
    routes = wo.routes if hasattr(wo, "routes") and wo.routes else []
    route_stages = [r.stage for r in sorted(routes, key=lambda x: x.sequence)] if routes else STANDARD_STAGES
    
    cur_stage = wo.current_stage or (route_stages[0] if route_stages else "F1")
    cur_idx = route_stages.index(cur_stage) if cur_stage in route_stages else 0
    remaining_stages = len(route_stages) - 1 - cur_idx

    # Delivery deadline calculation
    today = date.today()
    delivery_date = order.delivery_date if order else None
    days_to_deadline = (delivery_date - today).days if delivery_date else 15
    is_overdue = days_to_deadline < 0

    # Total rejected so far across stages
    total_rej = 0
    if db:
        rej_sum = db.query(func.sum(StageWIP.rejected_qty)).filter(StageWIP.work_order_id == wo.id).scalar()
        total_rej = rej_sum or 0

    return {
        "wo_id": str(wo.id),
        "wo_number": wo.wo_number,
        "physical_wo_qty": int(wo.physical_wo_qty or 0),
        "part_number": part.part_number if part else "N/A",
        "part_grade": grade,
        "alloy_complexity": complexity,
        "route_length": len(route_stages),
        "current_stage": cur_stage,
        "current_stage_idx": cur_idx,
        "remaining_stages_count": max(remaining_stages, 0),
        "days_to_deadline": days_to_deadline,
        "is_overdue": is_overdue,
        "total_rejected_so_far": total_rej,
        "yield_so_far": yield_pct(max(wo.physical_wo_qty - total_rej, 0), wo.physical_wo_qty)
    }


def extract_stage_features(wo: WorkOrder, stage: str, db: Session) -> Dict[str, Any]:
    """
    Extract stage-specific execution and buffer features.
    """
    wip_rec = db.query(StageWIP).filter(
        StageWIP.work_order_id == wo.id,
        StageWIP.stage == stage
    ).first()

    ent_qty = wip_rec.ent_qty if wip_rec else 0
    ok_qty = wip_rec.ok_qty if wip_rec else 0
    rej_qty = wip_rec.rejected_qty if wip_rec else 0
    avail_wip = wip_rec.available_wip if wip_rec else (wo.physical_wo_qty if stage in ("F1", "F01") else 0)
    inproc_qty = wip_rec.inproc_qty if wip_rec else 0

    # Recent movements at this stage
    last_mov = db.query(ProductionMovement).filter(
        ProductionMovement.work_order_id == wo.id,
        ProductionMovement.from_stage == stage
    ).order_by(ProductionMovement.created_at.desc()).first()

    # Open NC count for this WO & stage
    nc_count = db.query(NCRecord).filter(
        NCRecord.work_order_id == wo.id,
        NCRecord.stage == stage,
        NCRecord.status == "Open"
    ).count()

    base_cycle = BASELINE_STAGE_CYCLE_HOURS.get(stage, 3.0)
    base_scrap = BASELINE_STAGE_SCRAP_RATES.get(stage, 2.0)

    return {
        "stage": stage,
        "ent_qty": ent_qty,
        "ok_qty": ok_qty,
        "rej_qty": rej_qty,
        "available_wip": avail_wip,
        "in_process_qty": inproc_qty,
        "stage_rejection_rate": rejection_rate(rej_qty, ok_qty + rej_qty),
        "baseline_cycle_hours": base_cycle,
        "baseline_scrap_rate": base_scrap,
        "open_nc_count": nc_count,
        "last_machine_id": last_mov.machine_id if last_mov else None,
        "last_operator": last_mov.operator_name if last_mov else None,
        "last_shift": last_mov.shift if last_mov else None
    }


def extract_time_features(dt: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Extract calendar and operational shift time features.
    """
    now = dt or datetime.now()
    hour = now.hour
    
    if 6 <= hour < 14:
        shift = "Shift A (Morning)"
    elif 14 <= hour < 22:
        shift = "Shift B (Evening)"
    else:
        shift = "Shift C (Night)"

    return {
        "timestamp": now.isoformat(),
        "hour_of_day": hour,
        "day_of_week": now.weekday(),
        "day_name": now.strftime("%A"),
        "is_weekend": now.weekday() >= 5,
        "shift_name": shift,
        "month": now.month
    }


def build_historical_movement_dataset(db: Session, min_samples: int = 5) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Extract a clean tabular dataset from production movements for ML training / evaluation.
    Filters out invalid records.
    """
    movements = db.query(ProductionMovement).order_by(ProductionMovement.created_at.asc()).all()
    valid_samples = []
    rejected_count = 0

    for m in movements:
        is_val, msg = validate_movement_record(m)
        if not is_val:
            rejected_count += 1
            continue

        wo = db.query(WorkOrder).filter(WorkOrder.id == m.work_order_id).first()
        if not wo:
            rejected_count += 1
            continue

        wo_feats = extract_wo_features(wo, db=db)
        time_feats = extract_time_features(m.created_at)
        
        sample = {
            "movement_id": m.movement_id,
            "wo_number": wo.wo_number,
            "part_grade": wo_feats["part_grade"],
            "alloy_complexity": wo_feats["alloy_complexity"],
            "physical_wo_qty": wo_feats["physical_wo_qty"],
            "from_stage": m.from_stage,
            "to_stage": m.to_stage,
            "quantity_moved": m.quantity_moved,
            "rejected_quantity": m.rejected_quantity,
            "machine_id": m.machine_id or "M-GENERIC",
            "operator_name": m.operator_name or "Operator",
            "shift": m.shift or time_feats["shift_name"],
            "hour_of_day": time_feats["hour_of_day"],
            "day_of_week": time_feats["day_of_week"],
            "is_weekend": time_feats["is_weekend"],
            "source_type": m.source_type or "SMES_UI",
            "created_at": m.created_at
        }
        valid_samples.append(sample)

    metadata = {
        "total_records_scanned": len(movements),
        "valid_samples_count": len(valid_samples),
        "invalid_records_dropped": rejected_count,
        "has_sufficient_data": len(valid_samples) >= min_samples
    }

    return valid_samples, metadata
