"""Sales order status report: what is still to be delivered, by delivery month, with value.

Read-only. Three sources, never counted twice:
  OAR       accepted orders (OARs) with pieces still to dispatch
  PO_LINE   PO lines whose quantity is not yet covered by an OAR
  SCHEDULE  customer schedules with no OAR and no PO yet
Value = pending pieces x unit price. The price comes from the OAR's PO line, else the PO line with the
same PO number, customer and part, else the schedule. With no price found the order is counted but valued 0
and reported as "no price".
"""
import io
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.models.dispatch import Dispatch
from app.models.master_data import POLine, POMaster, POStatus, ScheduleMaster, ScheduleStatus
from app.models.order import Order, OrderStatus
from app.models.work_order import WorkOrder

SOURCES = ("OAR", "PO_LINE", "SCHEDULE")
TILE_COLOURS = ["C00000", "E36C09", "BF9000", "2E7D32", "1F4E78", "595959"]


def _month_label(d: date) -> str:
    return d.strftime("%b-%Y")


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def buckets_for(today: date) -> List[Dict]:
    """Due up to this month (overdue included), the next three months, then beyond; plus orders without a date."""
    m0 = date(today.year, today.month, 1)
    names = [m0] + [_add_months(m0, i) for i in (1, 2, 3)]
    return [
        {"key": "DUE", "label": f"Due up to {_month_label(m0)}", "end": _add_months(m0, 1)},
        {"key": "M1", "label": f"{_month_label(names[1])} Delivery", "end": _add_months(m0, 2)},
        {"key": "M2", "label": f"{_month_label(names[2])} Delivery", "end": _add_months(m0, 3)},
        {"key": "M3", "label": f"{_month_label(names[3])} Delivery", "end": _add_months(m0, 4)},
        {"key": "BEYOND", "label": f"Beyond {_month_label(names[3])}", "end": None},
    ]


def _bucket_key(d: Optional[date], buckets: List[Dict]) -> str:
    if d is None:
        return "NODATE"
    for b in buckets:
        if b["end"] is None or d < b["end"]:
            return b["key"]
    return "BEYOND"


def _price_target(line, schedule, order=None):
    """What a price edit on a dashboard row changes: the PO line when there is one, else the schedule, else (for an
    order with neither) the order itself, which gets its PO line recorded. Read only: the dashboards use it to show
    an Edit price action; the edit itself goes through the masters API."""
    if line is not None:
        return {"type": "PO_LINE", "po_id": str(line.po_id), "line_id": str(line.id)}
    if schedule is not None:
        return {"type": "SCHEDULE", "id": str(schedule.id)}
    if order is not None:
        return {"type": "ORDER", "order_id": str(order.id)}
    return None


