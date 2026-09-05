"""
VSPL SMES + OMS - Mathematical KPI Engine
Pure, deterministic, reproducible mathematical functions for manufacturing intelligence.

CRITICAL PRINCIPLE:
- Deterministic and pure (no side effects).
- Zero-safe division handling.
- Reusable across backend services, analytics, and reporting.
- Does NOT invent manufacturing quantities (actual quantities come from OMS Engine).
"""

from typing import Dict, Any, Optional, Union
from datetime import datetime


def safe_div(numerator: Union[int, float], denominator: Union[int, float], default: float = 0.0) -> float:
    """Safely divide two numbers, returning `default` if denominator is 0 or invalid."""
    try:
        num = float(numerator)
        denom = float(denominator)
        if denom == 0.0:
            return float(default)
        return num / denom
    except (ValueError, TypeError, ZeroDivisionError):
        return float(default)


def production_achievement(ok_qty: Union[int, float], target_qty: Union[int, float]) -> float:
    """
    Calculate Production Achievement Percentage.
    Formula: (OK Completed Qty / Target Qty) * 100
    """
    if target_qty <= 0:
        return 0.0
    return round(safe_div(ok_qty, target_qty) * 100.0, 2)


def rejection_rate(rej_qty: Union[int, float], processed_qty: Union[int, float]) -> float:
    """
    Calculate Rejection Rate Percentage.
    Formula: (Rejection Qty / Processed Qty) * 100
    where Processed Qty = OK Qty + Rejection Qty (or total pieces processed through the stage).
    """
    if processed_qty <= 0:
        return 0.0
    return round(safe_div(rej_qty, processed_qty) * 100.0, 2)


def stage_completion_pct(stage_ok_qty: Union[int, float], stage_target_qty: Union[int, float]) -> float:
    """
    Calculate Stage Completion Percentage against OMS stage target.
    Formula: (Stage OK Qty / Stage Target Qty) * 100 (capped at 100.0 for pipeline progress)
    """
    if stage_target_qty <= 0:
        return 0.0
    ratio = safe_div(stage_ok_qty, stage_target_qty) * 100.0
    return round(min(ratio, 100.0), 2)


def yield_pct(good_qty: Union[int, float], input_qty: Union[int, float]) -> float:
    """
    Calculate First-Pass Yield Percentage.
    Formula: (Good Qty / Input Qty) * 100
    """
    if input_qty <= 0:
        return 100.0
    return round(safe_div(good_qty, input_qty) * 100.0, 2)


def wip_trend(current_wip: Union[int, float], previous_wip: Union[int, float]) -> float:
    """
    Calculate WIP Delta / Trend.
    Formula: Current WIP - Previous WIP
    Positive value indicates WIP accumulation; Negative indicates buffer clearance.
    """
    return round(float(current_wip) - float(previous_wip), 2)


def production_velocity(completed_qty: Union[int, float], elapsed_hours: Union[int, float]) -> float:
    """
    Calculate Production Velocity in units per hour.
    Formula: Completed Qty / Elapsed Hours
    """
    if elapsed_hours <= 0:
        return 0.0
    return round(safe_div(completed_qty, elapsed_hours), 2)


def cycle_time_hours(entry_time: Optional[datetime], exit_time: Optional[datetime]) -> float:
    """
    Calculate Stage Cycle Time in Decimal Hours.
    Formula: (Exit Time - Entry Time) in seconds / 3600
    """
    if not entry_time or not exit_time:
        return 0.0
    if exit_time < entry_time:
        return 0.0
    delta = exit_time - entry_time
    return round(delta.total_seconds() / 3600.0, 3)


def takt_time(available_production_time_sec: Union[int, float], required_units: Union[int, float]) -> float:
    """
    Calculate Takt Time in seconds per unit.
    Formula: Available Production Time (sec) / Customer Demand (Units)
    """
    if required_units <= 0:
        return 0.0
    return round(safe_div(available_production_time_sec, required_units), 2)


def oee_proxy(availability_pct: float, performance_pct: float, quality_pct: float) -> float:
    """
    Calculate Overall Equipment Effectiveness (OEE) Proxy Percentage.
    Formula: (Availability / 100) * (Performance / 100) * (Quality / 100) * 100
    """
    a = max(0.0, min(100.0, availability_pct)) / 100.0
    p = max(0.0, min(100.0, performance_pct)) / 100.0
    q = max(0.0, min(100.0, quality_pct)) / 100.0
    return round(a * p * q * 100.0, 2)


def stage_result_balance(ent_qty: int, ok_qty: int, rej_qty: int) -> Dict[str, int]:
    """
    Calculate deterministic stage result balance according to authoritative OMS logic.
    - in_process = max(ent_qty - ok_qty - rej_qty, 0)
    - total_processed = ok_qty + rej_qty
    - is_balanced = (ok_qty + rej_qty + in_process == ent_qty)
    """
    ent = max(0, int(ent_qty))
    ok = max(0, int(ok_qty))
    rej = max(0, int(rej_qty))
    inproc = max(ent - ok - rej, 0)
    total_proc = ok + rej
    is_balanced = (ok + rej + inproc == ent)
    
    return {
        "ent_qty": ent,
        "ok_qty": ok,
        "rej_qty": rej,
        "in_process_qty": inproc,
        "total_processed": total_proc,
        "is_balanced": is_balanced
    }


def reconciliation_variance(released_qty: int, total_wip: int, dispatched_qty: int, total_scrap: int) -> int:
    """
    Calculate Plant Conservation of Mass Variance.
    Formula: Released Qty - (Total WIP + Dispatched Qty + Total Scrap)
    Zero indicates perfect balance across factory floor.
    """
    return int(released_qty) - (int(total_wip) + int(dispatched_qty) + int(total_scrap))
