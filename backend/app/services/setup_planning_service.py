"""Setup planning: setups, the work orders mapped to them, heat numbers, and gate dates.

Design: docs/setup-planning-architecture.md. A setup is one production day with several work
orders, planned by PPC. Gate dates stay on wo_routes (planned_start / planned_end), which the
floor's work queue already reads. Everything here is planning information: it never reads or
writes quantities, WIP or MRB, and production entry / moves / dispatch never read it.
"""
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.departments import normalize_stage
from app.models.audit import AuditLog
from app.models.order import Order
from app.models.setup_planning import PlanningSetup, WOHeat
from app.models.user import User
from app.models.work_order import WORoute, WOStatus, WorkOrder
from app.services import plan_delay_service as delay
from app.services.stage_plan_service import order_due_date

CLOSED_STATUSES = (WOStatus.CLOSED, WOStatus.DISPATCHED)


def _bad(detail, code: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def require_enabled() -> None:
    if not settings.SETUP_PLANNING_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Setup planning is not enabled.")


def _audit(db: Session, user: Optional[User], action: str, entity_id: str, old: str = "", new: str = "", details: str = "") -> None:
    db.add(AuditLog(
        user_id=user.id if user else None,
        user_name=user.full_name if user else "PPC",
        action=action, entity="WorkOrder" if action.startswith("WO_") else "PlanningSetup",
        entity_id=entity_id, old_value=old or None, new_value=new or None, details=details or None,
    ))


def _is_active(wo: WorkOrder) -> bool:
    return wo.status not in CLOSED_STATUSES and wo.current_stage != "Completed"


def _released(wo: WorkOrder) -> bool:
    return wo.release_date is not None


def clean_setup_number(value: Optional[str]) -> str:
    v = " ".join((value or "").split())
    if not v:
        raise _bad("A setup number is required.")
    if len(v) > 60:
        raise _bad("The setup number is too long (60 characters at most).")
    return v


def clean_heats(values: Optional[Iterable[str]]) -> List[str]:
    """Heat numbers from a list or from text separated by commas, semicolons or new lines.
    Trimmed, de-duplicated ignoring case, first spelling kept."""
    out: List[str] = []
    seen = set()
    for raw in values or []:
        for part in str(raw or "").replace(";", ",").replace("\n", ",").split(","):
            h = part.strip()
            if not h:
                continue
            if len(h) > 100:
                raise _bad(f"Heat number '{h[:20]}...' is too long (100 characters at most).")
            if h.upper() not in seen:
                seen.add(h.upper())
                out.append(h)
    return out


def find_setup(db: Session, number: str, lock: bool = False) -> PlanningSetup:
    q = db.query(PlanningSetup).filter(func.upper(PlanningSetup.setup_number) == clean_setup_number(number).upper())
    if lock:
        q = q.with_for_update()
    s = q.first()
    if not s:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Setup '{number}' not found.")
    return s


def find_wo(db: Session, wo_number: str, lock: bool = False) -> WorkOrder:
    q = db.query(WorkOrder).filter(WorkOrder.wo_number == (wo_number or "").strip())
    if lock:
        q = q.with_for_update()
    wo = q.first()
    if not wo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work Order '{wo_number}' not found.")
    return wo


def _heats_of(db: Session, wo_ids: List) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    if not wo_ids:
        return out
    for h in db.query(WOHeat).filter(WOHeat.work_order_id.in_(wo_ids)).order_by(WOHeat.added_at, WOHeat.heat_number).all():
        out.setdefault(str(h.work_order_id), []).append(h.heat_number)
    return out


def _wo_row(wo: WorkOrder, ev: Dict, heats: List[str], setup_number: Optional[str]) -> Dict:
    order: Optional[Order] = wo.order
    return {
        "wo_number": wo.wo_number,
        "oar_number": order.oar_number if order else None,
        "customer_po": order.customer_po if order else None,
        "customer_name": order.customer.name if order and order.customer else None,
        "part_number": order.part.part_number if order and order.part else None,
        "part_name": order.part.description if order and order.part else None,
        "qty": wo.physical_wo_qty,
        "wo_status": getattr(wo.status, "value", wo.status),
        "current_stage": wo.current_stage,
        "setup_number": setup_number,
        "heat_numbers": heats,
        "plan_version": wo.plan_version or 0,
        "commitment_date": ev.get("commitment_date"),
        "days_to_commitment": ev.get("days_to_commitment"),
        "plan_status": ev["status"],
        "plan_text": ev["text"],
        "late_gate": ev.get("late_gate"),
        "late_days": ev.get("late_days", 0),
        "missing_dates": ev.get("missing_dates", []),
        "gates": ev["gates"],
    }


def _apply_splits(db: Session, setup: PlanningSetup, rows: List[Dict], primary_wos: List[WorkOrder]) -> List[Dict]:
    """Primary rows show only the quantity this setup keeps; shares planned here for a work order
    whose main setup is elsewhere are added as read-only rows (dates are the work order's own)."""
    from app.models.setup_planning import WOSetupSplit
    names = {str(x.id): x.setup_number for x in db.query(PlanningSetup).all()}
    prim_ids = [w.id for w in primary_wos]
    if prim_ids:
        cut: Dict[str, int] = {}
        for sp in db.query(WOSetupSplit).filter(WOSetupSplit.work_order_id.in_(prim_ids)).all():
            cut[str(sp.work_order_id)] = cut.get(str(sp.work_order_id), 0) + sp.qty
        by_no = {w.wo_number: w for w in primary_wos}
        for r in rows:
            c = cut.get(str(by_no[r["wo_number"]].id), 0)
            r["is_split"] = False
            r["total_qty"] = r["qty"]
            r["split_note"] = f"{r['qty'] - c} of {r['qty']} pcs here; {c} in other setups" if c else None
            r["qty"] = (r["qty"] or 0) - c
    mine = db.query(WOSetupSplit).filter(WOSetupSplit.setup_id == setup.id).all()
    if mine:
        wos = [w for w in db.query(WorkOrder).filter(WorkOrder.id.in_([m.work_order_id for m in mine])).all() if _is_active(w)]
        evs = delay.evaluate_work_orders(db, wos)
        heats = _heats_of(db, [w.id for w in wos])
        qty = {str(m.work_order_id): m.qty for m in mine}
        for w in wos:
            row = _wo_row(w, evs[str(w.id)], heats.get(str(w.id), []), setup.setup_number)
            row.update({"is_split": True, "total_qty": row["qty"], "qty": qty[str(w.id)],
                        "primary_setup": names.get(str(w.setup_id)) if w.setup_id else None,
                        "split_note": f"{qty[str(w.id)]} of {row['qty']} pcs here; dates are set in {names.get(str(w.setup_id)) or 'its main setup'}"})
            rows.append(row)
    return rows


def _rollup(rows: List[Dict]) -> Dict:
    counts = {delay.DELAYED: 0, delay.AT_RISK: 0, delay.NO_PLAN: 0, delay.ON_TRACK: 0, delay.COMPLETE: 0}
    gates_total = gates_dated = 0
    commits = []
    heats = set()
    for r in rows:
        counts[r["plan_status"]] = counts.get(r["plan_status"], 0) + 1
        for g in r["gates"]:
            gates_total += 1
            if g["planned_end"]:
                gates_dated += 1
        if r["commitment_date"]:
            commits.append(r["commitment_date"])
        heats.update(h.upper() for h in r["heat_numbers"])
    return {
        "wo_count": len(rows),
        "total_qty": sum(r["qty"] or 0 for r in rows),
        "heat_count": len(heats),
        "earliest_commitment": min(commits) if commits else None,
        "delayed": counts[delay.DELAYED],
        "at_risk": counts[delay.AT_RISK],
        "no_plan": counts[delay.NO_PLAN],
        "on_track": counts[delay.ON_TRACK],
        "complete": counts[delay.COMPLETE],
        "gates_total": gates_total,
        "gates_dated": gates_dated,
    }


def _setup_dict(s: PlanningSetup) -> Dict:
    return {
        "setup_number": s.setup_number,
        "setup_date": s.setup_date.isoformat() if s.setup_date else None,
        "status": s.status,
        "remarks": s.remarks,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


class SetupPlanningService:
    # ------------------------------------------------------------------ setups
    @staticmethod
    def create_setup(db: Session, setup_number: str, setup_date: Optional[date], remarks: Optional[str], user: Optional[User]) -> PlanningSetup:
        number = clean_setup_number(setup_number)
        if db.query(PlanningSetup).filter(func.upper(PlanningSetup.setup_number) == number.upper()).first():
            raise _bad(f"Setup '{number}' already exists.", status.HTTP_409_CONFLICT)
        s = PlanningSetup(setup_number=number, setup_date=setup_date, status="OPEN",
                          remarks=(remarks or "").strip() or None, created_by=user.full_name if user else None)
        db.add(s)
        db.flush()
        _audit(db, user, "SETUP_CREATED", number, "", f"Production day {setup_date or 'not set'}", (remarks or ""))
        return s

    @staticmethod
    def list_setups(db: Session, status_filter: Optional[str] = None) -> List[Dict]:
        q = db.query(PlanningSetup)
        if status_filter and status_filter.upper() in ("OPEN", "CLOSED"):
            q = q.filter(PlanningSetup.status == status_filter.upper())
        setups = q.all()
        if not setups:
            return []
        by_setup: Dict[str, List[WorkOrder]] = {}
        for wo in db.query(WorkOrder).filter(WorkOrder.setup_id.in_([s.id for s in setups])).all():
            if _is_active(wo):
                by_setup.setdefault(str(wo.setup_id), []).append(wo)
        all_wos = [w for ws in by_setup.values() for w in ws]
        evs = delay.evaluate_work_orders(db, all_wos)
        heats = _heats_of(db, [w.id for w in all_wos])
        out = []
        for s in setups:
            rows = [_wo_row(w, evs[str(w.id)], heats.get(str(w.id), []), s.setup_number) for w in by_setup.get(str(s.id), [])]
            rows = _apply_splits(db, s, rows, by_setup.get(str(s.id), []))
            out.append({**_setup_dict(s), **_rollup(rows)})
        out.sort(key=lambda r: (r["setup_date"] or "", r["setup_number"]), reverse=True)
        return out

    @staticmethod
    def setup_detail(db: Session, setup_number: str) -> Dict:
        s = find_setup(db, setup_number)
        wos = [w for w in db.query(WorkOrder).filter(WorkOrder.setup_id == s.id).order_by(WorkOrder.wo_number).all()]
        active = [w for w in wos if _is_active(w)]
        evs = delay.evaluate_work_orders(db, active)
        heats = _heats_of(db, [w.id for w in active])
        rows = [_wo_row(w, evs[str(w.id)], heats.get(str(w.id), []), s.setup_number) for w in active]
        rows = _apply_splits(db, s, rows, active)
        rows.sort(key=lambda r: (delay.STATUS_RANK[r["plan_status"]], r["commitment_date"] or "9999", r["wo_number"]))
        # gate columns: the union of every work order's route, in the plant's usual order
        order = ["F1", "F2", "F3", "SP", "FI", "PACKING", "BSR", "DISPATCH"]
        seen: Dict[str, str] = {}
        for r in rows:
            for g in r["gates"]:
                seen.setdefault(normalize_stage(g["stage"]), g["stage"])
        gate_cols = sorted(seen.values(), key=lambda x: (order.index(normalize_stage(x)) if normalize_stage(x) in order else 99, x))
        return {"setup": _setup_dict(s), "rollup": _rollup(rows), "gate_columns": gate_cols, "work_orders": rows,
                "finished_work_orders": len(wos) - len(active)}

    @staticmethod
    def update_setup(db: Session, setup_number: str, setup_date: Optional[date], remarks: Optional[str],
                     new_status: Optional[str], user: Optional[User], date_given: bool = False) -> PlanningSetup:
        s = find_setup(db, setup_number, lock=True)
        changes = []
        if date_given and setup_date != s.setup_date:
            changes.append(f"production day {s.setup_date} -> {setup_date}")
            s.setup_date = setup_date
        if remarks is not None and (remarks.strip() or None) != s.remarks:
            changes.append("remarks")
            s.remarks = remarks.strip() or None
        if new_status is not None:
            ns = new_status.strip().upper()
            if ns not in ("OPEN", "CLOSED"):
                raise _bad("Status must be OPEN or CLOSED.")
            if ns != s.status:
                changes.append(f"status {s.status} -> {ns}")
                s.status = ns
        if changes:
            _audit(db, user, "SETUP_UPDATED", s.setup_number, "", "; ".join(changes))
        return s

    # ---------------------------------------------------- mapping work orders
    @staticmethod
    def map_work_orders(db: Session, setup_number: str, wo_numbers: List[str], reason: str, user: Optional[User]) -> Dict:
        s = find_setup(db, setup_number, lock=True)
        if s.status == "CLOSED":
            raise _bad(f"Setup '{s.setup_number}' is closed. Reopen it to add work orders.", status.HTTP_409_CONFLICT)
        if len((reason or "").strip()) < 3:
            raise _bad("A reason is required.")
        mapped, errors = [], []
        for n in dict.fromkeys(x.strip() for x in wo_numbers if x and x.strip()):
            wo = db.query(WorkOrder).filter(WorkOrder.wo_number == n).with_for_update().first()
            if not wo:
                errors.append({"wo_number": n, "message": "Work order not found."})
            elif not _released(wo):
                errors.append({"wo_number": n, "message": "Not released yet. Set the setup number when releasing it."})
            elif not _is_active(wo):
                errors.append({"wo_number": n, "message": "Closed or dispatched."})
            elif wo.setup_id == s.id:
                errors.append({"wo_number": n, "message": "Already in this setup."})
            elif wo.setup_id is not None:
                other = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first()
                errors.append({"wo_number": n, "message": f"Already in setup {other.setup_number if other else '?'}. Use Move."})
            else:
                wo.setup_id = s.id
                for h in db.query(WOHeat).filter(WOHeat.work_order_id == wo.id).all():
                    h.setup_id = s.id
                _audit(db, user, "WO_SETUP_MAPPED", wo.wo_number, "no setup", s.setup_number, reason.strip())
                mapped.append(wo.wo_number)
        db.flush()
        return {"mapped": mapped, "errors": errors}

    @staticmethod
    def move_work_order(db: Session, wo_number: str, to_setup_number: str, reason: str, user: Optional[User]) -> Dict:
        wo = find_wo(db, wo_number, lock=True)
        target = find_setup(db, to_setup_number, lock=True)
        if len((reason or "").strip()) < 3:
            raise _bad("A reason is required.")
        if target.status == "CLOSED":
            raise _bad(f"Setup '{target.setup_number}' is closed.", status.HTTP_409_CONFLICT)
        if not _released(wo) or not _is_active(wo):
            raise _bad("Only released, open work orders can be moved.")
        if wo.setup_id == target.id:
            raise _bad("The work order is already in that setup.")
        from app.models.setup_planning import WOSetupSplit
        if db.query(WOSetupSplit).filter(WOSetupSplit.work_order_id == wo.id, WOSetupSplit.setup_id == target.id).first():
            raise _bad("A share of this work order is planned in that setup. Remove the split first.")
        old = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first() if wo.setup_id else None
        if old and old.status == "CLOSED":
            raise _bad(f"Setup '{old.setup_number}' is closed. Reopen it first.", status.HTTP_409_CONFLICT)
        wo.setup_id = target.id
        for h in db.query(WOHeat).filter(WOHeat.work_order_id == wo.id).all():
            h.setup_id = target.id
        _audit(db, user, "WO_SETUP_MOVED", wo.wo_number, old.setup_number if old else "no setup", target.setup_number, reason.strip())
        db.flush()
        return {"wo_number": wo.wo_number, "from": old.setup_number if old else None, "to": target.setup_number}

    @staticmethod
    def unassigned(db: Session) -> List[Dict]:
        wos = [w for w in db.query(WorkOrder).filter(WorkOrder.setup_id.is_(None), WorkOrder.release_date.isnot(None)).all() if _is_active(w)]
        evs = delay.evaluate_work_orders(db, wos)
        heats = _heats_of(db, [w.id for w in wos])
        rows = [_wo_row(w, evs[str(w.id)], heats.get(str(w.id), []), None) for w in wos]
        rows.sort(key=lambda r: (r["commitment_date"] or "9999", r["wo_number"]))
        return rows

    # ----------------------------------------------------------------- heats
    @staticmethod
    def set_heats(db: Session, wo: WorkOrder, heats: List[str], reason: str, user: Optional[User], audit: bool = True) -> List[str]:
        cleaned = clean_heats(heats)
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).all()
        if not cleaned and any(normalize_stage(r.stage) == "F1" for r in routes):
            raise _bad("At least one heat number is required when the route includes F1.")
        existing = db.query(WOHeat).filter(WOHeat.work_order_id == wo.id).all()
        old = [h.heat_number for h in existing]
        if {x.upper() for x in old} == {x.upper() for x in cleaned}:
            return old
        keep = {h.upper() for h in cleaned}
        for h in existing:
            if h.heat_number.upper() not in keep:
                db.delete(h)
        have = {h.heat_number.upper() for h in existing}
        for h in cleaned:
            if h.upper() not in have:
                db.add(WOHeat(work_order_id=wo.id, setup_id=wo.setup_id, heat_number=h, added_by=user.full_name if user else None))
        wo.heat_number = cleaned[0] if cleaned else None
        wo.plan_version = (wo.plan_version or 0) + 1
        if audit:
            _audit(db, user, "WO_HEATS_CHANGED", wo.wo_number, ", ".join(old), ", ".join(cleaned), reason)
        db.flush()
        return cleaned

    # ----------------------------------------------------------- gate dates
    @staticmethod
    def validate_gate_changes(
        routes: List[WORoute],
        ev: Dict,
        changes: Dict[str, Tuple[Optional[date], Optional[date]]],
        commitment: Optional[date],
        wo_number: str,
        clears: Optional[List[str]] = None,
        db: Optional[Session] = None,
        wo: Optional[WorkOrder] = None,
    ) -> List[Dict]:
        """Checks shared by the Excel import and the on-screen edit. `changes` maps a gate to the
        (start, end) PPC provided; None means "not provided" (an existing date is never cleared).
        Returns [{stage, level: ERROR|WARNING, message}]."""
        issues: List[Dict] = []
        by_key = {normalize_stage(r.stage): r for r in routes}
        states = {normalize_stage(g["stage"]): g["state"] for g in ev["gates"]}
        merged: Dict[str, Tuple[Optional[date], Optional[date]]] = {k: (r.planned_start, r.planned_end) for k, r in by_key.items()}
        changed_keys = set()
        for stage, (ns, ne) in changes.items():
            key = normalize_stage(stage)
            r = by_key.get(key)
            if r is None:
                issues.append({"stage": stage, "level": "ERROR", "message": f"{stage} is not a gate of {wo_number}."})
                continue
            old = (r.planned_start, r.planned_end)
            new = (ns if ns is not None else old[0], ne if ne is not None else old[1])
            if new == old:
                continue
            if states.get(key) == delay.DONE:
                issues.append({"stage": r.stage, "level": "ERROR", "message": f"{r.stage} is already finished; its dates cannot change."})
                continue
            if new[0] and new[1] and new[0] > new[1]:
                issues.append({"stage": r.stage, "level": "ERROR", "message": f"{r.stage}: the start date is after the end date."})
                continue
            merged[key] = new
            changed_keys.add(key)
        for stage in clears or []:
            key = normalize_stage(stage)
            r = by_key.get(key)
            if r is None:
                issues.append({"stage": stage, "level": "ERROR", "message": f"{stage} is not a gate of {wo_number}."})
            elif key in {normalize_stage(s) for s in changes}:
                issues.append({"stage": r.stage, "level": "ERROR", "message": f"{r.stage} cannot be both changed and cleared."})
            elif (r.planned_start or r.planned_end) and states.get(key) == delay.DONE:
                issues.append({"stage": r.stage, "level": "ERROR", "message": f"{r.stage} is already finished; its dates cannot change."})
            elif r.planned_start or r.planned_end:
                merged[key] = (None, None)
                changed_keys.add(key)
        if changed_keys and not any(i["level"] == "ERROR" for i in issues):
            ordered = sorted(routes, key=lambda r: r.sequence)
            for a, b in zip(ordered, ordered[1:]):
                ka, kb = normalize_stage(a.stage), normalize_stage(b.stage)
                if ka in changed_keys or kb in changed_keys:
                    ea, eb = merged[ka][1], merged[kb][1]
                    if ea and eb and eb < ea:
                        issues.append({"stage": b.stage, "level": "WARNING", "message": f"{b.stage} ends before {a.stage}."})
            dated = [r for r in ordered if merged[normalize_stage(r.stage)][1]]
            if dated and commitment:
                last = dated[-1]
                last_end = merged[normalize_stage(last.stage)][1]
                if last_end > commitment:
                    issues.append({"stage": last.stage, "level": "WARNING",
                                   "message": f"The last gate ({last.stage}) ends {last_end.strftime('%d %b')}, after the commitment date {commitment.strftime('%d %b')}."})
            # Holiday / capacity warnings were removed with the Calendar and Capacity screens: a gate date
            # is only checked against the commitment date.
        return issues

    @staticmethod
    def apply_gate_changes(db: Session, wo: WorkOrder, routes: List[WORoute],
                           changes: Dict[str, Tuple[Optional[date], Optional[date]]],
                           source: str, user: Optional[User], reason: str,
                           clears: Optional[List[str]] = None) -> List[Tuple]:
        by_key = {normalize_stage(r.stage): r for r in routes}
        done: List[Tuple] = []
        now = datetime.now()
        for stage, (ns, ne) in changes.items():
            r = by_key.get(normalize_stage(stage))
            if r is None:
                continue
            old = (r.planned_start, r.planned_end)
            new = (ns if ns is not None else old[0], ne if ne is not None else old[1])
            if new == old:
                continue
            r.planned_start, r.planned_end = new
            r.plan_source = source
            r.plan_updated_at = now
            done.append((r.stage, old[0], old[1], new[0], new[1]))
        for stage in clears or []:
            r = by_key.get(normalize_stage(stage))
            if r is None or (r.planned_start is None and r.planned_end is None):
                continue
            done.append((r.stage, r.planned_start, r.planned_end, None, None))
            r.planned_start = r.planned_end = None
            r.plan_source = source
            r.plan_updated_at = now
        if done:
            wo.plan_version = (wo.plan_version or 0) + 1
            fmt = lambda a, b: f"{a.strftime('%d %b') if a else '-'} to {b.strftime('%d %b') if b else '-'}"
            _audit(db, user, "WO_PLAN_CHANGED", wo.wo_number,
                   "; ".join(f"{s}: {fmt(a, b)}" for s, a, b, _, _ in done),
                   "; ".join(f"{s}: {fmt(c, d)}" for s, _, _, c, d in done), reason)
        return done

    @staticmethod
    def update_plan(db: Session, wo_number: str, gates: List[Dict], heat_numbers: Optional[List[str]],
                    reason: str, expected_plan_version: Optional[int], user: Optional[User]) -> Dict:
        wo = find_wo(db, wo_number, lock=True)
        if len((reason or "").strip()) < 3:
            raise _bad("A reason is required.")
        if not _released(wo) or not _is_active(wo):
            raise _bad("Only released, open work orders can be planned.")
        if wo.setup_id:
            s = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first()
            if s and s.status == "CLOSED":
                raise _bad(f"Setup '{s.setup_number}' is closed. Reopen it to change dates.", status.HTTP_409_CONFLICT)
        if expected_plan_version is not None and expected_plan_version != (wo.plan_version or 0):
            raise _bad("The plan was changed by someone else after you opened it. Reload and try again.", status.HTTP_409_CONFLICT)
        routes = db.query(WORoute).filter(WORoute.work_order_id == wo.id).order_by(WORoute.sequence).all()
        ev = delay.evaluate_work_orders(db, [wo])[str(wo.id)]
        changes = {g["stage"]: (g.get("planned_start"), g.get("planned_end")) for g in gates if not g.get("clear")}
        clears = [g["stage"] for g in gates if g.get("clear")]
        issues = SetupPlanningService.validate_gate_changes(routes, ev, changes, order_due_date(wo.order), wo.wo_number, clears, db, wo)
        errors = [i for i in issues if i["level"] == "ERROR"]
        if errors:
            raise _bad({"message": "The plan was not saved.", "issues": issues})
        done = SetupPlanningService.apply_gate_changes(db, wo, routes, changes, "MANUAL", user, reason.strip(), clears)
        heats = None
        if heat_numbers is not None:
            heats = SetupPlanningService.set_heats(db, wo, heat_numbers, reason.strip(), user)
        db.flush()
        return {"wo_number": wo.wo_number, "changed_gates": [d[0] for d in done], "heat_numbers": heats,
                "warnings": [i for i in issues if i["level"] == "WARNING"], "plan_version": wo.plan_version or 0}

    # ------------------------------------------------------------------ boards
    @staticmethod
    def delay_board(db: Session, setup_number: Optional[str] = None, statuses: Optional[List[str]] = None) -> Dict:
        wanted = [s.upper() for s in (statuses or [delay.DELAYED, delay.AT_RISK])]
        q = db.query(WorkOrder).filter(WorkOrder.release_date.isnot(None))
        setup_names: Dict[str, str] = {}
        if setup_number:
            s = find_setup(db, setup_number)
            q = q.filter(WorkOrder.setup_id == s.id)
        for s in db.query(PlanningSetup).all():
            setup_names[str(s.id)] = s.setup_number
        wos = [w for w in q.all() if _is_active(w)]
        evs = delay.evaluate_work_orders(db, wos)
        heats = _heats_of(db, [w.id for w in wos])
        rows = []
        for w in wos:
            ev = evs[str(w.id)]
            if ev["status"] in wanted:
                rows.append(_wo_row(w, ev, heats.get(str(w.id), []), setup_names.get(str(w.setup_id)) if w.setup_id else None))
        rows.sort(key=lambda r: (delay.STATUS_RANK[r["plan_status"]], -(r["late_days"] or 0), r["commitment_date"] or "9999", r["wo_number"]))
        return {"today": date.today().isoformat(), "count": len(rows), "work_orders": rows}

    @staticmethod
    def delay_digest(db: Session) -> Dict:
        """The list PPC wants every morning: work orders that are delayed or at risk, worst first.
        Same rules as the Delay Board; read-only."""
        board = SetupPlanningService.delay_board(db, None, [delay.DELAYED, delay.AT_RISK])
        rows = board["work_orders"]
        no_plan = SetupPlanningService.delay_board(db, None, [delay.NO_PLAN])["count"]
        return {
            "date": date.today().isoformat(),
            "counts": {"delayed": sum(1 for r in rows if r["plan_status"] == delay.DELAYED),
                       "at_risk": sum(1 for r in rows if r["plan_status"] == delay.AT_RISK),
                       "no_plan": no_plan},
            "delayed": [r for r in rows if r["plan_status"] == delay.DELAYED],
            "at_risk": [r for r in rows if r["plan_status"] == delay.AT_RISK],
        }

    @staticmethod
    def send_digest(db: Session, user: Optional[User]) -> Dict:
        """Build the digest and send it to the planners (email when the server has SMTP set up,
        otherwise it is only logged on the server). Records the send in the audit log."""
        from app.models.user import User as UserModel, UserRole
        from app.services.notification_service import NotificationService

        digest = SetupPlanningService.delay_digest(db)
        recipients = [u.email for u in db.query(UserModel).filter(UserModel.role == UserRole.PLANNER, UserModel.is_active.is_(True)).all() if u.email]
        result = NotificationService.send_plan_delay_digest(digest, recipients)
        _audit(db, user, "PLAN_DIGEST_SENT", "digest", "",
               f"{digest['counts']['delayed']} delayed, {digest['counts']['at_risk']} at risk",
               f"email sent: {result['email_sent']}; recipients: {', '.join(result['recipients']) or 'none'}")
        return {**digest, **result}

    @staticmethod
    def plan_info(db: Session, wo_number: str, stage: Optional[str] = None) -> Dict:
        """Read-only plan facts for the floor (queue banner, Production Entry, Move Parts, WO Tracking)."""
        if not settings.SETUP_PLANNING_ENABLED:
            return {"enabled": False}
        wo = find_wo(db, wo_number)
        ev = delay.evaluate_work_orders(db, [wo])[str(wo.id)]
        s = db.query(PlanningSetup).filter(PlanningSetup.id == wo.setup_id).first() if wo.setup_id else None
        heats = _heats_of(db, [wo.id]).get(str(wo.id), [])
        key = normalize_stage(stage) if stage else None
        gates = ev["gates"]
        this_gate = next((g for g in gates if key and normalize_stage(g["stage"]) == key), None)
        next_gate = None
        if this_gate:
            nxt = [g for g in gates if g["sequence"] > this_gate["sequence"]]
            next_gate = nxt[0] if nxt else None
        return {
            "enabled": True,
            "wo_number": wo.wo_number,
            "setup_number": s.setup_number if s else None,
            "heat_numbers": heats,
            "commitment_date": ev["commitment_date"],
            "days_to_commitment": ev["days_to_commitment"],
            "plan_status": ev["status"],
            "plan_text": ev["text"],
            "this_gate": this_gate,
            "next_gate": next_gate,
            "gates": gates,
        }

    # ------------------------------------------------------------- release
    @staticmethod
    def bind_release(db: Session, wo: WorkOrder, setup_number: Optional[str], new_setup_date: Optional[date],
                     heat_numbers: Optional[List[str]], legacy_heat: Optional[str], stages: List[str],
                     user: Optional[User]) -> Optional[PlanningSetup]:
        """Called by WO release when setup planning is switched on: the setup number is mandatory,
        and heat numbers are mandatory when the route includes F1. Creating a new setup on the
        spot is a PPC action (planner / admin)."""
        from app.core.roles import PPC_PLANNING_ROLES

        if not settings.SETUP_PLANNING_ENABLED:
            return None
        if not (setup_number or "").strip():
            raise _bad("A setup number is required to release a work order. Pick an open setup or create one.")
        heats = clean_heats(list(heat_numbers or []) + ([legacy_heat] if legacy_heat else []))
        if "F1" in [normalize_stage(s) for s in stages] and not heats:
            raise _bad("At least one heat number is required when the route includes F1.")
        number = clean_setup_number(setup_number)
        s = db.query(PlanningSetup).filter(func.upper(PlanningSetup.setup_number) == number.upper()).with_for_update().first()
        if s is None:
            if new_setup_date is None:
                raise _bad(f"Setup '{number}' does not exist. Give its production day to create it, or pick an existing setup.")
            if user is None or not user.has_any_role(*PPC_PLANNING_ROLES):
                raise _bad(f"Setup '{number}' does not exist, and only PPC can create a setup. Pick an existing one.", status.HTTP_403_FORBIDDEN)
            s = SetupPlanningService.create_setup(db, number, new_setup_date, None, user)
        elif s.status == "CLOSED":
            raise _bad(f"Setup '{s.setup_number}' is closed.", status.HTTP_409_CONFLICT)
        old_setup = wo.setup_id
        wo.setup_id = s.id
        # Release rebuilds the work order, so its heat list is replaced by the one given now.
        for h in db.query(WOHeat).filter(WOHeat.work_order_id == wo.id).all():
            db.delete(h)
        db.flush()
        for h in heats:
            db.add(WOHeat(work_order_id=wo.id, setup_id=s.id, heat_number=h, added_by=user.full_name if user else None))
        if heats:
            wo.heat_number = heats[0]
        wo.plan_version = (wo.plan_version or 0) + 1
        _audit(db, user, "WO_SETUP_MAPPED", wo.wo_number, "no setup" if not old_setup else "re-released", s.setup_number,
               "Released into the setup" + (f" with heats {', '.join(heats)}" if heats else ""))
        return s