def collect_items(db: Session, include: Optional[List[str]] = None) -> List[Dict]:
    include = [s.upper() for s in (include or SOURCES)]
    items: List[Dict] = []

    # prices and PO-line coverage
    pos = {str(p.id): p for p in db.query(POMaster).all() if p.status not in (POStatus.CANCELLED, POStatus.CLOSED)}
    lines_by_key: Dict[tuple, POLine] = {}
    lines = [l for l in db.query(POLine).all() if str(l.po_id) in pos]
    for l in lines:
        p = pos[str(l.po_id)]
        lines_by_key[((p.po_number or "").strip().upper(), str(p.customer_id), str(l.part_id))] = l
    all_lines = {str(l.id): l for l in db.query(POLine).all()}
    schedules = {str(s.id): s for s in db.query(ScheduleMaster).all()}

    # dispatched per order
    disp: Dict[str, int] = defaultdict(int)
    wo_order = {str(w.id): str(w.order_id) for w in db.query(WorkOrder.id, WorkOrder.order_id).all()}
    for d in db.query(Dispatch.work_order_id, Dispatch.dispatched_qty).all():
        disp[wo_order.get(str(d[0]), "")] += d[1] or 0

    covered: Dict[str, int] = defaultdict(int)        # po_line id -> pieces already in OARs
    sched_has_oar = set()
    for o in db.query(Order).all():
        key = ((o.customer_po or "").strip().upper(), str(o.customer_id), str(o.part_id))
        line = all_lines.get(str(o.po_line_id)) if o.po_line_id else lines_by_key.get(key)
        if line is not None:
            covered[str(line.id)] += o.po_qty or 0
        if o.schedule_id:
            sched_has_oar.add(str(o.schedule_id))
        if "OAR" not in include or o.status == OrderStatus.REJECT:
            continue
        pending = max((o.po_qty or 0) - disp.get(str(o.id), 0) - (o.fulfilled_from_stock_qty or 0), 0)
        if pending <= 0:
            continue
        price = line.unit_price if line is not None and line.unit_price else None
        if price is None and o.schedule_id and schedules.get(str(o.schedule_id)) and schedules[str(o.schedule_id)].unit_price:
            price = schedules[str(o.schedule_id)].unit_price
        items.append({
            "source": "OAR", "ref": o.oar_number or "", "customer": o.customer.name if o.customer else "",
            "po": o.customer_po, "part": o.part.part_number if o.part else "", "pending_qty": pending,
            "unit_price": price, "value": round(pending * price, 2) if price else 0.0, "has_price": bool(price),
            "date": o.delivery_date or o.commitment_date,
            "price_target": _price_target(line, schedules.get(str(o.schedule_id)) if o.schedule_id else None, o),
        })

    if "PO_LINE" in include:
        for l in lines:
            p = pos[str(l.po_id)]
            remaining = max((l.po_qty or 0) - covered.get(str(l.id), 0), 0)
            if remaining <= 0:
                continue
            price = l.unit_price or None
            items.append({
                "source": "PO_LINE", "ref": p.po_number, "customer": p.customer.name if p.customer else "",
                "po": p.po_number, "part": l.part.part_number if l.part else "", "pending_qty": remaining,
                "unit_price": price, "value": round(remaining * price, 2) if price else 0.0, "has_price": bool(price),
                "date": l.required_date,
                "price_target": _price_target(l, None),
            })

    if "SCHEDULE" in include:
        for s in schedules.values():
            if str(s.id) in sched_has_oar or s.po_status not in (ScheduleStatus.SCHEDULED, ScheduleStatus.AWAITING_PO):
                continue
            price = s.unit_price or None
            value = s.total_value if s.total_value else (round((s.scheduled_qty or 0) * price, 2) if price else 0.0)
            items.append({
                "source": "SCHEDULE", "ref": s.schedule_number, "customer": s.customer.name if s.customer else "",
                "po": s.customer_schedule_ref or "", "part": s.part.part_number if s.part else "",
                "pending_qty": s.scheduled_qty or 0, "unit_price": price, "value": float(value or 0),
                "has_price": bool(value), "date": s.required_date,
                "price_target": _price_target(None, s),
            })
    return items


def build_report(db: Session, include: Optional[List[str]] = None, today: Optional[date] = None) -> Dict:
    today = today or date.today()
    bks = buckets_for(today)
    items = collect_items(db, include)
    def _new(key, label):
        return {"key": key, "label": label, "count": 0, "value": 0.0, "qty": 0,
                "by_source": {src: {"count": 0, "value": 0.0} for src in SOURCES}}
    agg: Dict[str, Dict] = {b["key"]: _new(b["key"], b["label"]) for b in bks}
    agg["NODATE"] = _new("NODATE", "No delivery date")
    for it in items:
        k = _bucket_key(it["date"], bks)
        it["bucket"] = k
        a = agg[k]
        a["count"] += 1
        a["value"] += it["value"]
        a["qty"] += it["pending_qty"]
        a["by_source"][it["source"]]["count"] += 1
        a["by_source"][it["source"]]["value"] += it["value"]
    rows = [agg[b["key"]] for b in bks] + ([agg["NODATE"]] if agg["NODATE"]["count"] else [])
    for r in rows:
        r["value"] = round(r["value"], 2)
        for v in r["by_source"].values():
            v["value"] = round(v["value"], 2)
    by_source = {s: {"count": 0, "value": 0.0} for s in SOURCES}
    by_customer: Dict[str, Dict] = {}
    for it in items:
        by_source[it["source"]]["count"] += 1
        by_source[it["source"]]["value"] += it["value"]
        c = by_customer.setdefault(it["customer"], {"customer": it["customer"], "count": 0, "value": 0.0})
        c["count"] += 1
        c["value"] += it["value"]
    top = sorted(by_customer.values(), key=lambda c: -c["value"])[:5]
    overdue = [it for it in items if it["date"] and it["date"] < today]
    return {
        "as_of": today.isoformat(),
        "buckets": rows,
        "total": {"count": len(items), "value": round(sum(r["value"] for r in rows), 2), "qty": sum(r["qty"] for r in rows)},
        "by_source": {k: {"count": v["count"], "value": round(v["value"], 2)} for k, v in by_source.items()},
        "top_customers": [{**c, "value": round(c["value"], 2)} for c in top],
        "overdue": {"count": len(overdue), "value": round(sum(i["value"] for i in overdue), 2)},
        "no_price_count": sum(1 for i in items if not i["has_price"]),
        "items": [{**i, "date": i["date"].isoformat() if i["date"] else None} for i in sorted(items, key=lambda x: (x["date"] or date.max, x["ref"]))],
    }


def _inr(n: float) -> str:
    """Indian digit grouping, e.g. 10,35,09,629."""
    s = f"{int(round(n)):d}"
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


INR_FORMAT = '[>=10000000]"₹"##\\,##\\,##\\,##0;[>=100000]"₹"##\\,##\\,##0;"₹"##,##0'
NAVY, SLATE, LIGHT, ZEBRA = "1F3A5F", "475569", "F1F5F9", "F8FAFC"


def _style_header(ws, row: int, cols: int, fill: str = NAVY):
    for c in range(1, cols + 1):
        cell = ws.cell(row, c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=fill)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 24


def _kpi(ws, row: int, col: int, title: str, value, fmt: Optional[str] = None, span: int = 2):
    from openpyxl.styles import Border, Side
    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + span - 1)
    ws.merge_cells(start_row=row + 1, start_column=col, end_row=row + 1, end_column=col + span - 1)
    t, v = ws.cell(row, col, title), ws.cell(row + 1, col, value)
    t.font, v.font = Font(size=9, color=SLATE, bold=True), Font(size=16, bold=True, color=NAVY)
    t.alignment = v.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    if fmt:
        v.number_format = fmt
    for r in (row, row + 1):
        for c in range(col, col + span):
            ws.cell(r, c).fill = PatternFill("solid", fgColor=LIGHT)
            ws.cell(r, c).border = Border(left=Side(style="thick", color=NAVY) if c == col else None)
    ws.row_dimensions[row + 1].height = 28


def _build_workbook(title: str, subtitle: str, kpis: List[tuple], period_rows: List[Dict], period_head: List[str],
                    detail_heads: List[str], detail_rows: List[List], detail_widths: List[int], detail_formats: Dict[int, str],
                    chart_title: str) -> bytes:
    from openpyxl.chart import BarChart, Reference
    wb = Workbook()
    ws = wb.active
    ws.title = "Dashboard"
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:H1")
    ws["A1"] = title
    ws["A1"].font = Font(size=18, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 34
    ws.merge_cells("A2:H2")
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, color=SLATE)
    ws["A2"].alignment = Alignment(indent=1)
    for i, (t, v, f) in enumerate(kpis):
        _kpi(ws, 4, 1 + (i % 4) * 2, t, v, f)
        if i == 3 and len(kpis) > 4:
            pass
    row = 7 if len(kpis) <= 4 else 7
    r0 = row + 1
    for j, h in enumerate(period_head, start=1):
        ws.cell(r0, j, h)
    _style_header(ws, r0, len(period_head))
    for k, pr in enumerate(period_rows, start=1):
        for j, v in enumerate(pr["cells"], start=1):
            c = ws.cell(r0 + k, j, v)
            if k % 2 == 0:
                c.fill = PatternFill("solid", fgColor=ZEBRA)
            if j in pr.get("money", ()):
                c.number_format = INR_FORMAT
    tr = r0 + len(period_rows) + 1
    ws.cell(tr, 1, "TOTAL").font = Font(bold=True)
    for j in range(2, len(period_head) + 1):
        col = get_column_letter(j)
        c = ws.cell(tr, j, f"=SUM({col}{r0 + 1}:{col}{tr - 1})")
        c.font = Font(bold=True)
        if (j in period_rows[0].get("money", ())) if period_rows else False:
            c.number_format = INR_FORMAT
    for c in range(1, len(period_head) + 1):
        ws.cell(tr, c).fill = PatternFill("solid", fgColor=LIGHT)
    for i, w in enumerate([28, 18, 22, 18, 18, 18, 18, 18], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    if period_rows:
        ch = BarChart()
        ch.type = "col"
        ch.title = chart_title
        ch.style = 10
        vcol = next(iter(period_rows[0].get("money", (3,))))
        ch.add_data(Reference(ws, min_col=vcol, min_row=r0, max_row=r0 + len(period_rows)), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=r0 + len(period_rows)))
        ch.legend = None
        ch.height, ch.width = 7.5, 17
        ws.add_chart(ch, f"A{tr + 3}")
    dt = wb.create_sheet("Details")
    dt.append(detail_heads)
    _style_header(dt, 1, len(detail_heads))
    for r in detail_rows:
        dt.append(r)
    for i, w in enumerate(detail_widths, start=1):
        dt.column_dimensions[get_column_letter(i)].width = w
    for col, fmt in detail_formats.items():
        for r in range(2, len(detail_rows) + 2):
            dt.cell(r, col).number_format = fmt
    dt.freeze_panes = "A2"
    dt.auto_filter.ref = f"A1:{get_column_letter(len(detail_heads))}{max(len(detail_rows) + 1, 2)}"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_report(db: Session, include: Optional[List[str]] = None, today: Optional[date] = None) -> bytes:
    rep = build_report(db, include, today)
    d = date.fromisoformat(rep["as_of"])
    label = {b["key"]: b["label"] for b in rep["buckets"]}
    label["NODATE"] = "No delivery date"
    src_name = {"OAR": "Accepted order", "PO_LINE": "PO line (no OAR)", "SCHEDULE": "Schedule (no OAR/PO)"}
    kpis = [("OPEN ORDERS", rep["total"]["count"], None), ("PENDING VALUE", rep["total"]["value"], INR_FORMAT),
            ("OVERDUE ORDERS", rep["overdue"]["count"], None), ("OVERDUE VALUE", rep["overdue"]["value"], INR_FORMAT)]
    periods = [{"cells": [b["label"], b["count"], b["value"], b["qty"]], "money": (3,)} for b in rep["buckets"]]
    heads = ["Period", "Source", "Reference", "Customer", "PO / Schedule ref", "Part", "Pending Qty", "Unit Price", "Pending Value", "Delivery Date"]
    rows = [[label.get(it["bucket"], ""), src_name[it["source"]], it["ref"], it["customer"], it["po"], it["part"], it["pending_qty"],
             it["unit_price"], it["value"], date.fromisoformat(it["date"]) if it["date"] else None] for it in rep["items"]]
    return _build_workbook("Sales Order Status", f"As of {d.strftime('%d %b %Y')}  |  open pending orders by delivery month",
                           kpis, periods, ["Period", "Open Orders", "Pending Value", "Pending Qty"], heads, rows,
                           [22, 20, 16, 30, 20, 18, 12, 14, 16, 14], {8: INR_FORMAT, 9: INR_FORMAT, 10: "DD-MMM-YYYY"},
                           "Pending value by delivery month")


# ------------------------------------------------------------------------------ schedule master
SCHEDULE_OPEN = (ScheduleStatus.SCHEDULED, ScheduleStatus.AWAITING_PO, ScheduleStatus.PO_RECEIVED)
SCHEDULE_NAMES = {"scheduled": "Scheduled", "awaiting_po": "Awaiting PO", "po_received": "PO received",
                  "matched": "Matched to an order", "cancelled": "Cancelled"}


def build_schedule_report(db: Session, today: Optional[date] = None) -> Dict:
    """Customer schedules not yet turned into an order (scheduled, awaiting PO, PO received), by required month."""
    today = today or date.today()
    bks = buckets_for(today)
    all_s = db.query(ScheduleMaster).all()
    status_split = {k: {"label": v, "count": 0, "value": 0.0} for k, v in SCHEDULE_NAMES.items()}
    items = []
    for s in all_s:
        value = float(s.total_value or ((s.scheduled_qty or 0) * (s.unit_price or 0)) or 0)
        st = status_split[s.po_status.value]
        st["count"] += 1
        st["value"] += value
        if s.po_status not in SCHEDULE_OPEN:
            continue
        items.append({"schedule": s.schedule_number, "customer": s.customer.name if s.customer else "",
                      "customer_ref": s.customer_schedule_ref or "", "part": s.part.part_number if s.part else "",
                      "qty": s.scheduled_qty or 0, "unit_price": s.unit_price or None, "value": round(value, 2),
                      "has_price": bool(value), "status": s.po_status.value, "date": s.required_date,
                      "bucket": _bucket_key(s.required_date, bks), "price_target": _price_target(None, s)})
    def _new(key, label):
        return {"key": key, "label": label, "count": 0, "value": 0.0, "qty": 0}
    agg = {b["key"]: _new(b["key"], b["label"]) for b in bks}
    agg["NODATE"] = _new("NODATE", "No required date")
    by_customer: Dict[str, Dict] = {}
    for it in items:
        a = agg[it["bucket"]]
        a["count"] += 1
        a["value"] += it["value"]
        a["qty"] += it["qty"]
        c = by_customer.setdefault(it["customer"], {"customer": it["customer"], "count": 0, "value": 0.0})
        c["count"] += 1
        c["value"] += it["value"]
    rows = [agg[b["key"]] for b in bks] + ([agg["NODATE"]] if agg["NODATE"]["count"] else [])
    for r in rows:
        r["value"] = round(r["value"], 2)
    overdue = [i for i in items if i["date"] and i["date"] < today]
    awaiting = [i for i in items if i["status"] == "awaiting_po"]
    return {
        "as_of": today.isoformat(),
        "buckets": rows,
        "total": {"count": len(items), "value": round(sum(i["value"] for i in items), 2), "qty": sum(i["qty"] for i in items)},
        "overdue": {"count": len(overdue), "value": round(sum(i["value"] for i in overdue), 2)},
        "awaiting_po": {"count": len(awaiting), "value": round(sum(i["value"] for i in awaiting), 2)},
        "status_split": [{"status": k, **{**v, "value": round(v["value"], 2)}} for k, v in status_split.items()],
        "top_customers": [{**c, "value": round(c["value"], 2)} for c in sorted(by_customer.values(), key=lambda c: -c["value"])[:5]],
        "no_price_count": sum(1 for i in items if not i["has_price"]),
        "items": [{**i, "date": i["date"].isoformat() if i["date"] else None} for i in sorted(items, key=lambda x: (x["date"] or date.max, x["schedule"]))],
    }


def export_schedule_report(db: Session, today: Optional[date] = None) -> bytes:
    rep = build_schedule_report(db, today)
    d = date.fromisoformat(rep["as_of"])
    label = {b["key"]: b["label"] for b in rep["buckets"]}
    kpis = [("OPEN SCHEDULES", rep["total"]["count"], None), ("SCHEDULE VALUE", rep["total"]["value"], INR_FORMAT),
            ("AWAITING PO", rep["awaiting_po"]["count"], None), ("OVERDUE SCHEDULES", rep["overdue"]["count"], None)]
    periods = [{"cells": [b["label"], b["count"], b["value"], b["qty"]], "money": (3,)} for b in rep["buckets"]]
    heads = ["Period", "Schedule", "Customer", "Customer Ref", "Part", "Qty", "Unit Price", "Value", "Status", "Required Date"]
    rows = [[label.get(it["bucket"], "No required date"), it["schedule"], it["customer"], it["customer_ref"], it["part"], it["qty"],
             it["unit_price"], it["value"], SCHEDULE_NAMES.get(it["status"], it["status"]),
             date.fromisoformat(it["date"]) if it["date"] else None] for it in rep["items"]]
    return _build_workbook("Customer Schedule Status", f"As of {d.strftime('%d %b %Y')}  |  schedules not yet converted to an order",
                           kpis, periods, ["Period", "Open Schedules", "Schedule Value", "Qty"], heads, rows,
                           [22, 18, 30, 18, 18, 10, 14, 16, 18, 14], {7: INR_FORMAT, 8: INR_FORMAT, 10: "DD-MMM-YYYY"},
                           "Schedule value by required month")
