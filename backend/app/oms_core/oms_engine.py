
"""
VIJAY SPHEROIDALS — Order Management Engine  (v3.3 — LATEST; run this file)
============================================================================================
Changelog since the v3 baseline:
  v3.1  Gate 'Stage Status' (In-Process/Completed); per-stage In-Process Qty; additive
        quantities; Stock Audit tool (align physical counts, move pieces, re-route WOs).
  v3.2  Per-stage RAG status from achieved = (Completed+Rejected)/Planned
        (Green <5% short, Amber 5-10%, Red >=10%); planner-named conversion WOs
        (Conversion WO column) + conversion routing via the WO Release 'Conversion WO' column.
  v3.3  Flow model: In-Process is the live figure = Fed - Completed - Rejected (drops as parts
        finish); NEW calculated On-Hand = Completed - fed-into-next-stage (material available
        at the stage, drops as the next stage pulls parts forward).

v3 additions
------------
* New daily input: WO RELEASE (--wor). Planner declares, per WO, the physical WO quantity
  and the stages that WO is designed to move through (Yes/No per stage column). Not every
  part visits every gate. The engine stores the route on the WO, recomputes stage targets
  over the route only, and overrides WO Good Target with the released physical qty.
* DYNAMIC STAGES: a new stage column in the WO Release template is auto-registered (persisted
  in the master's "Stage Registry" sheet), added to the WO Master schema, accepted by the
  Gate Update (MRB) processor, and reported in every stage-wise report (rejection, WIP).
* AUDITABLE WIP: inventory is now computed per WO along that WO's own route as
      WIP after stage S = OK(S) - (OK(next) + Rej(next))
  (pieces rejected at the next gate were physically consumed from S's output -- the old
  OK(S) - OK(next) formula overstated WIP). Stage totals are built bottom-up from the per-WO
  figures (never a plant-wide clamp), negative gaps are surfaced as exceptions instead of
  being silently clamped to 0, and a new "3c Stage Audit Sheet" lists every WO holding WIP
  at every stage with blank Physical Count / Variance columns for floor verification.
Deterministic engine that powers the order-management agent. All numbering, yield maths,
conversions, roll-ups and reports are pure code (no model tokens), so a daily run is cheap
and fully auditable.

Daily cycle
-----------
    latest master
  + Order Intake   (Sales)
  + Gate Update    (MRB / Production)   -> production, rejections, dispatch + invoice
  + Conversions    (Planner)            -> reallocate / re-route pieces between WOs/OARs
  + NC Tracker     (QA)                 -> non-conformance status + closure
        |
        v   (this engine)
    new Master_<date>.xlsx
  + Daily_Report_<date>.xlsx
        Summary | Status | Rejection(by stage / by WO+NC / by defect)
        Inventory(by stage / by WO+part) | NC Register | PO->Invoice Traceability

Run
---
    python oms_engine.py --master master.xlsx --intake intake.xlsx --mrb gate.xlsx \
        --conv conversions.xlsx --nc nc.xlsx --wor wo_release.xlsx \
        --history "Work Order Data-2.xlsx" --outdir ./out
(every input is optional; feed each new file once per day; --wor is always optional)
"""

import argparse, math, os, datetime as dt
import warnings
# openpyxl can't preserve Excel's extended data-validation (the Yes/No dropdowns in the
# WO Release template); it reads all DATA fine and just drops the dropdown formatting on
# load. The warning is noise on every daily run, so silence exactly that message.
warnings.filterwarnings("ignore", message="Data Validation extension is not supported")
import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, PatternFill as PF
from openpyxl.chart import BarChart, PieChart, LineChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.utils import get_column_letter
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.formatting.rule import CellIsRule, FormulaRule

# v3: stages are DYNAMIC. These lists are the defaults; the master's "Stage Registry"
# sheet is the source of truth once it exists, and a new stage column in the WO Release
# input extends both lists (and the WO Master schema, MRB validation and every stage-wise
# report) automatically. The lists are mutated IN PLACE so every reference sees updates.
BASE_PROD_STAGES = ["F1", "F2", "F3", "SP", "FI"]
PROD_STAGES = list(BASE_PROD_STAGES)
ALL_STAGES = PROD_STAGES + ["Dispatch"]
DEFAULT_YIELDS = {"F1": 0.89, "F2": 0.89, "F3": 0.97, "SP": 0.99, "FI": 0.94}
TODAY = dt.date.today()

# BUG7 FIX: stage names typed/pasted into the daily sheets aren't always the exact case used
# here (e.g. "DISPATCH" instead of "Dispatch"), which made valid Gate Update / Conversions
# rows get rejected as "Invalid stage". Match case-insensitively and normalize to the
# canonical spelling; genuinely unrecognized stages still fail validation.
_STAGE_LOOKUP = {s.upper(): s for s in ALL_STAGES}

# Manual aliases: the floor's habitual name for a stage differs from its registered code.
# "BSR" was in use on the floor before the stage was formally registered as "Packing" --
# rather than retrain data entry or hand-correct everything already typed, BSR resolves
# straight to Packing once Packing is registered. Extend this dict for any future renames.
_STAGE_ALIASES = {"BSR": "Packing"}


def _rebuild_stage_lookup():
    _STAGE_LOOKUP.clear()
    _STAGE_LOOKUP.update({s.upper(): s for s in ALL_STAGES})


def _canon_stage(s):
    key = _str(s).upper()
    key = _STAGE_ALIASES.get(key, key).upper()
    return _STAGE_LOOKUP.get(key, _str(s))



# Stage-completion vocabulary ---------------------------------------------------------------
# A stage's Status is one of: Pending | In-Progress | Green | Amber | Red | Converted-in | Skip
# v3.2: the per-stage status is a RAG rating driven by ACHIEVED = (OK Completed + Rejected) /
# Planned (stage target) — i.e. how much of the planned quantity has been accounted for at the
# gate. shortfall = 1 - achieved:
#   Green  = shortfall < 5%   (planned qty essentially all processed / met / exceeded)
#   Amber  = 5% <= shortfall < 10%
#   Red    = shortfall >= 10%
#   In-Progress = pieces in process but nothing completed/rejected yet (nothing to rate)
#   Pending / Skip = not started / not on route
# (Note: RAG measures throughput completeness at the gate; the WO-level Shortfall flag still
#  tracks GOOD-output adequacy via the projection off OK, which is a separate signal.)
STAGE_DONE = ("Green", "Amber", "Red", "Converted-in")
# DISPATCH_DONE = the WO has shipped (any completed dispatch, clean or short) -> dispatched/closeable.
DISPATCH_DONE = ("Green", "Amber", "Red")


def _rag_status(ok, rej, inproc, target):
    """RAG rating for a stage from its quantities (v3.2).
    achieved = (OK + Rej) / target ; shortfall = 1 - achieved.
      shortfall < 5%  -> Green ; 5%-<10% -> Amber ; >=10% -> Red.
    A stage with no completed/rejected activity yet is In-Progress (if pieces are in process)
    or Pending (nothing at all) — it has no achieved ratio to rate."""
    processed = int(_num(ok)) + int(_num(rej))
    if processed <= 0:
        return "In-Progress" if int(_num(inproc)) > 0 else "Pending"
    tgt = int(_num(target))
    if tgt <= 0:
        return "Green"                      # no plan to measure against -> treat as met
    shortfall = (tgt - processed) / tgt
    EPS = 1e-9                               # guard float boundaries at exactly 5% / 10%
    if shortfall < 0.05 - EPS:
        return "Green"
    if shortfall < 0.10 - EPS:
        return "Amber"
    return "Red"

# v3.1: Gate Update (MRB) "Stage Status" column — the floor's explicit declaration of whether
# the WO has FINISHED the reported stage or is still being worked at it. This replaces the old
# purely count-driven "Green when cum >= target" inference. Blank => legacy count-based fallback.
_WO_STATUS_LOOKUP = {
    "COMPLETED": "Completed", "COMPLETE": "Completed", "DONE": "Completed",
    "CLOSED": "Completed", "FINISHED": "Completed", "C": "Completed",
    "IN-PROCESS": "In-Process", "IN PROCESS": "In-Process", "INPROCESS": "In-Process",
    "IN-PROGRESS": "In-Process", "IN PROGRESS": "In-Process", "INPROGRESS": "In-Process",
    "WIP": "In-Process", "IP": "In-Process", "P": "In-Process", "OPEN": "In-Process",
    "RUNNING": "In-Process", "ONGOING": "In-Process",
}


def _canon_wo_status(x):
    """Normalize the Gate Update 'Stage Status' cell to 'Completed' / 'In-Process' / ''.
    Unrecognized non-blank values are returned as-is so preflight can flag them."""
    raw = _str(x)
    if not raw:
        return ""
    return _WO_STATUS_LOOKUP.get(raw.upper(), raw)


def _set_stage_order(prod_stages):
    """Replace the production stage sequence in place (Dispatch always last)."""
    PROD_STAGES[:] = list(prod_stages)
    ALL_STAGES[:] = PROD_STAGES + ["Dispatch"]
    _rebuild_stage_lookup()


def _ensure_wo_stage_cols(m):
    """Guarantee the WO Master has Target/OK/Rej/Status columns for every known stage
    (and the v3 route columns), with safe defaults for pre-existing rows."""
    wom = m["WO Master"]
    defaults = {"Target": 0, "OK": 0, "InProc": 0, "OnHand": 0, "Rej": 0, "Status": "Skip", "Ent": 0}
    for s in ALL_STAGES:
        for metric, dv in defaults.items():
            col = f"{s} {metric}"
            if col not in wom.columns:
                wom[col] = dv
    for col, dv in (("Route", ""), ("Released Qty", ""), ("Release Date", ""),
                    ("Released By", "")):
        if col not in wom.columns:
            wom[col] = dv


def sync_stages_from_registry(m):
    """On load: seed the Stage Registry with the base stages if empty, else adopt the
    registry's stage order. Keeps dynamic stages alive across daily runs."""
    reg = m["Stage Registry"]
    if len(reg) == 0:
        for i, s in enumerate(BASE_PROD_STAGES):
            reg.loc[len(reg)] = [s, i + 1, str(TODAY), "base"]
    order = reg.sort_values("Seq")["Stage"].astype(str).tolist()
    _set_stage_order([s for s in order if s != "Dispatch"])
    for s in PROD_STAGES:
        DEFAULT_YIELDS.setdefault(s, 1.0)
    _ensure_wo_stage_cols(m)


def register_stage(m, stage, after=None, source=""):
    """Add a NEW production stage (idempotent). Inserted after `after` if given, else
    just before FI/Dispatch-end. Persists to Stage Registry, extends the WO Master schema,
    MRB validation and all stage-wise reports (they iterate PROD_STAGES/ALL_STAGES)."""
    stage = _str(stage)
    if not stage or stage in ALL_STAGES:
        return False
    seq = list(PROD_STAGES)
    pos = seq.index(after) + 1 if (after in seq) else len(seq)
    seq.insert(pos, stage)
    _set_stage_order(seq)
    DEFAULT_YIELDS.setdefault(stage, 1.0)  # no history for a brand-new stage
    reg = m["Stage Registry"]
    reg["Seq"] = [seq.index(str(s)) + 1 if str(s) in seq else _num(v, 999)
                  for s, v in zip(reg["Stage"], reg["Seq"])]
    reg.loc[len(reg)] = [stage, seq.index(stage) + 1, str(TODAY), source]
    m["Stage Registry"] = reg.sort_values("Seq").reset_index(drop=True)
    _ensure_wo_stage_cols(m)
    audit(m, "STAGE_REGISTER", stage, new=stage, source=source,
          note=f"sequence now {' > '.join(ALL_STAGES)}")
    return True


def _parse_route(route_str):
    """'F1 > F3 > FI' -> ['F1','F3','FI','Dispatch'] (canonical, Dispatch always last)."""
    stages = [_canon_stage(x) for x in _str(route_str).replace(",", ">").split(">")]
    stages = [s for s in (x.strip() for x in stages) if s and s != "Dispatch"]
    return stages + ["Dispatch"]


def _wo_route(wom, n):
    """The stage sequence THIS WO moves through. Blank Route (pre-v3 WOs, or WOs not yet
    released) = the full plant sequence, preserving old behaviour."""
    rt = _str(wom.at[n, "Route"]) if "Route" in wom.columns else ""
    if not rt:
        return list(ALL_STAGES)
    return _parse_route(rt)


def _route_of_row(w):
    """Same as _wo_route but for a plain row/dict/Series (used in reports)."""
    rt = _str(w.get("Route", "")) if hasattr(w, "get") else ""
    if not rt:
        return list(ALL_STAGES)
    return _parse_route(rt)


# BUG9 FIX: WO IDs pasted from QA's NC-tracking software (or typed by hand) sometimes come in
# as bare numbers ("14960") instead of the "WO-14960" format used everywhere else in the
# system. A bare number never matches the master's "WO-14960" keys, so every such row was
# being flagged as "WO not found in master" even when the WO genuinely exists. Normalize any
# purely-numeric WO ID to the canonical "WO-<number>" form; anything already prefixed (in any
# case) is normalized to "WO-"; anything else is passed through unchanged so a truly bad value
# still surfaces as a real anomaly instead of being silently reinterpreted.
def _canon_wo(x):
    s = _str(x)
    if not s:
        return s
    if s.upper().startswith("WO-"):
        return "WO-" + s[3:]
    core = s.split(".")[0] if s.replace(".", "", 1).isdigit() else s  # tolerate "14960.0" from Excel float read
    return f"WO-{core}" if core.isdigit() else s

BLUE = "2E5496"
HF = Font(name="Arial", bold=True, color="FFFFFF", size=11)
HFILL = PatternFill("solid", fgColor=BLUE)


# ------------------------------------------------------------------ helpers
def _num(x, d=0.0):
    try:
        return d if pd.isna(x) else float(x)
    except Exception:
        return d


def _str(x):
    return "" if pd.isna(x) else str(x).strip()


# BUG5 FIX: the daily input templates (Order Intake, Gate Update, Conversions, NC Tracker)
# built by build_new_templates.py/build_intake.py carry a 2-row title/instructions banner
# plus a blank row before the real header row (row 4 on the sheet). Every
# pd.read_excel(path, sheet_name=...) call in this file was reading with the default
# header=0, so it picked up the banner text as the column names and every
# r.get("Order Status")/r.get("NC Number")/etc. lookup silently returned nothing — rows
# were skipped with no error and no exception logged. Rather than hardcode "row 4" (which
# would break on plainer files, e.g. test fixtures with headers on row 1), we scan the first
# few rows for a marker column that must be present, and use whichever row it's found on.
_HEADER_MARKER = {"Order Intake": "Order Status", "Gate Update": "Stage",
                  "Conversions": "Source WO ID", "NC Tracker": "NC Number",
                  "WO Release": "Physical WO Qty", "Stock Audit": "Physical Count"}


def _detect_header_row(path, sheet, marker, max_scan=15):
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet]
        for r_idx, row in enumerate(ws.iter_rows(min_row=1, max_row=max_scan, values_only=True)):
            cells = [str(v).strip() if v is not None else "" for v in row]
            if marker in cells:
                return r_idx  # 0-indexed -> pandas header= value
    finally:
        wb.close()
    return 0  # fallback: assume no banner


def _read_input_sheet(path, sheet):
    marker = _HEADER_MARKER.get(sheet)
    hdr = _detect_header_row(path, sheet, marker) if marker else 0
    df = pd.read_excel(path, sheet_name=sheet, header=hdr)
    df.columns = [str(c).strip().rstrip("*").strip() for c in df.columns]
    # BUG11 FIX: every anomaly/exception message quotes an Excel row number as `i + 2`,
    # which is only correct when the header sits on row 1 (hdr=0). Every VSPL daily
    # template has a title/instructions banner before the real header (hdr = however many
    # rows _detect_header_row skipped), so a flagged row was reported `hdr` rows too early
    # -- e.g. header on row 4 (hdr=3) made the first real data row (Excel row 5) print as
    # "row 2". Stash the offset on the frame so every caller can compute the true row via
    # _excel_row() instead of hardcoding "+2".
    df.attrs["hdr"] = hdr
    return df


def _excel_row(df, i):
    """True 1-indexed Excel row for DataFrame position i, honoring this sheet's banner
    offset (see BUG11 FIX above). Falls back to the old i+2 if a frame has no offset
    recorded (e.g. built in-memory by a test, where hdr is genuinely 0)."""
    return i + df.attrs.get("hdr", 0) + 2


def _key(po, part):
    return f"{_str(po).upper()}||{_str(part).upper()}"


def _days(raised, closed):
    try:
        # BUG8 FIX: NC Tracker dates are typed as plain DD/MM/YYYY text (VSPL's convention).
        # Without dayfirst=True, pandas defaults to month-first and silently misreads any
        # date with day <= 12 (e.g. "02/07/2026" -> Feb 7 instead of Jul 2) — corrupting
        # "Days Open" ageing without ever raising an error.
        r = pd.to_datetime(raised, errors="coerce", dayfirst=True)
        c = pd.to_datetime(closed, errors="coerce", dayfirst=True)
        end = c if pd.notna(c) else pd.Timestamp(TODAY)
        return int((end - r).days) if pd.notna(r) else ""
    except Exception:
        return ""


def _is_terminal_status(overall_status):
    """True for 'Dispatched' (a real shipment) OR any admin closure whose Overall Status
    starts with 'Closed' (e.g. 'Closed (Legacy 2025)', 'Closed (Cancelled)') -- both mean
    the WO is done and should drop out of Open/Shortfall/Delivery-Risk counts, without
    being counted as an actual dispatch. Matched by prefix, not an exact literal, so a
    future closure label (a different reason, a different year) is recognized the same
    way without another engine change."""
    s = _str(overall_status).upper()
    return s == "DISPATCHED" or s.startswith("CLOSED")


def _delivery_risk(due, current_stage, overall_status, route=None):
    """Time-based delivery risk: compares days left to customer delivery date
    against stages still remaining ON THIS WO'S ROUTE (not a quantity check)."""
    if _is_terminal_status(overall_status):
        return "On Track"
    try:
        due_ts = pd.to_datetime(due, errors="coerce", dayfirst=True)
        if pd.isna(due_ts):
            return "Unknown"
        due_date = due_ts.date()
    except Exception:
        return "Unknown"
    days_left = (due_date - TODAY).days
    seq = route or ALL_STAGES
    try:
        idx = seq.index(_str(current_stage))
    except ValueError:
        idx = 0
    stages_remaining = max(len(seq) - idx, 1)
    if days_left < 0:
        return "OVERDUE"
    if days_left <= stages_remaining:
        return "HIGH RISK"
    if days_left <= stages_remaining * 2:
        return "AT RISK"
    return "On Track"


def compute_yields(history_path):
    y = dict(DEFAULT_YIELDS)
    if not history_path or not os.path.exists(history_path):
        return y, "defaults only (no history)"
    try:
        df = pd.read_excel(history_path, sheet_name="Fdata")
    except Exception:
        return y, "defaults only (history unreadable)"
    pairs = {"F1": ("F1 OK (RCD QTY)", "F1 Rejected (RCD Qty)"),
             "F2": ("F2 Produced", "F2 Rejected"),
             "F3": ("F3 Inward", "F3 Rejected"),
             "FI": ("FI ok qty", "FI Rejected")}
    notes = []
    for st, (okc, rjc) in pairs.items():
        if okc in df and rjc in df:
            ok = pd.to_numeric(df[okc], errors="coerce").fillna(0)
            rj = pd.to_numeric(df[rjc], errors="coerce").fillna(0)
            mask = (ok + rj) > 0
            n = int(mask.sum());
            tot = (ok + rj)[mask].sum()
            if n >= 30 and tot > 0:
                y[st] = round(ok[mask].sum() / tot, 4);
                notes.append(f"{st}={y[st]}(n={n})")
            else:
                notes.append(f"{st}=def{y[st]}(n={n})")
    return y, "; ".join(notes)


def stage_targets(good, yields, route=None):
    """Back-calculate per-stage targets from yield — over the WO's own route only.
    Stages not on the route get no target (they are reported as Skip)."""
    prod = [s for s in (route or ALL_STAGES) if s != "Dispatch"]
    t = {}
    need = good
    for st in reversed(prod):
        t[st] = math.ceil(need)
        need = need / yields.get(st, 1.0)
    t["Dispatch"] = math.ceil(good)
    return t


# ------------------------------------------------------------------ master schema
def wo_cols():
    """WO Master column list — rebuilt on demand because stages are dynamic."""
    return (["WO ID", "OAR No", "Customer", "Customer PO Number", "Part No", "Grade",
             "WO Good Target", "Max Batch Size", "Cust Delivery Date", "Source",
             "Route", "Released Qty", "Release Date", "Released By"]
            + [f"{s} {m}" for s in ALL_STAGES for m in ("Target", "OK", "InProc", "OnHand", "Rej", "Status", "Ent")]
            + ["Current Stage", "Projected Final Good", "Shortfall", "Overall Status",
               "Converted From", "Converted To"])


WO_COLS = wo_cols()  # snapshot for a fresh master; real column set lives on the DataFrame

MASTER_SHEETS = {
    "OAR Register": ["OAR No", "Date Accepted", "Customer", "Customer Code",
                     "Customer PO Number", "Part No", "Grade", "PO Quantity", "Max Batch Size",
                     "Cust Delivery Date", "Order Type", "Order Category", "No. of WOs",
                     "Source of Accept.", "Status"],
    "WO Master": WO_COLS,
    "Disposition Ledger": ["Date", "WO ID", "OAR No", "Part No", "Stage", "Source", "Subcon",
                           "Defect Code", "Rejected Qty", "Disposition", "NC Number"],
    "NC Register": ["NC Number", "WO ID", "OAR No", "Part No", "Stage", "Defect Code", "Qty",
                    "NC Status", "Date Raised", "Date Closed", "Days Open", "Responsibility",
                    "Disposition", "Remarks"],
    "Conversion Ledger": ["Date", "Conversion WO", "Source WO", "Source OAR", "Dest OAR",
                          "Part From", "Part To", "Qty", "Entry Stage", "Reason", "Planner"],
    "Dispatch Ledger": ["Date", "WO ID", "OAR No", "Customer", "Customer PO Number", "Part No",
                        "Dispatched Qty", "Invoice No", "Invoice Date"],
    "Audit Log": ["Timestamp", "Action", "Entity", "Field", "Old", "New", "Source", "Note"],
    "Exceptions": ["Timestamp", "Type", "Detail", "Source Row"],
    "Hold Log": ["Date Held", "Customer", "Customer PO Number", "Part No", "PO Quantity",
                 "Cust Delivery Date", "Hold Reason", "OAR No"],
    "Rejected Log": ["Date Rejected", "Customer", "Customer PO Number", "Part No",
                     "PO Quantity", "Reject Reason", "OAR No"],
    "MRB Posted": ["Signature"],
    "Conv Posted": ["Signature"],
    "WOR Posted": ["Signature"],
    "Audit Posted": ["Signature"],
    "Audit Ledger": ["Audit Date", "WO ID", "Action", "Stage", "From Stage", "To Stage",
                     "System Qty", "Counted/Move Qty", "Variance", "New Route",
                     "Reason", "Audited By"],
    "Stage Registry": ["Stage", "Seq", "Added On", "Source"],
    "Counters": ["Key", "Last"],  # highest-ever WO/OAR number (incl. closed history)
    "Trend History": ["Date", "Total WOs", "Shortfalls", "Open NCs", "Open NCs Aged 7d+",
                      "Dispatched", "OARs", "Conversions", "Overdue WOs", "Overall Reject %"],
}


def load_master(path):
    # BUG10 FIX: saving then reloading a master round-trips any purely-numeric-looking text
    # (e.g. NC Number "100123") back as a numeric dtype (int64) — pandas/openpyxl silently
    # reinterpret it on read. That's invisible on a brand-new NC (pure insert), but the moment
    # a later run tries to UPDATE that same row via reg.at[idx, col] = "<string>", pandas can't
    # fit a string into a column it decided was int64 and raises LossySetitemError, crashing
    # the whole run. Casting every column to object dtype right after load makes it tolerant
    # of any single-cell write of any type, without altering any values — numeric math and
    # date parsing elsewhere already go through _num()/pd.to_datetime() rather than relying on
    # column dtype, so this is safe.
    # GUARD: a --master path that was GIVEN but doesn't resolve on disk (wrong folder, typo,
    # not yet produced) must FAIL LOUDLY — never silently fall through to a brand-new empty
    # master. Silently starting empty renumbers every WO from 1 and discards the real master,
    # producing a valid-looking but catastrophically wrong output. Only the genuine "no master
    # given" case (path is None/"") is allowed to start fresh.
    if path and not os.path.exists(path):
        raise FileNotFoundError(
            f"--master path given but not found on disk: '{path}'. "
            f"If you meant to start a brand-new master, omit --master entirely; "
            f"otherwise check the filename/folder and try again.")
    if path and os.path.exists(path):
        xl = pd.read_excel(path, sheet_name=None)
        out = {}
        for s, c in MASTER_SHEETS.items():
            df = xl.get(s, pd.DataFrame(columns=c)).copy()
            df = df.astype(object)
            out[s] = df
        sync_stages_from_registry(out)  # v3: adopt persisted stage order + route columns
        return out
    m = {s: pd.DataFrame(columns=c, dtype=object) for s, c in MASTER_SHEETS.items()}
    sync_stages_from_registry(m)
    return m


def _next_id(df, col, prefix):
    nums = [int(str(v).split("-")[-1]) for v in df[col].dropna()
            if str(v).startswith(prefix) and str(v).split("-")[-1].isdigit()]
    return f"{prefix}-{(max(nums) + 1) if nums else 1}"


def _counter_get(m, key):
    c = m["Counters"];
    row = c[c["Key"] == key]
    return int(row["Last"].iloc[0]) if len(row) else 0


def _counter_set(m, key, val):
    c = m["Counters"];
    idx = c.index[c["Key"] == key]
    if len(idx):
        c.at[idx[0], "Last"] = val
    else:
        c.loc[len(c)] = [key, val]


def _next_seq(m, kind):
    """Monotonic next ID that never collides — uses max(persistent counter, max in table).
    The counter (seeded from full history at migration) survives even when closed WOs aren't
    in the live master."""
    col, sheet, prefix = ("WO ID", "WO Master", "WO") if kind == "WO" else ("OAR No", "OAR Register", "OAR")
    nums = [int(str(v).split("-")[-1]) for v in m[sheet][col].dropna()
            if str(v).startswith(prefix) and str(v).split("-")[-1].isdigit()]
    nxt = max([_counter_get(m, kind)] + nums) + 1
    _counter_set(m, kind, nxt)
    return f"{prefix}-{nxt}"


def audit(m, action, entity, field="", old="", new="", source="", note=""):
    m["Audit Log"].loc[len(m["Audit Log"])] = [dt.datetime.now().isoformat(timespec="seconds"),
                                               action, entity, field, old, new, source, note]


def exception(m, typ, detail, row=""):
    m["Exceptions"].loc[len(m["Exceptions"])] = [dt.datetime.now().isoformat(timespec="seconds"),
                                                 typ, detail, row]


def _blank_wo():
    return {c: "" for c in wo_cols()}


def _append_wo(m, row):
    """Append a WO row dict aligned to the LIVE WO Master columns (stages are dynamic)."""
    wom = m["WO Master"]
    wom.loc[len(wom)] = [row.get(c, "") for c in wom.columns]


def _set_targets(row, good, yields, route=None):
    route = route or list(ALL_STAGES)
    t = stage_targets(good, yields, route)
    for s in ALL_STAGES:
        on_route = s in route
        row[f"{s} Target"] = t.get(s, 0) if on_route else 0
        row[f"{s} OK"] = 0
        row[f"{s} InProc"] = 0
        row[f"{s} OnHand"] = 0
        row[f"{s} Ent"] = 0
        row[f"{s} Rej"] = 0
        row[f"{s} Status"] = "Pending" if on_route else "Skip"


# ------------------------------------------------------------------ intake
def process_intake(m, path, yields):
    if not path or not os.path.exists(path):
        return
    df = _read_input_sheet(path, "Order Intake")
    existing = set(_key(r["Customer PO Number"], r["Part No"]) for _, r in m["OAR Register"].iterrows())
    for i, r in df.iterrows():
        status = _str(r.get("Order Status"));
        po = _str(r.get("Customer PO Number"))
        part = _str(r.get("Part No"));
        ref = f"Intake row {_excel_row(df, i)}"
        if not status or not po:
            continue
        if status == "Hold":
            m["Hold Log"].loc[len(m["Hold Log"])] = [TODAY, _str(r.get("Customer")), po, part,
                                                     _num(r.get("PO Quantity")), r.get("Cust Delivery Date"),
                                                     _str(r.get("Hold / Reject Reason")), ""]
            audit(m, "HOLD", po, source=ref);
            continue
        if status == "Rejected":
            m["Rejected Log"].loc[len(m["Rejected Log"])] = [TODAY, _str(r.get("Customer")), po,
                                                             part, _num(r.get("PO Quantity")),
                                                             _str(r.get("Hold / Reject Reason")), ""]
            audit(m, "REJECT", po, source=ref);
            continue
        if status != "Accepted" or _key(po, part) in existing:
            continue
        batch = _num(r.get("Max Batch Size"));
        poqty = _num(r.get("PO Quantity"))
        if batch <= 0 or poqty <= 0:
            exception(m, "Missing/invalid qty", f"PO {po}/{part}: batch={batch}, qty={poqty}", ref);
            continue
        oar = _next_seq(m, "OAR");
        nwo = math.ceil(poqty / batch)
        m["OAR Register"].loc[len(m["OAR Register"])] = [oar, TODAY, _str(r.get("Customer")),
                                                         _str(r.get("Customer Code")), po, part, _str(r.get("Grade")),
                                                         poqty, batch,
                                                         r.get("Cust Delivery Date"), _str(r.get("Order Type")),
                                                         _str(r.get("Order Category")),
                                                         nwo, "Order Intake", "Open"]
        existing.add(_key(po, part));
        audit(m, "OAR_CREATE", oar, new=oar, source=ref, note=f"{nwo} WO")
        rem = int(poqty)
        for _ in range(nwo):
            good = min(int(batch), rem);
            rem -= good
            wo = _next_seq(m, "WO");
            row = _blank_wo()
            row.update({"WO ID": wo, "OAR No": oar, "Customer": _str(r.get("Customer")),
                        "Customer PO Number": po, "Part No": part, "Grade": _str(r.get("Grade")),
                        "WO Good Target": good, "Max Batch Size": batch,
                        "Cust Delivery Date": r.get("Cust Delivery Date"), "Source": "Inhouse",
                        "Current Stage": "F1", "Projected Final Good": good, "Shortfall": "No",
                        "Overall Status": "Open"})
            _set_targets(row, good, yields)  # full route until a WO Release narrows it
            _append_wo(m, row)
            audit(m, "WO_CREATE", wo, new=wo, source=ref, note=f"target {good}")


# ------------------------------------------------------------------ conversions
def process_conversions(m, path, yields, wor_path=None):
    if not path or not os.path.exists(path):
        return
    df = _read_input_sheet(path, "Conversions")
    wom = m["WO Master"]
    posted = set(m["Conv Posted"]["Signature"].astype(str))
    for i, r in df.iterrows():
        cname = _canon_wo(r.get("Conversion WO"))    # planner-supplied name (e.g. C-0021)
        src = _canon_wo(r.get("Source WO ID"));
        dest = _str(r.get("Dest OAR No"))
        qty = int(_num(r.get("Convert Qty")));
        entry = _canon_stage(r.get("Entry Stage"))
        partto = _str(r.get("Dest Part No"));
        ref = f"Conv row {_excel_row(df, i)}"
        if not cname and not src and not dest:
            continue
        # v3.2: the Conversion WO name is a PLANNER INPUT (only conversion WOs are named by
        # hand; all other WOs are auto-numbered). It becomes the new WO's ID, so it is
        # mandatory and must be unique.
        sig = f"{_str(r.get('Date'))}|{cname}|{src}|{dest}|{qty}|{entry}|{partto}"
        if sig in posted:
            audit(m, "CONV_DUP_SKIP", cname or src, source=ref);
            continue
        if not cname:
            exception(m, "Conversion: missing Conversion WO name",
                      f"{src}->{dest}: planner must supply a unique Conversion WO name "
                      f"(e.g. C-0021) — not auto-generated", ref)
            continue
        if (wom["WO ID"].astype(str) == cname).any():
            exception(m, "Conversion: duplicate Conversion WO name",
                      f"'{cname}' already exists as a WO ID — names must be unique", ref)
            continue
        sidx = wom.index[wom["WO ID"].astype(str) == src]
        didx = m["OAR Register"].index[m["OAR Register"]["OAR No"].astype(str) == dest]
        if len(sidx) == 0:
            exception(m, "Conversion: source WO not found", f"{src}", ref);
            continue
        if len(didx) == 0:
            exception(m, "Conversion: dest OAR not found", f"{dest}", ref);
            continue
        if entry not in ALL_STAGES or qty <= 0:
            exception(m, "Conversion: bad entry stage / qty", f"{src}->{dest} {entry} {qty}", ref);
            continue
        sidx = sidx[0];
        doar = m["OAR Register"].loc[didx[0]]
        partfrom = _str(wom.at[sidx, "Part No"])
        ei = ALL_STAGES.index(entry)
        # BUG2 FIX: hard-block if source WO doesn't have enough qty at expected stage.
        # This check MUST run before any row is created — checking after creating the
        # destination WO left a phantom, fully-credited WO in the master on every blocked
        # conversion (caught by test_oms_math.py::test_blocked_when_insufficient_quantity).
        # v3: the debit stage is route-aware — it's the stage BEFORE the entry stage on the
        # SOURCE WO's own route (its pieces physically sit after its own previous gate),
        # falling back to the source route's last production stage / global previous.
        srt = _wo_route(wom, sidx)
        if entry in srt:
            j = srt.index(entry)
            debit = srt[j - 1] if j > 0 else srt[0]
        else:
            sprod = [s for s in srt if s != "Dispatch"]
            debit = sprod[-1] if sprod else (ALL_STAGES[ei - 1] if ei > 0 else "F1")
        available = int(_num(wom.at[sidx, f"{debit} OK"]))
        if available < qty:
            exception(m, "Conversion: insufficient qty at expected stage",
                      f"{src} has {available} at {debit}, needs {qty} — conversion blocked", ref)
            continue  # skip this conversion entirely, master unchanged for this row
        # create conversion WO under destination OAR — using the PLANNER-SUPPLIED name as its ID
        cwo = cname
        row = _blank_wo()
        row.update({"WO ID": cwo, "OAR No": dest, "Customer": _str(doar["Customer"]),
                    "Customer PO Number": _str(doar["Customer PO Number"]),
                    "Part No": partto or _str(doar["Part No"]), "Grade": _str(doar["Grade"]),
                    "WO Good Target": qty, "Max Batch Size": _num(doar["Max Batch Size"]),
                    "Cust Delivery Date": doar["Cust Delivery Date"], "Source": "Inhouse",
                    "Projected Final Good": qty, "Shortfall": "No", "Overall Status": "In-Progress",
                    "Converted From": src})
        # v3.2: the conversion WO's downstream route comes from its WO Release row (the
        # 'Conversion WO' column) — the planner declares which stages it passes through, just
        # like any released WO. The carried-in pieces sit as good WIP at the credit stage (the
        # stage before the entry stage) and the WO proceeds through the released route. If no
        # WO Release row is supplied, fall back to "entry stage onward through the full sequence".
        wroute, _wqty = _wor_conv_route(wor_path, cname)
        if wroute:
            downstream = [s for s in wroute if ALL_STAGES.index(s) >= ei]
            if entry not in downstream:
                downstream = [entry] + downstream
            conv_route = ([ALL_STAGES[ei - 1]] if ei > 0 else []) + downstream + ["Dispatch"]
        else:
            conv_route = ALL_STAGES[ei:]
            if ei > 0:
                conv_route = [ALL_STAGES[ei - 1]] + conv_route  # credit stage carries the WIP
        _seen = []
        conv_route = [s for s in conv_route if not (s in _seen or _seen.append(s))]
        row["Route"] = " > ".join(conv_route)
        _set_targets(row, qty, yields, route=conv_route)
        for j, s in enumerate(ALL_STAGES):
            if j < ei:  # stages before entry not required of this WO
                row[f"{s} Target"] = 0;
                row[f"{s} OK"] = 0;
                row[f"{s} Status"] = "Converted-in"
        if ei > 0:  # pieces arrive as good WIP after the prior stage
            prev = ALL_STAGES[ei - 1]
            row[f"{prev} OK"] = qty;
            row[f"{prev} Status"] = "Green"
        row["Current Stage"] = entry
        _append_wo(m, row)
        wom = m["WO Master"]
        wom.at[sidx, f"{debit} OK"] = available - qty
        # reduce source WO commitment and note lineage
        old_t = int(_num(wom.at[sidx, "WO Good Target"]))
        wom.at[sidx, "WO Good Target"] = max(0, old_t - qty)
        prev = _str(wom.at[sidx, "Converted To"])
        wom.at[sidx, "Converted To"] = (prev + "; " if prev else "") + f"{cwo}({qty})"
        _recompute_wo(wom, sidx, yields)
        _recompute_wo(wom, wom.index[wom["WO ID"] == cwo][0], yields)
        # append to destination OAR's WO count
        m["OAR Register"].at[didx[0], "No. of WOs"] = int(_num(doar["No. of WOs"])) + 1
        # BUG1 FIX: use row Date field for conversion ledger
        conv_date = pd.to_datetime(r.get("Date"), errors="coerce", dayfirst=True)
        conv_entry_date = conv_date.date() if pd.notna(conv_date) else TODAY
        m["Conversion Ledger"].loc[len(m["Conversion Ledger"])] = [conv_entry_date, cwo, src,
                                                                   _str(wom.at[sidx, "OAR No"]), dest, partfrom, partto,
                                                                   qty, entry,
                                                                   _str(r.get("Reason")), _str(r.get("Planner"))]
        m["Conv Posted"].loc[len(m["Conv Posted"])] = [sig];
        posted.add(sig)
        audit(m, "CONVERT", cwo, field="from->to", old=src, new=cwo, source=ref,
              note=f"{qty} {partfrom}->{partto} @ {entry}; src target {old_t}->{old_t - qty}")


# ------------------------------------------------------------------ MRB
def process_mrb(m, path, yields):
    if not path or not os.path.exists(path):
        return
    df = _read_input_sheet(path, "Gate Update")
    wom = m["WO Master"]
    idx = {str(w): n for n, w in zip(wom.index, wom["WO ID"])}
    posted = set(m["MRB Posted"]["Signature"].astype(str))
    # PRE-SCAN (business rule): a WO is only ever physically at ONE stage. In a single day's
    # sheet, the same WO may appear more than once for the SAME stage (last row wins), but
    # appearing at TWO different stages is a data-entry error. Detect those WOs up front and
    # skip ALL their rows this run (flag as anomaly with the stages + sources), so a conflicting
    # sheet never corrupts the WO's stage picture. Same-stage repeats are allowed through.
    _wo_stages = {}
    for _, r in df.iterrows():
        w = _canon_wo(r.get("WO ID")); s = _canon_stage(r.get("Stage"))
        if w and s:
            _wo_stages.setdefault(w, set()).add(s)
    conflicted = {w: sorted(st) for w, st in _wo_stages.items() if len(st) > 1}
    for w, stg in conflicted.items():
        exception(m, "MRB: WO at multiple stages same day",
                  f"{w}: appears at stages {', '.join(stg)} in one sheet — a WO can only be at one "
                  f"stage; correct the sheet (check Source column) and re-run. All rows for this WO "
                  f"were skipped this cycle.", "Gate Update")
    for i, r in df.iterrows():
        wo = _canon_wo(r.get("WO ID"));
        stage = _canon_stage(r.get("Stage"));
        declared = _canon_wo_status(r.get("Stage Status"))
        ref = f"MRB row {_excel_row(df, i)}"
        if not wo and not stage:
            continue
        if wo in conflicted:
            continue          # skip every row of a multi-stage-conflicted WO (already flagged)
        # declared status is part of the row's identity: flipping In-Process -> Completed must
        # re-post even if the counts are unchanged, so it belongs in the idempotency signature.
        sig = "|".join([_str(r.get("Update Date")), wo, stage, str(int(_num(r.get("Produced OK Qty")))),
                        str(int(_num(r.get("Rejected Qty")))), _str(r.get("Defect Code")),
                        _str(r.get("NC Number")), _str(r.get("Invoice Number")), declared])
        if sig in posted:
            audit(m, "MRB_DUP_SKIP", wo, source=ref);
            continue
        if wo not in idx:
            exception(m, "Unknown WO", f"WO '{wo}' not in master ({stage})", ref);
            continue
        if stage not in ALL_STAGES:
            exception(m, "Bad stage", f"Stage '{stage}' for {wo}", ref);
            continue
        n = idx[wo]
        # WO RELEASE MANDATORY (warn-only phase): every WO should have a route defined via a
        # WO Release before production is logged against it. During backfill of the existing
        # routeless WOs, we WARN rather than block — the row is still processed (falling back to
        # the full plant sequence), but the WO is flagged so it can be released properly. Once
        # the backlog is routed, this can be promoted to a hard block.
        has_route = bool(_str(wom.at[n, "Route"])) if "Route" in wom.columns else False
        if not has_route:
            exception(m, "WO has no route (WO Release missing)",
                      f"{wo}: MRB data logged but this WO has no WO Release / route yet — "
                      f"processed against the default full sequence for now; please release it. "
                      f"(warn-only during route backfill)", ref)
        # v3: a WO only moves through its released route — a Gate Update against a stage
        # the WO is not designed to visit is a data error, not production.
        wroute = _wo_route(wom, n)
        if stage not in wroute:
            exception(m, "Stage not on WO route",
                      f"{wo}: stage '{stage}' not in route {' > '.join(wroute)}", ref)
            continue
        qty = int(_num(r.get("Produced OK Qty")))     # the movement quantity reported on this row
        rej = int(_num(r.get("Rejected Qty")))
        # v3.3 FLOW MOVEMENT SEMANTICS: each Gate Update row is that day's NEW movement (quantities
        # accumulate). The row's Stage Status decides which cumulative counter it feeds:
        #     In-Process               -> Entered (pieces put INTO process at this stage)
        #     Completed / blank(legacy) -> OK (pieces that CLEARED this stage, good)
        # Rejected always feeds the Rejected counter. From these three cumulative counters the
        # engine derives, in _recompute_wo, the live position of the parts:
        #     In-Process (net) = Entered - OK - Rej   (drops as pieces are completed/rejected)
        #     On-Hand          = OK - Entered(next)   (drops as the NEXT stage pulls pieces in)
        # OK stays cumulative (drives the RAG status). Idempotency means re-uploading the same file
        # never double-adds; a correction is a new row (negative qty) or the Stock Audit tool.
        prev_ok = int(_num(wom.at[n, f"{stage} OK"]))
        prev_ent = int(_num(wom.at[n, f"{stage} Ent"]))
        prev_rej = int(_num(wom.at[n, f"{stage} Rej"]))
        if declared == "In-Process":
            wom.at[n, f"{stage} Ent"] = prev_ent + qty        # pieces entered process at this stage
            ok_added = 0
        else:                                                 # Completed or legacy-blank -> cleared good
            wom.at[n, f"{stage} OK"] = prev_ok + qty
            ok_added = qty
        wom.at[n, f"{stage} Rej"] = prev_rej + rej
        # InProc / OnHand / Status are all recomputed from the counters in _recompute_wo below.
        ip_added = qty if declared == "In-Process" else 0
        audit(m, "MRB_POST", wo, field=f"{stage} Ent/OK/Rej",
              old=f"{prev_ent}/{prev_ok}/{prev_rej}",
              new=f"Ent+{ip_added}/OK+{ok_added}/Rej+{rej}", source=ref,
              note=f"declared={declared or 'n/a'}")
        m["MRB Posted"].loc[len(m["MRB Posted"])] = [sig];
        posted.add(sig)
        # BUG1 FIX: use row Update Date for accurate audit trail on late uploads
        row_date = pd.to_datetime(r.get("Update Date"), errors="coerce", dayfirst=True)
        entry_date = row_date.date() if pd.notna(row_date) else TODAY
        # Additive: the row's rejected qty IS the new movement -> log it straight to the ledger.
        if rej > 0:
            m["Disposition Ledger"].loc[len(m["Disposition Ledger"])] = [entry_date, wo,
                                                                         _str(wom.at[n, "OAR No"]),
                                                                         _str(wom.at[n, "Part No"]), stage,
                                                                         _str(r.get("Source")),
                                                                         _str(r.get("Subcon Name")),
                                                                         _str(r.get("Defect Code")), rej,
                                                                         _str(r.get("Disposition")),
                                                                         _str(r.get("NC Number"))]
        # A Completed movement at Dispatch is a real shipment of `ok_added` pieces this row.
        if stage == "Dispatch" and ok_added > 0:
            m["Dispatch Ledger"].loc[len(m["Dispatch Ledger"])] = [entry_date, wo,
                                                                   _str(wom.at[n, "OAR No"]),
                                                                   _str(wom.at[n, "Customer"]),
                                                                   _str(wom.at[n, "Customer PO Number"]),
                                                                   _str(wom.at[n, "Part No"]), ok_added,
                                                                   _str(r.get("Invoice Number")),
                                                                   _str(r.get("Invoice Date"))]
        _recompute_wo(wom, n, yields)
    for oi, oar in m["OAR Register"]["OAR No"].items():
        wos = wom[wom["OAR No"] == oar]
        if len(wos) and wos["Dispatch Status"].isin(DISPATCH_DONE).all():
            m["OAR Register"].at[oi, "Status"] = "Closed"


def migrate_ent_baseline(m):
    """ONE-TIME cutover step for a master built before v3.3 (no '{stage} Ent' column, or Ent
    sitting at 0 while InProc/OK/Rej already carry real history). Per the Baseline work
    instruction's Fed formula (Fed = In-Process + Completed + Rejected), back-derive each
    stage's Ent baseline from what the master already recorded, so no existing WIP is lost.
    Run this ONCE against a pre-v3.3 master before its first v3.3 cycle -- never on every
    cycle, and never on a master that already has real Ent history (it only touches a
    stage's Ent when Ent is 0 there, so re-running it after go-live is a safe no-op, but it
    should still only be a deliberate, logged step, not a silent part of every run).
    Returns the number of (WO, stage) cells backfilled, for the audit trail.
    """
    wom = m["WO Master"]
    backfilled = 0
    for n in wom.index:
        for s in ALL_STAGES:
            ent_col = f"{s} Ent"
            cur_ent = int(_num(wom.at[n, ent_col])) if ent_col in wom.columns else 0
            if cur_ent != 0:
                continue  # already has a real baseline -- never overwrite
            ip = int(_num(wom.at[n, f"{s} InProc"])) if f"{s} InProc" in wom.columns else 0
            ok = int(_num(wom.at[n, f"{s} OK"])) if f"{s} OK" in wom.columns else 0
            rej = int(_num(wom.at[n, f"{s} Rej"])) if f"{s} Rej" in wom.columns else 0
            fed = ip + ok + rej
            if fed > 0:
                wom.at[n, ent_col] = fed
                backfilled += 1
    if backfilled:
        audit(m, "ENT_BASELINE_MIGRATION", "WO Master", field="{stage} Ent",
              new=f"backfilled {backfilled} stage-cells from Fed=InProc+OK+Rej",
              note="one-time pre-v3.3 cutover -- see migrate_ent_baseline()")
    return backfilled


def _recompute_wo(wom, n, yields):
    # v3: everything walks the WO's OWN route, not the full plant sequence.
    route = _wo_route(wom, n)
    prod = [s for s in route if s != "Dispatch"]
    # v3.3 FLOW POSITION: derive the live In-Process (net) and On-Hand from the cumulative
    # counters, and set each stage's RAG status. Walk the route so 'next stage' is route-aware.
    for i, s in enumerate(route):
        ent = int(_num(wom.at[n, f"{s} Ent"]))
        ok = int(_num(wom.at[n, f"{s} OK"]))
        rej = int(_num(wom.at[n, f"{s} Rej"]))
        tgt = int(_num(wom.at[n, f"{s} Target"]))
        net_ip = max(ent - ok - rej, 0)                     # in process now (drops as completed/rej)
        nxt_ent = int(_num(wom.at[n, f"{route[i + 1]} Ent"])) if i + 1 < len(route) else 0
        on_hand = max(ok - nxt_ent, 0)                      # cleared here, not yet pulled to next
        wom.at[n, f"{s} InProc"] = net_ip
        wom.at[n, f"{s} OnHand"] = on_hand
        if _str(wom.at[n, f"{s} Status"]) != "Converted-in":
            wom.at[n, f"{s} Status"] = _rag_status(ok, rej, net_ip, tgt)
    # SNAPSHOT BUSINESS RULE: the presence of data at a stage means the product physically
    # reached that stage. A stage's target is only the PLAN — actual = target minus rejections,
    # which is normal, not a blocker. So "Current Stage" is the FURTHEST stage along the route
    # that has any data entered (OK or Rej), not "the first stage that hasn't hit its target".
    # If every stage including Dispatch has data and Dispatch is done, the WO is Completed.
    def _has_data(s):
        return int(_num(wom.at[n, f"{s} OK"])) > 0 or int(_num(wom.at[n, f"{s} Rej"])) > 0 \
            or int(_num(wom.at[n, f"{s} InProc"])) > 0 \
            or _str(wom.at[n, f"{s} Status"]) in STAGE_DONE
    furthest = None
    for s in route:
        if _has_data(s):
            furthest = s
    if furthest is None:
        cur = route[0] if route else "F1"          # nothing entered yet -> sits at route start
    elif furthest == route[-1] and _str(wom.at[n, f"{furthest} Status"]) in DISPATCH_DONE:
        cur = "Completed"                            # reached & cleared the final (Dispatch) stage
    else:
        cur = furthest                               # product is at its furthest data-bearing stage
    wom.at[n, "Current Stage"] = cur
    good = int(_num(wom.at[n, "WO Good Target"]))
    proj = good;
    last = None
    for s in prod:
        if int(_num(wom.at[n, f"{s} OK"])) > 0:
            last = s
    if last is not None:
        proj = int(_num(wom.at[n, f"{last} OK"]))
        for s in prod[prod.index(last) + 1:]:
            proj *= yields.get(s, 1.0)
        proj = int(math.floor(proj))
    wom.at[n, "Projected Final Good"] = proj
    # v3.1: flag a shortfall when the projection falls short OR when the WO's FURTHEST reached
    # stage was short-closed by the floor. We check only the furthest stage (not any historical
    # one): an early stage finishing below its interim plan isn't a shortfall if later stages
    # recovered — the projection off the latest stage already reflects that. But a short-close
    # at the current front (incl. a short Dispatch) is a real, floor-declared shortfall.
    short_closed = furthest is not None and _str(wom.at[n, f"{furthest} Status"]) in ("Amber", "Red")
    wom.at[n, "Shortfall"] = "YES" if (proj < good or short_closed) else "No"
    # Production is complete once the LAST production stage on the route has data entered
    # (snapshot rule: data at a stage = product reached it). Then the WO is Ready (awaiting/
    # mid Dispatch) until Dispatch itself is done, at which point it's Dispatched.
    last_prod = prod[-1] if prod else None
    prod_last_has_data = last_prod is not None and (
        int(_num(wom.at[n, f"{last_prod} OK"])) > 0
        or int(_num(wom.at[n, f"{last_prod} Rej"])) > 0
        or _str(wom.at[n, f"{last_prod} Status"]) in STAGE_DONE)
    production_done = cur in ("Dispatch", "Completed") or prod_last_has_data
    if _str(wom.at[n, "Dispatch Status"]) in DISPATCH_DONE:
        wom.at[n, "Overall Status"] = "Dispatched"
    elif production_done:
        wom.at[n, "Overall Status"] = "Ready"
    else:
        wom.at[n, "Overall Status"] = "In-Progress"


# ------------------------------------------------------------------ WO Release
# Meta columns of the WO Release sheet; EVERY other column is a stage column and the
# template's left-to-right column order IS the route sequence. Adding a brand-new stage
# column in the template auto-registers the stage plant-wide.
WOR_META = {"Release Date", "WO ID", "Conversion WO", "Part No", "Physical WO Qty",
            "Released By", "Remarks"}


def _wor_conv_route(wor_path, cname):
    """Look up a conversion WO's released route from the WO Release sheet's 'Conversion WO'
    column. Returns (prod_route_list, physical_qty) or (None, None) if no matching row.
    A conversion-release row has WO ID blank and the Conversion WO name filled; its Yes/No
    stage marks (in template column order) define the route the conversion WO will follow."""
    if not wor_path or not os.path.exists(wor_path) or not cname:
        return None, None
    try:
        df = _read_input_sheet(wor_path, "WO Release")
    except Exception:
        return None, None
    if "Conversion WO" not in df.columns:
        return None, None
    stage_cols = [c for c in df.columns if c not in WOR_META
                  and not str(c).lower().startswith("unnamed")]
    for _, r in df.iterrows():
        if _canon_wo(r.get("Conversion WO")) != cname:
            continue
        seen = []
        for c in stage_cols:
            canon = _canon_stage(c)
            if _str(r.get(c)).lower() in _YES and canon != "Dispatch" and canon not in seen:
                seen.append(canon)
        q = int(_num(r.get("Physical WO Qty")))
        return (seen or None), (q if q > 0 else None)
    return None, None
_YES = {"yes", "y", "1", "true", "x"}


def process_wor(m, path, yields):
    """Apply WO Release rows: per-WO route (Yes/No per stage column) + physical WO qty
    (overrides WO Good Target; targets re-back-calculated over the route only)."""
    if not path or not os.path.exists(path):
        return
    df = _read_input_sheet(path, "WO Release")
    stage_cols = [c for c in df.columns if c not in WOR_META
                  and not str(c).lower().startswith("unnamed")]
    # register any brand-new stage, positioned after its left neighbour in the template
    prev_known = None
    for c in stage_cols:
        canon = _canon_stage(c)
        if canon in ALL_STAGES:
            prev_known = canon
            continue
        register_stage(m, _str(c), after=prev_known, source=f"WO Release {os.path.basename(path)}")
        prev_known = _str(c)
    stage_cols_canon = [(c, _canon_stage(c)) for c in stage_cols]

    wom = m["WO Master"]
    idx = {str(w): n for n, w in zip(wom.index, wom["WO ID"])}
    posted = set(m["WOR Posted"]["Signature"].astype(str))
    for i, r in df.iterrows():
        wo = _canon_wo(r.get("WO ID"))
        ref = f"WOR row {_excel_row(df, i)}"
        if not wo:
            continue
        qty = int(_num(r.get("Physical WO Qty")))
        marks = {canon: _str(r.get(col)).lower() for col, canon in stage_cols_canon}
        route_prod = [canon for col, canon in stage_cols_canon
                      if marks.get(canon, "") in _YES and canon != "Dispatch"]
        sig = "|".join([_str(r.get("Release Date")), wo, str(qty)] + route_prod)
        if sig in posted:
            audit(m, "WOR_DUP_SKIP", wo, source=ref)
            continue
        if wo not in idx:
            exception(m, "WO Release: unknown WO", f"WO '{wo}' not in master", ref)
            continue
        if qty <= 0:
            exception(m, "WO Release: bad qty", f"{wo}: Physical WO Qty={qty}", ref)
            continue
        if not route_prod:
            exception(m, "WO Release: empty route", f"{wo}: no stage marked Yes", ref)
            continue
        n = idx[wo]
        route = route_prod + ["Dispatch"]
        # cannot remove a stage that already has production booked against it
        booked_off_route = [s for s in ALL_STAGES if s not in route
                            and (int(_num(wom.at[n, f"{s} OK"])) > 0
                                 or int(_num(wom.at[n, f"{s} Rej"])) > 0)]
        if booked_off_route:
            exception(m, "WO Release: stage with production removed from route",
                      f"{wo}: {', '.join(booked_off_route)} already has OK/Rej booked — "
                      f"release skipped, correct the route or raise a conversion", ref)
            continue
        old_target = int(_num(wom.at[n, "WO Good Target"]))
        old_route = _str(wom.at[n, "Route"])
        wom.at[n, "Route"] = " > ".join(route)
        wom.at[n, "Released Qty"] = qty
        wom.at[n, "Release Date"] = _str(r.get("Release Date")) or str(TODAY)
        wom.at[n, "Released By"] = _str(r.get("Released By"))
        wom.at[n, "WO Good Target"] = qty  # physical WO qty overrides the split PO target
        t = stage_targets(qty, yields, route)
        for s in ALL_STAGES:
            if s in route:
                wom.at[n, f"{s} Target"] = t.get(s, 0)
                if _str(wom.at[n, f"{s} Status"]) != "Converted-in":
                    wom.at[n, f"{s} Status"] = _rag_status(
                        wom.at[n, f"{s} OK"], wom.at[n, f"{s} Rej"],
                        wom.at[n, f"{s} InProc"], t.get(s, 0))
            else:
                wom.at[n, f"{s} Target"] = 0
                wom.at[n, f"{s} Status"] = "Skip"
        _recompute_wo(wom, n, yields)
        m["WOR Posted"].loc[len(m["WOR Posted"])] = [sig]
        posted.add(sig)
        audit(m, "WOR_APPLY", wo, field="Route/Qty",
              old=f"{old_route or 'full'} / target {old_target}",
              new=f"{' > '.join(route)} / qty {qty}", source=ref)


# ------------------------------------------------------------------ NC tracker
def process_nc(m, path):
    if not path or not os.path.exists(path):
        return
    df = _read_input_sheet(path, "NC Tracker")
    reg = m["NC Register"]
    pos = {str(v): i for i, v in reg["NC Number"].items()}
    for i, r in df.iterrows():
        nc = _str(r.get("NC Number"));
        ref = f"NC row {_excel_row(df, i)}"
        if not nc:
            continue
        # BUG3 FIX: if status is Closed but Date Closed is missing, flag as exception
        nc_status = _str(r.get("NC Status")) or "Open"
        date_closed = r.get("Date Closed")
        if nc_status.lower() == "closed" and (pd.isna(date_closed) or _str(date_closed) == ""):
            exception(m, "NC closure missing Date Closed",
                      f"NC {nc} marked Closed but Date Closed is blank — status kept Open", ref)
            nc_status = "Open"  # revert to Open until Date Closed is provided
            date_closed = None
        vals = {"NC Number": nc, "WO ID": _canon_wo(r.get("WO ID")), "OAR No": _str(r.get("OAR No")),
                "Part No": _str(r.get("Part No")), "Stage": _str(r.get("Stage")),
                "Defect Code": _str(r.get("Defect Code")), "Qty": _num(r.get("Qty")),
                "NC Status": nc_status,
                "Date Raised": r.get("Date Raised"), "Date Closed": date_closed,
                "Days Open": _days(r.get("Date Raised"), r.get("Date Closed")),
                "Responsibility": _str(r.get("Responsibility")),
                "Disposition": _str(r.get("Disposition")), "Remarks": _str(r.get("Remarks"))}
        if nc in pos:
            for k, v in vals.items():
                reg.at[pos[nc], k] = v
            audit(m, "NC_UPDATE", nc, new=vals["NC Status"], source=ref)
        else:
            reg.loc[len(reg)] = [vals[c] for c in MASTER_SHEETS["NC Register"]]
            pos[nc] = len(reg) - 1
            audit(m, "NC_NEW", nc, new=vals["NC Status"], source=ref)


# ------------------------------------------------------------------ reports
def _record_trend(m, dash_stats):
    """Upsert today's KPI snapshot into the Trend History sheet (in-memory on m).
    Same-day re-runs (e.g. catch-up) overwrite today's row rather than duplicating it."""
    row = {
        "Date": dash_stats["date"],
        "Total WOs": dash_stats["total_wos"],
        "Shortfalls": dash_stats["shortfalls"],
        "Open NCs": dash_stats["open_nc"],
        "Open NCs Aged 7d+": dash_stats["open_nc_aged7"],
        "Dispatched": dash_stats["dispatched"],
        "OARs": dash_stats["oars"],
        "Conversions": dash_stats["conversions"],
        "Overdue WOs": dash_stats["overdue_wos"],
        "Overall Reject %": dash_stats["overall_reject_pct"],
    }
    hist = m["Trend History"]
    hist = hist[hist["Date"] != dash_stats["date"]]  # drop any existing row for today
    hist = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
    hist = hist.sort_values("Date").reset_index(drop=True)
    hist = hist.tail(60).reset_index(drop=True)  # keep last 60 days max
    m["Trend History"] = hist
    return hist


def _trend_prev_row(hist):
    """Return the row before today's, for a day-over-day delta on the Dashboard (or None)."""
    if len(hist) < 2:
        return None
    return hist.iloc[-2].to_dict()


def build_reports(m, outdir, yields, ynote, anomaly_count=0, total_input_rows=0, cycle=None):
    cycle = cycle or {}
    wom = m["WO Master"].copy()
    open_wo = wom[~wom["Overall Status"].map(_is_terminal_status)]
    closed_legacy = wom[wom["Overall Status"].astype(str).str.upper().str.startswith("CLOSED")]

    status = open_wo[["WO ID", "OAR No", "Customer", "Part No", "WO Good Target", "Current Stage",
                      "Projected Final Good", "Shortfall", "Cust Delivery Date", "Overall Status",
                      "Converted From"]].copy()
    status["Delivery Risk"] = [
        _delivery_risk(w.get("Cust Delivery Date"), w.get("Current Stage"),
                       w.get("Overall Status"), _route_of_row(w))
        for _, w in open_wo.iterrows()
    ]

    # rejection — by stage / by WO+NC / by defect
    rej_stage = pd.DataFrame([{"Stage": s,
                               "Total OK": int(pd.to_numeric(wom.get(f"{s} OK"), errors="coerce").fillna(0).sum()),
                               "Total Rejected": int(
                                   pd.to_numeric(wom.get(f"{s} Rej"), errors="coerce").fillna(0).sum())}
                              for s in ALL_STAGES])
    denom = (rej_stage["Total OK"] + rej_stage["Total Rejected"]).astype(float)
    rej_stage["Reject %"] = [round(100 * rj / d, 1) if d else 0.0
                             for rj, d in zip(rej_stage["Total Rejected"], denom)]
    led = m["Disposition Ledger"].copy()
    ncreg = m["NC Register"].set_index("NC Number") if len(m["NC Register"]) else None
    if len(led):
        led["NC Status"] = led["NC Number"].map(
            lambda x: _str(ncreg.at[x, "NC Status"]) if (
                        ncreg is not None and x in ncreg.index) else "Open (not tracked)")
        led["Days Open"] = led["NC Number"].map(
            lambda x: ncreg.at[x, "Days Open"] if (ncreg is not None and x in ncreg.index) else "")
    rej_wo = led[["Date", "WO ID", "OAR No", "Part No", "Stage", "Defect Code", "Rejected Qty",
                  "Disposition", "NC Number", "NC Status", "Days Open"]] if len(led) else \
        pd.DataFrame(columns=["Date", "WO ID", "OAR No", "Part No", "Stage", "Defect Code",
                              "Rejected Qty", "Disposition", "NC Number", "NC Status", "Days Open"])
    rej_defect = (led.groupby("Defect Code")["Rejected Qty"].sum().reset_index()
                  .sort_values("Rejected Qty", ascending=False)) if len(led) else \
        pd.DataFrame(columns=["Defect Code", "Rejected Qty"])

    # inventory — v3: PER-WO, ROUTE-AWARE, PHYSICALLY AUDITABLE.
    # For each WO, walking ITS OWN route:  WIP after S = OK(S) - (OK(next) + Rej(next)).
    # Pieces rejected at the next gate were consumed from S's output (the old OK-OK formula
    # counted them as still sitting at S). Stage totals are the SUM of per-WO figures
    # (bottom-up — a plant-wide aggregate can go negative and clamp silently; this can't).
    # Negative per-WO gaps mean bad data (out-of-order gate entries) -> Exceptions, not 0.
    audit_rows = []          # one row per WO per stage holding WIP  -> 3c audit sheet
    stage_prod, stage_cons, stage_wip = ({s: 0 for s in PROD_STAGES} for _ in range(3))
    wip_by_wo = {}           # WO ID -> {stage: qty}
    for _, w in open_wo.iterrows():
        route = _route_of_row(w)
        for k, s in enumerate(route[:-1]):
            nxt = route[k + 1]
            ok = int(_num(w.get(f"{s} OK", 0)))
            nok = int(_num(w.get(f"{nxt} OK", 0)))
            nrej = int(_num(w.get(f"{nxt} Rej", 0)))
            held = ok - (nok + nrej)
            if s in stage_prod:
                stage_prod[s] += ok
                stage_cons[s] += (nok + nrej)
            if held > 0:
                stage_wip[s] = stage_wip.get(s, 0) + held
                wip_by_wo.setdefault(str(w["WO ID"]), {})[s] = held
                audit_rows.append({"Stage": s, "WO ID": w["WO ID"], "OAR No": w["OAR No"],
                                   "Part No": w["Part No"],
                                   "Route": " > ".join(route),
                                   "OK at Stage": ok, "Next Stage": nxt,
                                   "Consumed by Next (OK+Rej)": nok + nrej,
                                   "WIP Qty (Book)": held,
                                   "Physical Count": "", "Variance": ""})
            elif held < 0:
                exception(m, "WIP negative at stage",
                          f"{w['WO ID']}: {nxt} consumed {nok + nrej} but {s} only produced "
                          f"{ok} — out-of-order Gate Update or missing entry at {s}")
    inv_stage = pd.DataFrame([{"After Stage": s, "Good Produced": stage_prod[s],
                               "Consumed by Next (OK+Rej)": stage_cons[s],
                               "WIP On-hand": stage_wip.get(s, 0)} for s in PROD_STAGES])
    inv_wo = []
    for _, w in open_wo.iterrows():
        row = {"WO ID": w["WO ID"], "OAR No": w["OAR No"], "Part No": w["Part No"],
               "Route": " > ".join(_route_of_row(w))}
        for s in PROD_STAGES:
            row[f"{s} OK"] = int(_num(w.get(f"{s} OK", 0)))
        d = wip_by_wo.get(str(w["WO ID"]), {})
        row["WIP Detail"] = "; ".join(f"{s}:{q}" for s, q in d.items())
        row["WIP Total"] = sum(d.values())
        inv_wo.append(row)
    inv_wo = pd.DataFrame(inv_wo)
    if audit_rows:
        inv_audit = pd.DataFrame(audit_rows)
        inv_audit["__ord"] = inv_audit["Stage"].map(
            lambda v: PROD_STAGES.index(v) if v in PROD_STAGES else 999)
        inv_audit = (inv_audit.sort_values(["__ord", "WO ID"])
                     .drop(columns="__ord").reset_index(drop=True))
    else:
        inv_audit = pd.DataFrame(columns=["Stage", "WO ID", "OAR No", "Part No", "Route",
                                          "OK at Stage", "Next Stage",
                                          "Consumed by Next (OK+Rej)", "WIP Qty (Book)",
                                          "Physical Count", "Variance"])

    # NC register report
    ncrep = m["NC Register"][["NC Number", "WO ID", "Part No", "Stage", "Defect Code", "Qty",
                              "NC Status", "Date Raised", "Date Closed", "Days Open",
                              "Responsibility"]].copy() if len(m["NC Register"]) else \
        pd.DataFrame(columns=["NC Number", "WO ID", "Part No", "Stage", "NC Status", "Days Open"])

    # PO -> Invoice traceability: every accepted PO down to its invoices
    disp = m["Dispatch Ledger"]
    trace = []
    for _, o in m["OAR Register"].iterrows():
        wl = wom[wom["OAR No"] == o["OAR No"]]
        for _, w in wl.iterrows():
            dl = disp[disp["WO ID"] == w["WO ID"]] if len(disp) else disp
            if len(dl):
                for _, d in dl.iterrows():
                    trace.append({"Customer PO": o["Customer PO Number"], "OAR No": o["OAR No"],
                                  "Customer": o["Customer"], "WO ID": w["WO ID"], "Part No": w["Part No"],
                                  "WO Target": w["WO Good Target"], "Dispatched Qty": d["Dispatched Qty"],
                                  "Invoice No": d["Invoice No"], "Invoice Date": d["Invoice Date"],
                                  "WO Status": w["Overall Status"]})
            else:
                trace.append({"Customer PO": o["Customer PO Number"], "OAR No": o["OAR No"],
                              "Customer": o["Customer"], "WO ID": w["WO ID"], "Part No": w["Part No"],
                              "WO Target": w["WO Good Target"], "Dispatched Qty": "", "Invoice No": "",
                              "Invoice Date": "", "WO Status": w["Overall Status"]})
    trace = pd.DataFrame(trace) if trace else pd.DataFrame(
        columns=["Customer PO", "OAR No", "Customer", "WO ID", "Part No", "WO Target",
                 "Dispatched Qty", "Invoice No", "Invoice Date", "WO Status"])

    open_nc = int((m["NC Register"]["NC Status"].astype(str).str.lower() == "open").sum()) if len(
        m["NC Register"]) else 0

    # ── Dashboard stats (used to build the executive Dashboard tab) ──────────
    ncreg_all = m["NC Register"]
    open_nc_aged7 = 0
    if len(ncreg_all):
        st = ncreg_all["NC Status"].astype(str).str.lower()
        days = pd.to_numeric(ncreg_all.get("Days Open"), errors="coerce").fillna(0)
        open_nc_aged7 = int(((st == "open") & (days >= 7)).sum())

    top_defect = None
    if len(rej_defect):
        rd = rej_defect.iloc[0]
        if _num(rd["Rejected Qty"]) > 0:
            top_defect = (str(rd["Defect Code"]), int(_num(rd["Rejected Qty"])))

    top_reject_stage = None
    if len(rej_stage):
        rs = rej_stage.sort_values("Reject %", ascending=False).iloc[0]
        if float(rs["Reject %"]) > 0:
            top_reject_stage = (str(rs["Stage"]), float(rs["Reject %"]))

    risk_wos = list(status.loc[status["Delivery Risk"].isin(["OVERDUE", "HIGH RISK"]), "WO ID"]) \
        if len(status) else []
    overdue_wos = int((status["Delivery Risk"] == "OVERDUE").sum()) if len(status) else 0

    total_ok = int(rej_stage["Total OK"].sum()) if len(rej_stage) else 0
    total_rej = int(rej_stage["Total Rejected"].sum()) if len(rej_stage) else 0
    overall_reject_pct = round(100 * total_rej / (total_ok + total_rej), 1) if (total_ok + total_rej) else 0.0

    # Today's activity comes entirely from the `cycle` before/after diff computed in run()
    # (see _cycle_snapshot/_cycle_diff) -- a row's own Update Date can be backdated for a
    # catch-up entry, so counting by date would under-report; diffing what the master
    # actually gained this run is exact regardless of what dates are typed into the rows.
    new_wos_today = cycle.get("wos_created", 0)
    new_ncs_today = cycle.get("nc_opened", 0)

    # Anomaly-rate materiality: what fraction of today's Intake/Gate Update/Conversions/NC
    # rows were skipped. A clean-looking "Run completed" Notice can hide a day where most
    # rows failed (e.g. wrong --master passed) -- this makes that visible on the Dashboard
    # itself rather than requiring someone to open the Anomalies tab.
    anomaly_rate = round(100 * anomaly_count / total_input_rows, 1) if total_input_rows else 0.0

    dash_stats = {
        "date": str(TODAY),
        "total_wos": int(len(wom)),
        "shortfalls": int((open_wo["Shortfall"] == "YES").sum()) if len(open_wo) else 0,
        "open_nc": open_nc,
        "open_nc_aged7": open_nc_aged7,
        "dispatched": int((wom["Overall Status"] == "Dispatched").sum()) if len(wom) else 0,
        "closed_legacy": int(len(closed_legacy)),
        "oars": int(len(m["OAR Register"])),
        "conversions": int(len(m["Conversion Ledger"])),
        "new_wos_today": new_wos_today,
        "new_ncs_today": new_ncs_today,
        "anomaly_count": anomaly_count,
        "total_input_rows": total_input_rows,
        "anomaly_rate": anomaly_rate,
        "cycle": cycle,
        "top_defect": top_defect,
        "top_reject_stage": top_reject_stage,
        "risk_wos": risk_wos,
        "overdue_wos": overdue_wos,
        "overall_reject_pct": overall_reject_pct,
    }

    trend = _record_trend(m, dash_stats)
    dash_stats["trend_prev"] = _trend_prev_row(trend)

    # WO Stage Tracking — per WO, per route stage: Planned / OK Completed / In-Process / Rejected
    # / Status. One row per WO×stage, mirroring the four quantity buckets held in the master.
    _track_cols = ["WO ID", "OAR No", "Part No", "Stage", "Planned Qty", "OK Completed Qty",
                   "In-Process Qty", "On-Hand Qty", "Rejected Qty", "Stage Status"]
    track_rows = []
    for _, w in open_wo.iterrows():
        for s in _route_of_row(w):
            track_rows.append({"WO ID": w["WO ID"], "OAR No": w["OAR No"], "Part No": w["Part No"],
                               "Stage": s, "Planned Qty": int(_num(w.get(f"{s} Target", 0))),
                               "OK Completed Qty": int(_num(w.get(f"{s} OK", 0))),
                               "In-Process Qty": int(_num(w.get(f"{s} InProc", 0))),
                               "On-Hand Qty": int(_num(w.get(f"{s} OnHand", 0))),
                               "Rejected Qty": int(_num(w.get(f"{s} Rej", 0))),
                               "Stage Status": _str(w.get(f"{s} Status", ""))})
    wo_track = pd.DataFrame(track_rows, columns=_track_cols) if track_rows \
        else pd.DataFrame(columns=_track_cols)

    path = os.path.join(outdir, f"Daily_Report_{TODAY}.xlsx")
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        anomaly_line = (f"Anomaly rate: {anomaly_rate:.1f}% ({anomaly_count} of {total_input_rows} "
                        f"input rows skipped)" + (" — HIGH, verify master before trusting this report"
                        if anomaly_rate >= 10 else ""))
        pd.DataFrame({"Vijay Spheroidals — Daily Order Management Report": [
            f"Date: {TODAY}", f"Open work orders: {len(open_wo)}",
            "--- TODAY'S CYCLE (this run only) ---",
            f"Orders accepted: {cycle.get('oars_created', 0)} OAR(s), {new_wos_today} WO(s) created",
            f"Held / rejected at intake: {cycle.get('held_at_intake', 0)} held, "
            f"{cycle.get('rejected_at_intake', 0)} rejected",
            f"Production posted: {cycle.get('ok_produced', 0)} good, "
            f"{cycle.get('rejected_qty', 0)} rejected (pcs)",
            f"Conversions: {cycle.get('conversions_done', 0)} conversion(s), "
            f"{cycle.get('conversion_qty', 0)} pcs moved"
            + (f" — {cycle.get('conversions_blocked', 0)} blocked (see Dashboard/Exceptions)"
               if cycle.get('conversions_blocked', 0) else ""),
            f"Dispatched: {cycle.get('dispatched_wos', 0)} WO(s), {cycle.get('dispatched_qty', 0)} pcs",
            f"NCs: {new_ncs_today} opened, {cycle.get('nc_closed', 0)} closed",
            "--- LIVE TOTALS (all-time) ---",
            f"Shortfall-flagged WOs: {(open_wo['Shortfall'] == 'YES').sum()}",
            f"Open NCs: {open_nc}", f"Conversions to date: {len(m['Conversion Ledger'])}",
            f"OARs: {len(m['OAR Register'])} | WOs: {len(wom)}",
            f"Legacy closed (excluded from Open/Shortfall/Risk): {len(closed_legacy)}",
            anomaly_line,
            f"Yields used: {ynote}"]}).to_excel(xw, sheet_name="Summary", index=False)
        status.to_excel(xw, sheet_name="1 Status", index=False)
        wo_track.to_excel(xw, sheet_name="1b WO Stage Tracking", index=False)
        rej_stage.to_excel(xw, sheet_name="2a Rejection by Stage", index=False)
        rej_wo.to_excel(xw, sheet_name="2b Rejection WO+NC", index=False)
        rej_defect.to_excel(xw, sheet_name="2c Rejection by Defect", index=False)
        inv_stage.to_excel(xw, sheet_name="3a Inventory by Stage", index=False)
        inv_wo.to_excel(xw, sheet_name="3b Inventory WO+Part", index=False)
        inv_audit.to_excel(xw, sheet_name="3c Stage Audit Sheet", index=False)
        ncrep.to_excel(xw, sheet_name="4 NC Register", index=False)
        trace.to_excel(xw, sheet_name="5 PO to Invoice", index=False)
        trend.tail(14).to_excel(xw, sheet_name="6 Trend", index=False)
    _style(path, dash_stats)
    return path, len(open_wo), int((open_wo["Shortfall"] == "YES").sum()), open_nc


# ── Color fills ──────────────────────────────────────────────────────────────
RED_CLR = "C00000";
AMBER_CLR = "BF8F00";
GREEN_CLR = "548235";
BLUE_CLR = "2E5496"
RED_FILL = PatternFill("solid", fgColor="FFCCCC")
AMBER_FILL = PatternFill("solid", fgColor="FFE699")
GREEN_FILL = PatternFill("solid", fgColor="C6EFCE")
RED_FONT = Font(name="Arial", size=10, color="9C0006")
AMBER_FONT = Font(name="Arial", size=10, color="7F6000")
GREEN_FONT = Font(name="Arial", size=10, color="276221")
BOLD_RED = Font(name="Arial", size=10, bold=True, color="9C0006")


def _color_cell(cell, fill, font):
    cell.fill = fill;
    cell.font = font


def _color_reports(wb):
    """Apply red/amber/green color coding across all report tabs."""

    # ── 1b WO Stage Tracking tab: colour the Stage Status column by its RAG value ─────
    wst = wb["1b WO Stage Tracking"] if "1b WO Stage Tracking" in wb.sheetnames else None
    if wst:
        hdrs = {wst.cell(1, c).value: c for c in range(1, wst.max_column + 1)}
        sc = hdrs.get("Stage Status")
        if sc:
            for r in range(2, wst.max_row + 1):
                v = str(wst.cell(r, sc).value)
                if v == "Red":
                    _color_cell(wst.cell(r, sc), RED_FILL, RED_FONT)
                elif v == "Amber":
                    _color_cell(wst.cell(r, sc), AMBER_FILL, AMBER_FONT)
                elif v == "Green":
                    _color_cell(wst.cell(r, sc), GREEN_FILL, GREEN_FONT)

    # ── 1 Status tab ─────────────────────────────────────────────────────────
    ws = wb["1 Status"] if "1 Status" in wb.sheetnames else None
    if ws:
        # Find column indices from header row
        headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
        shortfall_col = headers.get("Shortfall")
        status_col = headers.get("Overall Status")
        proj_col = headers.get("Projected Final Good")
        tgt_col = headers.get("WO Good Target")
        risk_col = headers.get("Delivery Risk")
        for r in range(2, ws.max_row + 1):
            shortfall = str(ws.cell(r, shortfall_col).value).upper() if shortfall_col else ""
            status = str(ws.cell(r, status_col).value) if status_col else ""
            for c in range(1, ws.max_column + 1):
                cell = ws.cell(r, c)
                if not cell.value:
                    continue
                if shortfall == "YES":
                    _color_cell(cell, RED_FILL, RED_FONT)
                elif status == "Dispatched":
                    _color_cell(cell, GREEN_FILL, GREEN_FONT)
                elif status == "In-Progress":
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
            # Delivery Risk column always gets its own color, regardless of the row-wide rule above
            if risk_col:
                risk = str(ws.cell(r, risk_col).value)
                rcell = ws.cell(r, risk_col)
                if risk in ("OVERDUE", "HIGH RISK"):
                    _color_cell(rcell, RED_FILL, BOLD_RED)
                elif risk == "AT RISK":
                    _color_cell(rcell, AMBER_FILL, AMBER_FONT)
                elif risk == "On Track":
                    _color_cell(rcell, GREEN_FILL, GREEN_FONT)

    # ── 2a Rejection by Stage ─────────────────────────────────────────────────
    ws2a = wb["2a Rejection by Stage"] if "2a Rejection by Stage" in wb.sheetnames else None
    if ws2a:
        headers = {ws2a.cell(1, c).value: c for c in range(1, ws2a.max_column + 1)}
        pct_col = headers.get("Reject %")
        for r in range(2, ws2a.max_row + 1):
            pct = ws2a.cell(r, pct_col).value if pct_col else 0
            try:
                pct = float(pct)
            except:
                pct = 0
            for c in range(1, ws2a.max_column + 1):
                cell = ws2a.cell(r, c)
                if not cell.value and cell.value != 0:
                    continue
                if pct >= 10:
                    _color_cell(cell, RED_FILL, RED_FONT)
                elif pct >= 5:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
                else:
                    _color_cell(cell, GREEN_FILL, GREEN_FONT)

    # ── 2b Rejection WO+NC ────────────────────────────────────────────────────
    ws2b = wb["2b Rejection WO+NC"] if "2b Rejection WO+NC" in wb.sheetnames else None
    if ws2b and ws2b.max_row > 1:
        headers = {ws2b.cell(1, c).value: c for c in range(1, ws2b.max_column + 1)}
        nc_status_col = headers.get("NC Status")
        days_col = headers.get("Days Open")
        for r in range(2, ws2b.max_row + 1):
            nc_status = str(ws2b.cell(r, nc_status_col).value) if nc_status_col else ""
            days = ws2b.cell(r, days_col).value if days_col else 0
            try:
                days = int(days)
            except:
                days = 0
            for c in range(1, ws2b.max_column + 1):
                cell = ws2b.cell(r, c)
                if not cell.value and cell.value != 0:
                    continue
                if nc_status.lower() == "open" and days >= 7:
                    _color_cell(cell, RED_FILL, RED_FONT)
                elif nc_status.lower() == "open" and days >= 3:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
                elif nc_status.lower() == "closed":
                    _color_cell(cell, GREEN_FILL, GREEN_FONT)

    # ── 2c Rejection by Defect ────────────────────────────────────────────────
    ws2c = wb["2c Rejection by Defect"] if "2c Rejection by Defect" in wb.sheetnames else None
    if ws2c and ws2c.max_row > 1:
        headers = {ws2c.cell(1, c).value: c for c in range(1, ws2c.max_column + 1)}
        qty_col = headers.get("Rejected Qty")
        # Find max for relative coloring
        qtys = []
        for r in range(2, ws2c.max_row + 1):
            try:
                qtys.append(float(ws2c.cell(r, qty_col).value or 0))
            except:
                qtys.append(0)
        max_qty = max(qtys) if qtys else 1
        for i, r in enumerate(range(2, ws2c.max_row + 1)):
            qty = qtys[i]
            for c in range(1, ws2c.max_column + 1):
                cell = ws2c.cell(r, c)
                if not cell.value and cell.value != 0:
                    continue
                if qty >= max_qty * 0.6:
                    _color_cell(cell, RED_FILL, RED_FONT)
                elif qty >= max_qty * 0.3:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
                else:
                    _color_cell(cell, GREEN_FILL, GREEN_FONT)

    # ── 4 NC Register ─────────────────────────────────────────────────────────
    ws4 = wb["4 NC Register"] if "4 NC Register" in wb.sheetnames else None
    if ws4 and ws4.max_row > 1:
        headers = {ws4.cell(1, c).value: c for c in range(1, ws4.max_column + 1)}
        status_col = headers.get("NC Status")
        days_col = headers.get("Days Open")
        for r in range(2, ws4.max_row + 1):
            status = str(ws4.cell(r, status_col).value) if status_col else ""
            days = ws4.cell(r, days_col).value if days_col else 0
            try:
                days = int(days)
            except:
                days = 0
            for c in range(1, ws4.max_column + 1):
                cell = ws4.cell(r, c)
                if not cell.value and cell.value != 0:
                    continue
                if status.lower() == "closed":
                    _color_cell(cell, GREEN_FILL, GREEN_FONT)
                elif status.lower() == "open" and days >= 7:
                    _color_cell(cell, RED_FILL, BOLD_RED)
                elif status.lower() == "open" and days >= 3:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
                else:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)

    # ── 3c Stage Audit Sheet: stage-banded shading + widths for floor use ─────
    ws3c = wb["3c Stage Audit Sheet"] if "3c Stage Audit Sheet" in wb.sheetnames else None
    if ws3c and ws3c.max_row > 1:
        band_a = PatternFill("solid", fgColor="EAF0FB")
        band_b = PatternFill("solid", fgColor="FFFFFF")
        prev_stage, band = None, band_b
        for r in range(2, ws3c.max_row + 1):
            stg = ws3c.cell(r, 1).value
            if stg != prev_stage:
                band = band_a if band is band_b else band_b
                prev_stage = stg
            for c in range(1, ws3c.max_column + 1):
                ws3c.cell(r, c).fill = band
        # Physical Count / Variance columns highlighted for the auditor to fill in
        headers3c = {ws3c.cell(1, c).value: c for c in range(1, ws3c.max_column + 1)}
        for name in ("Physical Count", "Variance"):
            cc = headers3c.get(name)
            if cc:
                for r in range(2, ws3c.max_row + 1):
                    ws3c.cell(r, cc).fill = AMBER_FILL
        ws3c.page_setup.orientation = "landscape"
        ws3c.page_setup.fitToWidth = 1
        ws3c.page_setup.fitToHeight = 0
        ws3c.sheet_properties.pageSetUpPr.fitToPage = True

    # ── 3a Inventory by Stage ─────────────────────────────────────────────────
    ws3a = wb["3a Inventory by Stage"] if "3a Inventory by Stage" in wb.sheetnames else None
    if ws3a and ws3a.max_row > 1:
        headers = {ws3a.cell(1, c).value: c for c in range(1, ws3a.max_column + 1)}
        wip_col = headers.get("WIP On-hand")
        for r in range(2, ws3a.max_row + 1):
            wip = ws3a.cell(r, wip_col).value if wip_col else 0
            try:
                wip = int(wip)
            except:
                wip = 0
            for c in range(1, ws3a.max_column + 1):
                cell = ws3a.cell(r, c)
                if not cell.value and cell.value != 0:
                    continue
                if wip > 50:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
                elif wip > 0:
                    _color_cell(cell, GREEN_FILL, GREEN_FONT)

    # ── Chart 1: Rejection % by Stage (Bar chart on 2a tab) ──
    ws2a = wb["2a Rejection by Stage"] if "2a Rejection by Stage" in wb.sheetnames else None
    if ws2a and ws2a.max_row > 1:
        chart = BarChart()
        chart.type = "col";
        chart.title = "Rejection % by Stage"
        chart.y_axis.title = "Reject %";
        chart.x_axis.title = "Stage"
        chart.style = 10;
        chart.width = 18;
        chart.height = 12
        # Stage labels (col A), Reject% (col D)
        cats = Reference(ws2a, min_col=1, min_row=2, max_row=ws2a.max_row)
        data = Reference(ws2a, min_col=4, min_row=1, max_row=ws2a.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.series[0].graphicalProperties.solidFill = RED_CLR
        ws2a.add_chart(chart, "F2")

    # ── Chart 2: Rejection by Defect Pareto (Bar on 2c tab) ──
    ws2c = wb["2c Rejection by Defect"] if "2c Rejection by Defect" in wb.sheetnames else None
    if ws2c and ws2c.max_row > 1:
        chart = BarChart()
        chart.type = "col";
        chart.title = "Rejection by Defect Code (Pareto)"
        chart.y_axis.title = "Rejected Qty";
        chart.x_axis.title = "Defect Code"
        chart.style = 10;
        chart.width = 18;
        chart.height = 12
        cats = Reference(ws2c, min_col=1, min_row=2, max_row=ws2c.max_row)
        data = Reference(ws2c, min_col=2, min_row=1, max_row=ws2c.max_row)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.series[0].graphicalProperties.solidFill = AMBER_CLR
        ws2c.add_chart(chart, "D2")

    # ── Chart 3: WIP On-hand by Stage (Bar on 3a tab) ──
    ws3a = wb["3a Inventory by Stage"] if "3a Inventory by Stage" in wb.sheetnames else None
    if ws3a and ws3a.max_row > 1:
        chart = BarChart()
        chart.type = "col";
        chart.title = "WIP On-hand by Stage"
        chart.y_axis.title = "Qty";
        chart.x_axis.title = "Stage"
        chart.style = 10;
        chart.width = 18;
        chart.height = 12
        cats = Reference(ws3a, min_col=1, min_row=2, max_row=ws3a.max_row)
        # Good Produced (col2), Moved to Next (col3), WIP On-hand (col4)
        data = Reference(ws3a, min_col=2, min_row=1, max_row=ws3a.max_row, max_col=4)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        chart.series[0].graphicalProperties.solidFill = GREEN_CLR
        chart.series[1].graphicalProperties.solidFill = BLUE_CLR
        chart.series[2].graphicalProperties.solidFill = AMBER_CLR
        ws3a.add_chart(chart, "F2")

    # ── Chart 4: NC Status Pie (Open vs Closed on 4 NC Register tab) ──
    ws4 = wb["4 NC Register"] if "4 NC Register" in wb.sheetnames else None
    if ws4 and ws4.max_row > 1:
        # Count open/closed from NC Status column (col 7 = NC Status)
        open_count = 0;
        closed_count = 0
        for row in ws4.iter_rows(min_row=2, max_row=ws4.max_row, min_col=7, max_col=7):
            for cell in row:
                if cell.value and str(cell.value).lower() == "open":
                    open_count += 1
                elif cell.value and str(cell.value).lower() == "closed":
                    closed_count += 1
        if open_count + closed_count > 0:
            # Write summary data next to the sheet for the pie chart
            summary_col = ws4.max_column + 2
            ws4.cell(row=1, column=summary_col, value="NC Status")
            ws4.cell(row=2, column=summary_col, value="Open")
            ws4.cell(row=3, column=summary_col, value="Closed")
            ws4.cell(row=1, column=summary_col + 1, value="Count")
            ws4.cell(row=2, column=summary_col + 1, value=open_count)
            ws4.cell(row=3, column=summary_col + 1, value=closed_count)
            chart = PieChart()
            chart.title = f"NC Status (Open: {open_count} / Closed: {closed_count})"
            chart.style = 10;
            chart.width = 14;
            chart.height = 10
            labels = Reference(ws4, min_col=summary_col, min_row=2, max_row=3)
            data = Reference(ws4, min_col=summary_col + 1, min_row=1, max_row=3)
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(labels)
            pt0 = DataPoint(idx=0);
            pt0.graphicalProperties.solidFill = RED_CLR
            pt1 = DataPoint(idx=1);
            pt1.graphicalProperties.solidFill = GREEN_CLR
            chart.series[0].data_points = [pt0, pt1]
            ws4.add_chart(chart, "O2")

    # ── Chart 5: WO Status breakdown Pie (Status tab) ──
    ws1 = wb["1 Status"] if "1 Status" in wb.sheetnames else None
    if ws1 and ws1.max_row > 1:
        status_counts = {}
        for row in ws1.iter_rows(min_row=2, max_row=ws1.max_row, min_col=10, max_col=10):
            for cell in row:
                if cell.value:
                    status_counts[cell.value] = status_counts.get(cell.value, 0) + 1
        if status_counts:
            sc = ws1.max_column + 2
            ws1.cell(row=1, column=sc, value="Status")
            ws1.cell(row=1, column=sc + 1, value="Count")
            for i, (k, v) in enumerate(status_counts.items(), 2):
                ws1.cell(row=i, column=sc, value=k)
                ws1.cell(row=i, column=sc + 1, value=v)
            chart = PieChart()
            chart.title = "WO Status Breakdown"
            chart.style = 10;
            chart.width = 14;
            chart.height = 10
            labels = Reference(ws1, min_col=sc, min_row=2, max_row=1 + len(status_counts))
            data = Reference(ws1, min_col=sc + 1, min_row=1, max_row=1 + len(status_counts))
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(labels)
            ws1.add_chart(chart, "O2")

    # ── Chart 6: Shortfall flagged WOs (bar on Status tab) ──
    if ws1 and ws1.max_row > 1:
        # Projected vs Target bar for each WO
        chart = BarChart()
        chart.type = "bar";
        chart.title = "WO Target vs Projected Final Good"
        chart.y_axis.title = "WO ID";
        chart.x_axis.title = "Qty"
        chart.style = 10;
        chart.width = 20;
        chart.height = max(10, ws1.max_row * 0.8)
        cats = Reference(ws1, min_col=1, min_row=2, max_row=ws1.max_row)
        # col5 = WO Good Target, col7 = Projected Final Good
        data = Reference(ws1, min_col=5, min_row=1, max_row=ws1.max_row, max_col=7)
        chart.add_data(data, titles_from_data=True)
        chart.set_categories(cats)
        ws1.add_chart(chart, "O16")

    # ── 6 Trend tab: color coding + trend line chart ──────────────────────────
    ws6 = wb["6 Trend"] if "6 Trend" in wb.sheetnames else None
    if ws6 and ws6.max_row > 1:
        headers = {ws6.cell(1, c).value: c for c in range(1, ws6.max_column + 1)}
        # Color each numeric KPI cell relative to the PRIOR row (day-over-day change).
        # For these KPIs, up = worse (red), down/flat = better (green); Total WOs/OARs/
        # Conversions/Dispatched are informational (blue) since more isn't inherently bad.
        worse_if_up = ["Shortfalls", "Open NCs", "Open NCs Aged 7d+", "Overdue WOs", "Overall Reject %"]
        neutral_cols = ["Total WOs", "Dispatched", "OARs", "Conversions"]
        prev_vals = {k: None for k in worse_if_up}
        for r in range(2, ws6.max_row + 1):
            for k in worse_if_up:
                c = headers.get(k)
                if not c:
                    continue
                cell = ws6.cell(r, c)
                try:
                    val = float(cell.value)
                except (TypeError, ValueError):
                    continue
                prev = prev_vals[k]
                if prev is None:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
                elif val > prev:
                    _color_cell(cell, RED_FILL, RED_FONT)
                elif val < prev:
                    _color_cell(cell, GREEN_FILL, GREEN_FONT)
                else:
                    _color_cell(cell, AMBER_FILL, AMBER_FONT)
                prev_vals[k] = val
            for k in neutral_cols:
                c = headers.get(k)
                if c:
                    ws6.cell(r, c).fill = PatternFill("solid", fgColor="EAF0FB")

        # Trend line chart: Shortfalls / Open NCs / Overdue WOs over time (non-contiguous
        # columns, so each series is added individually rather than as a column range)
        shortfall_c = headers.get("Shortfalls");
        open_nc_c = headers.get("Open NCs");
        overdue_c = headers.get("Overdue WOs")
        series_cols = [c for c in (shortfall_c, open_nc_c, overdue_c) if c]
        if series_cols:
            chart = LineChart()
            chart.title = "Risk KPIs Over Time"
            chart.y_axis.title = "Count";
            chart.x_axis.title = "Date"
            chart.style = 10;
            chart.width = 20;
            chart.height = 11
            cats = Reference(ws6, min_col=1, min_row=2, max_row=ws6.max_row)
            colors = [RED_CLR, AMBER_CLR, BLUE_CLR]
            for i, col in enumerate(series_cols):
                data = Reference(ws6, min_col=col, min_row=1, max_row=ws6.max_row)
                chart.add_data(data, titles_from_data=True)
            chart.set_categories(cats)
            for i, s in enumerate(chart.series):
                s.graphicalProperties.line.width = 22000
                s.graphicalProperties.line.solidFill = colors[i % len(colors)]
                s.marker.symbol = "circle"
            ws6.add_chart(chart, "K2")

        # Reject % trend
        pct_c = headers.get("Overall Reject %")
        if pct_c:
            chart2 = LineChart()
            chart2.title = "Overall Reject % Over Time"
            chart2.y_axis.title = "Reject %";
            chart2.x_axis.title = "Date"
            chart2.style = 10;
            chart2.width = 20;
            chart2.height = 11
            cats = Reference(ws6, min_col=1, min_row=2, max_row=ws6.max_row)
            data = Reference(ws6, min_col=pct_c, min_row=1, max_row=ws6.max_row)
            chart2.add_data(data, titles_from_data=True)
            chart2.set_categories(cats)
            chart2.series[0].graphicalProperties.line.solidFill = AMBER_CLR
            chart2.series[0].graphicalProperties.line.width = 22000
            chart2.series[0].marker.symbol = "diamond"
            ws6.add_chart(chart2, "K18")

        ws6.page_setup.orientation = "landscape"
        ws6.page_setup.fitToWidth = 1
        ws6.page_setup.fitToHeight = 0
        ws6.sheet_properties.pageSetUpPr.fitToPage = True


def _add_dashboard(wb, stats):
    """Build an executive-summary Dashboard tab and insert it as the first sheet."""
    if "Dashboard" in wb.sheetnames:
        del wb["Dashboard"]
    ws = wb.create_sheet("Dashboard", 0)
    ws.sheet_view.showGridLines = False

    NAVY = "1F3864"
    TITLE_FONT = Font(name="Arial", bold=True, size=18, color=NAVY)
    SUB_FONT = Font(name="Arial", italic=True, size=10, color="808080")
    TILE_LABEL_FONT = Font(name="Arial", bold=True, size=10, color="FFFFFF")
    TILE_VALUE_FONT = Font(name="Arial", bold=True, size=26, color=NAVY)
    SECTION_FONT = Font(name="Arial", bold=True, size=12, color=NAVY)
    NEUTRAL_FILL = PatternFill("solid", fgColor="D9E2F3")
    NEUTRAL_VAL_FILL = PatternFill("solid", fgColor="EAF0FB")
    thin = Side(style="thin", color="BFBFBF")
    box_border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.column_dimensions["A"].width = 3
    for c in range(2, 14):
        ws.column_dimensions[get_column_letter(c)].width = 10

    ws["B2"] = f"VSPL Daily Dashboard — {stats['date']}"
    ws["B2"].font = TITLE_FONT
    ws.merge_cells("B2:M2")
    ws["B3"] = "Executive summary — generated automatically by the OMS agent"
    ws["B3"].font = SUB_FONT
    ws.merge_cells("B3:M3")

    def tile(col_start, row_start, label, value, label_fill, value_fill, value_font):
        col_end = col_start + 2
        cl1, cl2 = get_column_letter(col_start), get_column_letter(col_end)
        ws.merge_cells(f"{cl1}{row_start}:{cl2}{row_start}")
        c = ws.cell(row=row_start, column=col_start, value=label)
        c.font = TILE_LABEL_FONT;
        c.fill = label_fill
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.merge_cells(f"{cl1}{row_start + 1}:{cl2}{row_start + 2}")
        v = ws.cell(row=row_start + 1, column=col_start, value=value)
        v.font = value_font;
        v.fill = value_fill
        v.alignment = Alignment(horizontal="center", vertical="center")
        for r in range(row_start, row_start + 3):
            for c2 in range(col_start, col_end + 1):
                ws.cell(row=r, column=c2).border = box_border

    shortfalls = stats["shortfalls"]
    open_nc = stats["open_nc"]
    open_nc_aged7 = stats["open_nc_aged7"]

    shortfall_fill = RED_FILL if shortfalls > 0 else GREEN_FILL
    shortfall_font = Font(name="Arial", bold=True, size=26, color=RED_CLR if shortfalls > 0 else GREEN_CLR)
    if open_nc == 0:
        nc_fill, nc_font_clr = GREEN_FILL, GREEN_CLR
    elif open_nc_aged7 > 0:
        nc_fill, nc_font_clr = RED_FILL, RED_CLR
    else:
        nc_fill, nc_font_clr = AMBER_FILL, AMBER_CLR
    nc_font = Font(name="Arial", bold=True, size=26, color=nc_font_clr)
    dispatch_font = Font(name="Arial", bold=True, size=26, color=GREEN_CLR)

    row1 = 5
    tile(2, row1, "TOTAL WOs", stats["total_wos"], NEUTRAL_FILL, NEUTRAL_VAL_FILL, TILE_VALUE_FONT)
    tile(6, row1, "SHORTFALLS", shortfalls, NEUTRAL_FILL, shortfall_fill, shortfall_font)
    tile(10, row1, "OPEN NCs", open_nc, NEUTRAL_FILL, nc_fill, nc_font)

    row2 = row1 + 4
    tile(2, row2, "DISPATCHED", stats["dispatched"], NEUTRAL_FILL, GREEN_FILL, dispatch_font)
    tile(6, row2, "OARs", stats["oars"], NEUTRAL_FILL, NEUTRAL_VAL_FILL, TILE_VALUE_FONT)
    tile(10, row2, "CONVERSIONS", stats["conversions"], NEUTRAL_FILL, NEUTRAL_VAL_FILL, TILE_VALUE_FONT)

    anomaly_rate = stats.get("anomaly_rate", 0.0)
    total_input_rows = stats.get("total_input_rows", 0)
    if total_input_rows == 0:
        rate_fill, rate_clr = NEUTRAL_VAL_FILL, "808080"
    elif anomaly_rate >= 10:
        rate_fill, rate_clr = RED_FILL, RED_CLR
    elif anomaly_rate >= 3:
        rate_fill, rate_clr = AMBER_FILL, AMBER_CLR
    else:
        rate_fill, rate_clr = GREEN_FILL, GREEN_CLR
    rate_font = Font(name="Arial", bold=True, size=22, color=rate_clr)

    row3 = row2 + 4
    tile(2, row3, "LEGACY CLOSED", stats.get("closed_legacy", 0), NEUTRAL_FILL, NEUTRAL_VAL_FILL, TILE_VALUE_FONT)

    row4 = row3 + 4
    tile(2, row4, "NEW WOs TODAY", stats.get("new_wos_today", 0), NEUTRAL_FILL, NEUTRAL_VAL_FILL, TILE_VALUE_FONT)
    tile(6, row4, "NEW NCs TODAY", stats.get("new_ncs_today", 0), NEUTRAL_FILL, NEUTRAL_VAL_FILL, TILE_VALUE_FONT)
    tile(10, row4, "ANOMALY RATE",
         f"{anomaly_rate:.1f}%" if total_input_rows else "N/A", NEUTRAL_FILL, rate_fill, rate_font)

    def signal_row(r, label, value_text, fill, font):
        ws.merge_cells(f"B{r}:D{r}")
        lc = ws.cell(row=r, column=2, value=label)
        lc.font = Font(name="Arial", bold=True, size=10)
        lc.alignment = Alignment(vertical="center")
        ws.merge_cells(f"E{r}:M{r}")
        vc = ws.cell(row=r, column=5, value=value_text)
        vc.font = font;
        vc.fill = fill
        vc.alignment = Alignment(vertical="center", horizontal="left", indent=1)
        for c2 in range(2, 14):
            ws.cell(row=r, column=c2).border = box_border
        ws.row_dimensions[r].height = 20

    # ── TODAY'S CYCLE: everything THIS RUN changed, so the whole run is legible from the
    # Dashboard alone without opening any other tab. Values come from _cycle_diff()'s
    # before/after snapshot, not date-filtering, so a backdated Update Date still counts.
    cyc = stats.get("cycle", {}) or {}
    cycle_row = row4 + 4
    ws.cell(row=cycle_row, column=2, value="TODAY'S CYCLE").font = SECTION_FONT
    ws.merge_cells(f"B{cycle_row}:M{cycle_row}")
    INFO_FONT = Font(name="Arial", size=10, color="1F3864")
    r = cycle_row + 2
    signal_row(r, "Orders Accepted",
              f"{cyc.get('oars_created', 0)} OAR(s), {stats.get('new_wos_today', 0)} WO(s) created",
              NEUTRAL_VAL_FILL, INFO_FONT)
    r += 1
    held, hrej = cyc.get("held_at_intake", 0), cyc.get("rejected_at_intake", 0)
    signal_row(r, "Held / Rejected at Intake", f"{held} held, {hrej} rejected",
              AMBER_FILL if (held or hrej) else NEUTRAL_VAL_FILL,
              AMBER_FONT if (held or hrej) else INFO_FONT)
    r += 1
    signal_row(r, "Production Posted",
              f"{cyc.get('ok_produced', 0)} good, {cyc.get('rejected_qty', 0)} rejected (pcs)",
              NEUTRAL_VAL_FILL, INFO_FONT)
    r += 1
    signal_row(r, "Conversions",
              f"{cyc.get('conversions_done', 0)} conversion(s), {cyc.get('conversion_qty', 0)} pcs moved",
              NEUTRAL_VAL_FILL, INFO_FONT)
    r += 1
    conv_blocked = cyc.get("conversions_blocked", 0)
    if conv_blocked:
        detail = cyc.get("conversions_blocked_detail", [])
        text = "; ".join(detail[:4]) + (f" ... +{len(detail) - 4} more" if len(detail) > 4 else "")
        signal_row(r, "Conversions Blocked", f"{conv_blocked}: {text}", RED_FILL, BOLD_RED)
        r += 1
    signal_row(r, "Dispatched",
              f"{cyc.get('dispatched_wos', 0)} WO(s), {cyc.get('dispatched_qty', 0)} pcs",
              GREEN_FILL if cyc.get("dispatched_wos", 0) else NEUTRAL_VAL_FILL,
              GREEN_FONT if cyc.get("dispatched_wos", 0) else INFO_FONT)
    r += 1
    signal_row(r, "NCs This Run", f"{stats.get('new_ncs_today', 0)} opened, {cyc.get('nc_closed', 0)} closed",
              NEUTRAL_VAL_FILL, INFO_FONT)

    key_row = r + 3
    ws.cell(row=key_row, column=2, value="KEY SIGNALS").font = SECTION_FONT
    ws.merge_cells(f"B{key_row}:M{key_row}")

    r = key_row + 2
    ac, tir = stats.get("anomaly_count", 0), stats.get("total_input_rows", 0)
    if tir == 0:
        signal_row(r, "Data Quality (Anomaly Rate)", "No input rows to assess",
                   NEUTRAL_VAL_FILL, Font(name="Arial", size=10, color="595959"))
    elif anomaly_rate >= 10:
        signal_row(r, "Data Quality (Anomaly Rate)",
                   f"{anomaly_rate:.1f}% of rows skipped ({ac} of {tir}) — HIGH, verify the "
                   f"master before trusting this report", RED_FILL, BOLD_RED)
    elif anomaly_rate >= 3:
        signal_row(r, "Data Quality (Anomaly Rate)",
                   f"{anomaly_rate:.1f}% of rows skipped ({ac} of {tir}) — review the Anomaly Report",
                   AMBER_FILL, AMBER_FONT)
    else:
        signal_row(r, "Data Quality (Anomaly Rate)",
                   f"{anomaly_rate:.1f}% of rows skipped ({ac} of {tir}) — clean", GREEN_FILL, GREEN_FONT)
    r += 1
    if stats["top_defect"]:
        code, qty = stats["top_defect"]
        signal_row(r, "Top Defect", f"{code}  ({qty} pcs)", AMBER_FILL, AMBER_FONT)
    else:
        signal_row(r, "Top Defect", "None recorded", GREEN_FILL, GREEN_FONT)
    r += 1
    if stats["top_reject_stage"]:
        stg, pct = stats["top_reject_stage"]
        fill = RED_FILL if pct >= 10 else (AMBER_FILL if pct >= 5 else GREEN_FILL)
        font = RED_FONT if pct >= 10 else (AMBER_FONT if pct >= 5 else GREEN_FONT)
        signal_row(r, "Highest Reject Stage", f"{stg}  ({pct:.1f}%)", fill, font)
    else:
        signal_row(r, "Highest Reject Stage", "None recorded", GREEN_FILL, GREEN_FONT)
    r += 1
    risk = stats["risk_wos"]
    overdue = stats.get("overdue_wos", 0)
    if risk:
        tag = f"[{overdue} OVERDUE] " if overdue else ""
        shown = tag + ", ".join(risk[:12]) + (f"  (+{len(risk) - 12} more)" if len(risk) > 12 else "")
        signal_row(r, "WOs at Delivery Risk", shown, RED_FILL, RED_FONT)
    else:
        signal_row(r, "WOs at Delivery Risk", "None", GREEN_FILL, GREEN_FONT)
    r += 1
    prev = stats.get("trend_prev")
    if prev:
        d_short = stats["shortfalls"] - int(prev.get("Shortfalls", 0))
        d_nc = stats["open_nc"] - int(prev.get("Open NCs", 0))
        arrow = lambda d: "▲" if d > 0 else ("▼" if d < 0 else "▬")
        txt = f"Shortfalls {arrow(d_short)}{abs(d_short)}   |   Open NCs {arrow(d_nc)}{abs(d_nc)}   (vs {prev.get('Date')})"
        worse = d_short > 0 or d_nc > 0
        better = d_short < 0 and d_nc <= 0
        fill = RED_FILL if worse else (GREEN_FILL if better else AMBER_FILL)
        font = RED_FONT if worse else (GREEN_FONT if better else AMBER_FONT)
        signal_row(r, "Trend vs Yesterday", txt, fill, font)
    else:
        signal_row(r, "Trend vs Yesterday", "No prior-day history yet", NEUTRAL_VAL_FILL,
                   Font(name="Arial", size=10, color="595959"))

    ws.row_dimensions[2].height = 26
    ws.sheet_view.zoomScale = 100

    # Print setup: landscape, fit to one page wide so the tiles don't spill onto page 2
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = 0.3
    ws.page_margins.right = 0.3
    ws.page_margins.top = 0.4
    ws.page_margins.bottom = 0.4


def _add_instructions_sheet(wb):
    """Plain-language 'How to Read This Report' tab, inserted as the very first sheet
    (before Dashboard) so anyone opening the workbook cold sees it first."""
    if "0 How To Read This Report" in wb.sheetnames:
        del wb["0 How To Read This Report"]
    ws = wb.create_sheet("0 How To Read This Report", 0)
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 34
    ws.column_dimensions["C"].width = 100

    TITLE = Font(name="Arial", bold=True, size=16, color="1F3864")
    SEC = Font(name="Arial", bold=True, size=12, color="FFFFFF")
    SECFILL = PatternFill("solid", fgColor=BLUE)
    SUB = Font(name="Arial", bold=True, size=10.5, color="1F3864")
    BODY = Font(name="Arial", size=10.5)
    WRAP = Alignment(vertical="top", wrap_text=True)

    r = 1
    ws.cell(row=r, column=2, value="VSPL Order Management Engine — How to Read This Report").font = TITLE
    r += 2
    ws.cell(row=r, column=2, value="Generated automatically every daily cycle. This tab explains what each other "
            "tab means and the core rules behind the numbers — read this first if anything looks unfamiliar."
            ).font = BODY
    ws.cell(row=r, column=2).alignment = WRAP
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
    r += 2

    def section(title):
        nonlocal r
        c = ws.cell(row=r, column=2, value=title); c.font = SEC; c.fill = SECFILL
        c2 = ws.cell(row=r, column=3, value=""); c2.fill = SECFILL
        r += 1

    def item(label, text):
        nonlocal r
        ws.cell(row=r, column=2, value=label).font = SUB
        ws.cell(row=r, column=2).alignment = WRAP
        cell = ws.cell(row=r, column=3, value=text)
        cell.font = BODY; cell.alignment = WRAP
        r += 1

    def blank():
        nonlocal r
        r += 1

    section("THE DAILY CYCLE, IN ONE LINE")
    item("What feeds in", "Yesterday's Master + today's 5 REQUIRED input files: Order Intake, "
         "Gate Update/MRB, Conversions, NC Tracker, and WO Release. ALL FIVE are mandatory every "
         "run — none is optional. If a function has nothing to report today, it still submits an "
         "empty-but-present file as its daily sign-off. A genuinely missing file BLOCKS the run. "
         "Everything is pure code — no AI judgement in the numbers themselves.")
    item("What comes out", "A new Master_<date>.xlsx (the updated source of truth) and this "
         "Daily_Report_<date>.xlsx (a read-only summary of it). If any input rows can't be matched "
         "safely, they're skipped and logged — never guessed — and you'll see an ANOMALY_REPORT.")
    blank()

    section("HOW MRB / GATE DATA IS READ  (important)")
    item("Snapshot, not cumulative", "Each Gate Update row is the CURRENT running-total STATE of a "
         "WO at a stage — e.g. 'this WO is at F1 with 96 good / 4 rejected' — NOT 'produced 96 more "
         "today'. Re-entering the same F1 line for several days keeps F1 at 96; it does not add up "
         "to 384. To move a WO forward, enter a row for the NEXT stage.")
    item("Target is the plan", "A stage target is only the plan. Actual good = target minus "
         "rejections, which is normal (e.g. 96 good of a 100 target with 4 rejected). A stage does "
         "not need to 'hit target' to count as done.")
    item("Current Stage", "The furthest stage that has any data entered — because data at a stage "
         "means the product physically reached it. Enter F2 data and the WO shows Current Stage = F2.")
    item("Sequential-flow check", "Stages still follow the real flow: a later stage can only "
         "process what an earlier one produced, so earlier-stage good >= later-stage good + rejects "
         "at all times. If a later stage shows MORE than an earlier one could have supplied, that's "
         "bad data (usually un-backfilled history) and it's flagged for audit — see 3c.")
    blank()

    section("TAB-BY-TAB GUIDE")
    item("Dashboard", "Executive summary: headline tiles, a 'TODAY'S CYCLE' box showing what changed "
         "in THIS run, and Key Signals (top defect, highest-reject stage, delivery risk, trend vs "
         "yesterday). A high Anomaly Rate means many input rows were skipped — check before trusting "
         "the rest.")
    item("Summary", "All-time cumulative totals as of today (open WOs, shortfalls, open NCs, OARs, "
         "WOs, yields in use). Not a 'today' view — that's the Dashboard's job.")
    item("1 Status", "One row per OPEN work order: target, current stage, projected final good, "
         "shortfall flag, delivery date, delivery-risk bucket. A WO drops off once fully Dispatched — "
         "by design.")
    item("2a Rejection by Stage", "Good vs rejected and reject % per stage, plant-wide.")
    item("2b Rejection WO+NC", "Each rejection event at WO/part level with defect, disposition, and "
         "the linked NC's status + days-open.")
    item("2c Rejection by Defect", "Pareto of rejected quantity by defect code.")
    item("3a Inventory by Stage", "Good produced / consumed by next stage / WIP on-hand per stage.")
    item("3b Inventory WO+Part", "Per-WO stage quantities and where physical WIP is sitting. The "
         "per-stage OK columns are the snapshot totals at each stage; a later stage exceeding an "
         "earlier one is a data problem (see 3c), not normal.")
    item("3c Stage Audit Sheet", "The reasoning trail for every WO/stage holding WIP — how each "
         "figure was derived — so it can be checked against the floor.")
    item("4 NC Register", "Every NC with status, dates, days-open, responsibility.")
    item("5 PO to Invoice", "Full Customer PO -> OAR -> WO -> dispatch -> invoice traceability.")
    item("6 Trend", "Day-over-day totals for recent cycles, to see direction of travel.")
    blank()

    section("STATUS VALUES")
    item("Overall Status", "Open = created, no Gate Update yet. In-Progress = some stage data logged, "
         "not through all production stages. Ready = all production stages done, awaiting/mid "
         "Dispatch. Dispatched = fully shipped (drops off '1 Status'). Closed (Legacy 2025) = "
         "migrated in as already-closed history.")
    item("Anomalies vs Exceptions", "An ANOMALY_REPORT lists rows SKIPPED this run — everything else "
         "still committed. The master's 'Exceptions' sheet is cumulative all-time and never "
         "auto-cleared, so its total is always much larger than any single day's anomaly count — "
         "expected, not a fault.")
    blank()
    ws.cell(row=r, column=2, value="Questions about a specific number? Check the Audit Log / "
            "Exceptions tabs inside Master_<date>.xlsx — every change is logged with a timestamp "
            "and source row."
            ).font = Font(name="Arial", italic=True, size=10, color="808080")
    ws.cell(row=r, column=2).alignment = WRAP
    ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)


def _style(path, dash_stats=None):
    wb = load_workbook(path)
    for ws in wb.worksheets:
        for c in range(1, ws.max_column + 1):
            ws.cell(row=1, column=c).font = HF;
            ws.cell(row=1, column=c).fill = HFILL
            ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = 18
        ws.freeze_panes = "A2"
    # Add color coding, charts and the Dashboard tab to the daily report only
    if "Summary" in wb.sheetnames:
        _color_reports(wb)  # also builds the charts (kept together historically)
        if dash_stats:
            _add_dashboard(wb, dash_stats)
        _add_instructions_sheet(wb)   # always first tab
    wb.save(path)


def cleanup_old_dated_files(outdir, keep_date):
    """Delete previous days' Master_/Daily_Report_/ANOMALY_REPORT_ files, keeping only
    today's (keep_date). Only ever called after a successful commit — never touches
    anything if the run was blocked, so a bad run can't wipe out yesterday's good files."""
    import glob
    removed = []
    for pattern in ("Master_*.xlsx", "Daily_Report_*.xlsx", "ANOMALY_REPORT_*.xlsx"):
        for f in glob.glob(os.path.join(outdir, pattern)):
            base = os.path.basename(f)
            if base.startswith("~$") or str(keep_date) in base:
                continue
            try:
                os.remove(f)
                removed.append(base)
            except OSError as e:
                print(f"  (could not remove {base}: {e})")
    if removed:
        print(f"Cleaned up {len(removed)} old file(s): {', '.join(removed)}")


def save_master(m, outdir):
    path = os.path.join(outdir, f"Master_{TODAY}.xlsx")
    # CANONICAL COLUMN ORDER: a master carried forward from a pre-v3.3 engine only had
    # Target/OK/InProc/Rej/Status per stage. OnHand/Ent get added dynamically the first time
    # something writes to them, which pandas tacks on at the END of the dataframe rather than
    # in the Target-OK-InProc-OnHand-Rej-Status-Ent sequence every fresh v3.3 master uses.
    # Reindex right before writing so the saved file always matches that canonical layout,
    # regardless of which engine vintage built the master this run started from.
    if "WO Master" in m:
        m["WO Master"] = m["WO Master"].reindex(columns=wo_cols())
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for s in MASTER_SHEETS:
            m[s].to_excel(xw, sheet_name=s, index=False)
    wb = load_workbook(path)
    for ws in wb.worksheets:
        for c in range(1, ws.max_column + 1):
            ws.cell(row=1, column=c).font = HF;
            ws.cell(row=1, column=c).fill = HFILL
        ws.freeze_panes = "A2"
    wb.save(path)
    return path


# ------------------------------------------------------------------ stock audit (v3.1)
# The Stock Audit input lets the floor reconcile the SYSTEM against a physical stocktake and,
# where the flow was wrong, correct it. It is a signed, human-authorized input — filling and
# submitting the sheet IS the authorization — processed idempotently with a full audit trail.
# Each row targets one WO and may carry up to three independent actions (applied in this order):
#   1. RE-ROUTE       New Route            -> redefine the stages the WO passes through
#   2. MOVE           Move Qty/From/To     -> shift good pieces logged at the wrong stage
#   3. ALIGN          Stage + Physical Count-> set the stage's good qty to the counted truth
# ALIGN overwrites the system figure (physical count wins) and records the variance; MOVE and
# RE-ROUTE never invent qty. Anything ambiguous or impossible goes to Exceptions, never a guess.
AUDIT_SHEET = "Stock Audit"
AUDIT_COLS = ["Audit Date", "WO ID", "Stage", "System Qty", "Physical Count",
              "Move Qty", "From Stage", "To Stage", "New Route", "Reason", "Audited By"]


def _parse_route_str(route_str):
    """Parse 'F1 > F3 > FI > Dispatch' (or comma-separated) into a canonical prod route
    with Dispatch guaranteed last. Returns [] if nothing valid was given."""
    toks = [_canon_stage(x) for x in _str(route_str).replace(",", ">").split(">") if _str(x)]
    prod, seen = [], set()
    for t in toks:
        if t in ALL_STAGES and t != "Dispatch" and t not in seen:
            prod.append(t); seen.add(t)
    return (prod + ["Dispatch"]) if prod else []


def _audit_ledger(m, date, wo, action, stage="", frm="", to="", sysq="", qty="", var="",
                  route="", reason="", by=""):
    m["Audit Ledger"].loc[len(m["Audit Ledger"])] = [date, wo, action, stage, frm, to,
                                                     sysq, qty, var, route, reason, by]


def process_audit(m, path, yields):
    if not path or not os.path.exists(path):
        return
    df = _read_input_sheet(path, AUDIT_SHEET)
    wom = m["WO Master"]
    idx = {str(w): n for n, w in zip(wom.index, wom["WO ID"])}
    posted = set(m["Audit Posted"]["Signature"].astype(str))
    for i, r in df.iterrows():
        wo = _canon_wo(r.get("WO ID"))
        ref = f"Audit row {_excel_row(df, i)}"
        if not wo:
            continue
        if wo not in idx:
            exception(m, "Audit: unknown WO", f"WO '{wo}' not in master", ref)
            continue
        n = idx[wo]
        ad = pd.to_datetime(r.get("Audit Date"), errors="coerce", dayfirst=True)
        adate = ad.date() if pd.notna(ad) else TODAY
        by = _str(r.get("Audited By")); reason = _str(r.get("Reason"))
        acted = False

        # 1) RE-ROUTE — redefine the WO's flow (targets re-derived over the new route) --------
        nr_raw = _str(r.get("New Route"))
        if nr_raw:
            new_route = _parse_route_str(nr_raw)
            if not new_route:
                exception(m, "Audit: bad New Route", f"{wo}: '{nr_raw}' has no valid stages", ref)
            else:
                sig = f"REROUTE|{adate}|{wo}|{'>'.join(new_route)}"
                if sig in posted:
                    audit(m, "AUDIT_DUP_SKIP", wo, source=ref)
                else:
                    old_route = _wo_route(wom, n)
                    good = int(_num(wom.at[n, "WO Good Target"])) or int(_num(wom.at[n, "Released Qty"]))
                    t = stage_targets(good, yields, new_route)
                    wom.at[n, "Route"] = " > ".join(new_route)
                    for s in ALL_STAGES:
                        if s in new_route:
                            wom.at[n, f"{s} Target"] = t.get(s, 0)
                            if _str(wom.at[n, f"{s} Status"]) != "Converted-in":
                                wom.at[n, f"{s} Status"] = _rag_status(
                                    wom.at[n, f"{s} OK"], wom.at[n, f"{s} Rej"],
                                    wom.at[n, f"{s} InProc"], t.get(s, 0))
                        else:
                            wom.at[n, f"{s} Target"] = 0
                            wom.at[n, f"{s} Status"] = "Skip"
                    _audit_ledger(m, adate, wo, "REROUTE", route=" > ".join(new_route),
                                  reason=reason, by=by)
                    audit(m, "AUDIT_REROUTE", wo, field="Route", old=" > ".join(old_route),
                          new=" > ".join(new_route), source=ref, note=reason)
                    m["Audit Posted"].loc[len(m["Audit Posted"])] = [sig]; posted.add(sig)
                    acted = True

        # 2) MOVE — shift good pieces from the wrong stage to the correct one -----------------
        mq = int(_num(r.get("Move Qty")))
        frm = _canon_stage(r.get("From Stage")); to = _canon_stage(r.get("To Stage"))
        if mq > 0 and (frm or to):
            if frm not in ALL_STAGES or to not in ALL_STAGES:
                exception(m, "Audit: bad move stage", f"{wo}: '{frm}' -> '{to}'", ref)
            else:
                sig = f"MOVE|{adate}|{wo}|{frm}|{to}|{mq}"
                if sig in posted:
                    audit(m, "AUDIT_DUP_SKIP", wo, source=ref)
                else:
                    avail = int(_num(wom.at[n, f"{frm} OK"]))
                    if avail < mq:
                        exception(m, "Audit: move exceeds available",
                                  f"{wo}: {frm} holds {avail}, cannot move {mq}", ref)
                    else:
                        wom.at[n, f"{frm} OK"] = avail - mq
                        wom.at[n, f"{to} OK"] = int(_num(wom.at[n, f"{to} OK"])) + mq
                        _audit_ledger(m, adate, wo, "MOVE", frm=frm, to=to, qty=mq,
                                      reason=reason, by=by)
                        audit(m, "AUDIT_MOVE", wo, field=f"{frm}->{to} OK",
                              old=str(avail), new=f"-{mq}/+{mq}", source=ref, note=reason)
                        m["Audit Posted"].loc[len(m["Audit Posted"])] = [sig]; posted.add(sig)
                        acted = True

        # 3) ALIGN — set the stage's good qty to the physical count (count is truth) ----------
        stage = _canon_stage(r.get("Stage"))
        pc = r.get("Physical Count")
        has_pc = not (pd.isna(pc) or _str(pc) == "")
        if has_pc and stage:
            if stage not in ALL_STAGES:
                exception(m, "Audit: bad stage", f"{wo}: '{stage}'", ref)
            else:
                phys = int(_num(pc)); sysq = int(_num(wom.at[n, f"{stage} OK"]))
                sig = f"ALIGN|{adate}|{wo}|{stage}|{phys}"
                if sig in posted:
                    audit(m, "AUDIT_DUP_SKIP", wo, source=ref)
                else:
                    if phys != sysq:
                        wom.at[n, f"{stage} OK"] = phys
                    _audit_ledger(m, adate, wo, "ALIGN", stage=stage, sysq=sysq, qty=phys,
                                  var=phys - sysq, reason=reason, by=by)
                    audit(m, "AUDIT_ALIGN", wo, field=f"{stage} OK", old=str(sysq), new=str(phys),
                          source=ref, note=f"variance {phys - sysq:+d}; {reason}")
                    m["Audit Posted"].loc[len(m["Audit Posted"])] = [sig]; posted.add(sig)
                    acted = True

        if acted:
            # Physical-consistency flag: along the route a later stage cannot hold MORE good
            # pieces than an earlier one. We surface it (never auto-fix — the counts are truth)
            # so a mis-count or a missing move is caught for review.
            rt = _wo_route(wom, n)
            for a2, b2 in zip(rt, rt[1:]):
                if int(_num(wom.at[n, f"{b2} OK"])) > int(_num(wom.at[n, f"{a2} OK"])):
                    exception(m, "Audit: WIP inconsistent after alignment",
                              f"{wo}: {b2} OK={int(_num(wom.at[n, f'{b2} OK']))} > "
                              f"{a2} OK={int(_num(wom.at[n, f'{a2} OK']))} — verify counts/flow", ref)
            _recompute_wo(wom, n, yields)


# ---- audit sheet writer (banner + header on row 4, matching the daily templates) -----------
def _write_audit_book(path, data_rows=None, example=True):
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.comments import Comment
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Alignment
    wb = Workbook(); ws = wb.active; ws.title = AUDIT_SHEET
    ws.sheet_view.showGridLines = False
    ncols = len(AUDIT_COLS); last = get_column_letter(ncols)
    ws.merge_cells(f"A1:{last}1"); ws.merge_cells(f"A2:{last}2"); ws.merge_cells(f"A3:{last}3")
    ws["A1"] = "STOCK AUDIT  —  reconcile physical vs system & correct part flow"
    ws["A1"].font = Font(name="Arial", bold=True, color="FFFFFF", size=13)
    ws["A1"].fill = HFILL; ws["A1"].alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 26
    ws["A2"] = ("Header row is row 4; enter data from row 5. One WO per row. Fill only what you "
                "need: Physical Count to align a stage, Move Qty/From/To to shift pieces, New "
                "Route to change the flow. Physical count OVERWRITES the system figure.")
    ws["A2"].font = Font(name="Arial", italic=True, color="FFFFFF", size=9)
    ws["A2"].fill = HFILL; ws["A2"].alignment = Alignment(vertical="center", indent=1, wrap_text=True)
    ws.row_dimensions[2].height = 30
    ws["A3"] = "  WO ID is required. System Qty is read-only reference. Leave a section blank to skip it."
    ws["A3"].font = Font(name="Arial", size=8, italic=True, color="595959")
    notes = {
        "Audit Date": "YYYY-MM-DD (defaults to today)", "WO ID": "REQUIRED — must exist in master",
        "Stage": "Stage being physically counted (F1/F2/.../Dispatch)",
        "System Qty": "Read-only: current system good qty (from the generator)",
        "Physical Count": "Counted good qty — OVERWRITES system for that stage",
        "Move Qty": "Good pieces to move to the correct stage",
        "From Stage": "Stage the pieces are wrongly logged at", "To Stage": "Correct stage",
        "New Route": "e.g. F1 > F3 > FI > Dispatch — redefines the WO's flow",
        "Reason": "Why the correction was made", "Audited By": "Who counted / authorized"}
    req = {"WO ID"}
    for j, h in enumerate(AUDIT_COLS, start=1):
        c = ws.cell(4, j, h)
        c.font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        c.fill = PatternFill("solid", fgColor="C55A11") if h in req else HFILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.comment = Comment(("REQUIRED. " if h in req else "") + notes[h], "VSPL")
        ws.column_dimensions[get_column_letter(j)].width = max(12, min(24, len(h) + 6))
    ws.row_dimensions[4].height = 40
    ws.freeze_panes = "A5"
    rows = data_rows if data_rows else ([{ "Audit Date": str(TODAY), "WO ID": "WO-142",
        "Stage": "F1", "System Qty": 118, "Physical Count": 120, "Move Qty": "", "From Stage": "",
        "To Stage": "", "New Route": "", "Reason": "cycle count", "Audited By": "S. Rao"}] if example else [])
    for ri, row in enumerate(rows, start=5):
        for j, h in enumerate(AUDIT_COLS, start=1):
            v = row.get(h, "")
            cell = ws.cell(ri, j, v)
            if data_rows is None:
                cell.font = Font(name="Arial", italic=True, color="7F7F7F")
    # dropdowns for the stage columns
    stage_list = '"' + ",".join(ALL_STAGES) + '"'
    for h in ("Stage", "From Stage", "To Stage"):
        L = get_column_letter(AUDIT_COLS.index(h) + 1)
        dv = DataValidation(type="list", formula1=stage_list, allow_blank=True)
        ws.add_data_validation(dv); dv.add(f"{L}5:{L}1000")
    wb.save(path)
    return path


def generate_audit_sheet(master, outdir):
    """Pre-fill a Stock Audit sheet from the current master: one row per WO/stage that is
    holding good WIP, with the system qty filled and Physical Count left blank to count against."""
    os.makedirs(outdir, exist_ok=True)
    m = load_master(master)
    wom = m["WO Master"]
    rows = []
    for n in wom.index:
        if _str(wom.at[n, "Overall Status"]) == "Dispatched":
            continue
        rt = _wo_route(wom, n)
        for s in [x for x in rt if x != "Dispatch"]:
            ok = int(_num(wom.at[n, f"{s} OK"]))
            if ok > 0:
                rows.append({"Audit Date": str(TODAY), "WO ID": _str(wom.at[n, "WO ID"]),
                             "Stage": s, "System Qty": ok, "Physical Count": "",
                             "Move Qty": "", "From Stage": "", "To Stage": "", "New Route": "",
                             "Reason": "", "Audited By": ""})
    path = os.path.join(outdir, f"Stock_Audit_Sheet_{TODAY}.xlsx")
    _write_audit_book(path, data_rows=rows, example=False)
    print(f"Audit sheet -> {path}  ({len(rows)} WO/stage rows to count)")
    return path


def write_audit_template(outdir):
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, "Stock_Audit_TEMPLATE.xlsx")
    _write_audit_book(path, data_rows=None, example=True)
    print(f"Blank audit template -> {path}")
    return path


def write_audit_report(outdir, applied, new_exc):
    """Separate variance / flow-correction report for one audit run."""
    path = os.path.join(outdir, f"Stock_Audit_Report_{TODAY}.xlsx")
    aligns = applied[applied["Action"] == "ALIGN"] if len(applied) else applied
    flows = applied[applied["Action"].isin(["MOVE", "REROUTE"])] if len(applied) else applied
    tot_var = int(pd.to_numeric(aligns.get("Variance"), errors="coerce").fillna(0).abs().sum()) if len(aligns) else 0
    net_var = int(pd.to_numeric(aligns.get("Variance"), errors="coerce").fillna(0).sum()) if len(aligns) else 0
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame({"Vijay Spheroidals — Stock Audit Report": [
            f"Date: {TODAY}", f"Alignments applied: {len(aligns)}",
            f"Flow corrections (move/reroute): {len(flows)}",
            f"Net qty variance (physical - system): {net_var:+d}",
            f"Absolute variance counted: {tot_var}",
            f"Consistency/anomaly flags this run: {len(new_exc)}"]}
            ).to_excel(xw, sheet_name="Summary", index=False)
        (aligns[["Audit Date", "WO ID", "Stage", "System Qty", "Counted/Move Qty", "Variance",
                 "Reason", "Audited By"]].rename(columns={"Counted/Move Qty": "Physical Count"})
         if len(aligns) else pd.DataFrame(
            columns=["Audit Date", "WO ID", "Stage", "System Qty", "Physical Count", "Variance",
                     "Reason", "Audited By"])).to_excel(xw, "Variances", index=False)
        (flows[["Audit Date", "WO ID", "Action", "From Stage", "To Stage", "Counted/Move Qty",
                "New Route", "Reason", "Audited By"]].rename(columns={"Counted/Move Qty": "Move Qty"})
         if len(flows) else pd.DataFrame(
            columns=["Audit Date", "WO ID", "Action", "From Stage", "To Stage", "Move Qty",
                     "New Route", "Reason", "Audited By"])).to_excel(xw, "Flow Corrections", index=False)
        (new_exc if len(new_exc) else pd.DataFrame(columns=MASTER_SHEETS["Exceptions"])
         ).to_excel(xw, "Anomalies", index=False)
    _style(path)
    print(f"Variance report -> {path}")
    return path


def run_audit(master, audit, outdir, history=None):
    """Apply a filled Stock Audit sheet to the master and emit a separate variance report."""
    os.makedirs(outdir, exist_ok=True)
    yields, _ = compute_yields(history)
    for s in PROD_STAGES:
        yields.setdefault(s, 1.0)
    m = load_master(master)
    led0, exc0 = len(m["Audit Ledger"]), len(m["Exceptions"])
    process_audit(m, audit, yields)
    applied = m["Audit Ledger"].iloc[led0:].copy()
    new_exc = m["Exceptions"].iloc[exc0:].copy()
    mpath = save_master(m, outdir)
    rpath = write_audit_report(outdir, applied, new_exc)
    print(f"Applied {len(applied)} audit action(s); {len(new_exc)} flag(s).")
    print("Master ->", mpath)
    return mpath, rpath


# ------------------------------------------------------------------ preflight
REQUIRED = {"Order Intake": "Order Intake", "Gate Update": "Gate Update",
            "Conversions": "Conversions", "NC Tracker": "NC Tracker",
            "WO Release": "WO Release"}


def _read_sheet(path, sheet):
    """Return (df, error). error is a string if the file/sheet can't be read."""
    try:
        return _read_input_sheet(path, sheet), None
    except Exception as e:
        return None, f"cannot read sheet '{sheet}': {e}"


def _count_input_rows(path, sheet):
    """Row count for the anomaly-rate denominator. Silently 0 if the file is absent or
    unreadable -- validate_intake/validate_refs already surface a real read error as its
    own anomaly, so this just needs to not crash the rate calculation."""
    if not path or not os.path.exists(path):
        return 0
    try:
        return len(_read_input_sheet(path, sheet))
    except Exception:
        return 0


def validate_intake(intake):
    """Anomalies in the intake file itself (checked BEFORE intake is applied)."""
    A = []
    if not intake:
        return A
    df, err = _read_sheet(intake, "Order Intake")
    if err:
        return [["Order Intake", "-", "-", err]]
    for i, r in df.iterrows():
        if _str(r.get("Order Status")) == "Accepted":
            if _num(r.get("Max Batch Size")) <= 0 or _num(r.get("PO Quantity")) <= 0:
                A.append(["Order Intake", _excel_row(df, i), _str(r.get("Customer PO Number")),
                          "Accepted order missing Max Batch Size or PO Quantity"])
    return A


def validate_refs(m, mrb, conv, nc):
    """WO/OAR/stage references — checked AFTER intake is applied, so same-day WOs are visible.
    Any returned anomaly blocks the entire run."""
    A = []
    woset = set(m["WO Master"]["WO ID"].astype(str)) if len(m["WO Master"]) else set()
    oarset = set(m["OAR Register"]["OAR No"].astype(str)) if len(m["OAR Register"]) else set()
    if mrb:
        df, err = _read_sheet(mrb, "Gate Update")
        if err:
            A.append(["Gate Update", "-", "-", err])
        else:
            for i, r in df.iterrows():
                wo = _canon_wo(r.get("WO ID"));
                stg = _canon_stage(r.get("Stage"))
                if not wo and not stg:
                    continue
                if wo not in woset:
                    A.append(["Gate Update", _excel_row(df, i), wo, f"WO not found in master (stage {stg})"])
                elif stg not in ALL_STAGES:
                    A.append(["Gate Update", _excel_row(df, i), wo, f"Invalid stage '{stg}'"])
                # v3.1: Stage Status, if given, must be a recognized value.
                sst_raw = _str(r.get("Stage Status"))
                if sst_raw and _canon_wo_status(sst_raw) not in ("In-Process", "Completed"):
                    A.append(["Gate Update", _excel_row(df, i), wo,
                              f"Invalid Stage Status '{sst_raw}' — use 'In-Process' or 'Completed'"])
    if conv:
        df, err = _read_sheet(conv, "Conversions")
        if err:
            A.append(["Conversions", "-", "-", err])
        else:
            for i, r in df.iterrows():
                src = _canon_wo(r.get("Source WO ID"));
                dest = _str(r.get("Dest OAR No"))
                entry = _canon_stage(r.get("Entry Stage"));
                q = _num(r.get("Convert Qty"))
                if not src and not dest:
                    continue
                if src not in woset:
                    A.append(["Conversions", _excel_row(df, i), src, "Source WO not found in master"])
                if dest not in oarset:
                    A.append(["Conversions", _excel_row(df, i), dest, "Dest OAR not found in master"])
                if entry not in ALL_STAGES:
                    A.append(["Conversions", _excel_row(df, i), src, f"Invalid entry stage '{entry}'"])
                if q <= 0:
                    A.append(["Conversions", _excel_row(df, i), src, "Convert Qty must be > 0"])
    if nc:
        df, err = _read_sheet(nc, "NC Tracker")
        if err:
            A.append(["NC Tracker", "-", "-", err])
        else:
            for i, r in df.iterrows():
                ncn = _str(r.get("NC Number"));
                wo = _canon_wo(r.get("WO ID"))
                if ncn and wo and wo not in woset:
                    A.append(["NC Tracker", _excel_row(df, i), wo, f"NC {ncn}: WO not found in master"])
    return A


def write_block_report(outdir, missing, anomalies, title, blocked=True):
    path = os.path.join(outdir, f"ANOMALY_REPORT_{TODAY}.xlsx")
    if blocked:
        notice = ["RUN BLOCKED — the master was NOT changed.",
                   "Fix the flagged file(s) and re-upload, then re-run the cycle.", f"Date: {TODAY}"]
    else:
        notice = ["Run completed — the master and report WERE updated with every valid row.",
                   "Only the specific rows listed below were skipped; nothing else was affected.",
                   f"Date: {TODAY}"]
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        pd.DataFrame({title: notice}).to_excel(xw, sheet_name="Notice", index=False)
        pd.DataFrame({"Missing required input": missing or ["(none)"]}
                     ).to_excel(xw, sheet_name="Missing Inputs", index=False)
        pd.DataFrame(anomalies or [], columns=["File", "Row", "WO / OAR", "Issue"]
                     ).to_excel(xw, sheet_name="Anomalies", index=False)
    _style(path)
    return path


def _cycle_snapshot(m):
    """Point-in-time counts/sums used to measure what THIS RUN changed (not what's dated
    'today' inside the rows -- an Update Date can legitimately be backdated for a catch-up
    entry, which would under-count activity if we filtered by date instead). Diffing a
    'before' and 'after' snapshot of the same fields, taken right before and right after
    processing, gives an exact count of this cycle's activity regardless of the dates
    typed into the input rows."""
    wom = m["WO Master"]
    ok_qty = int(sum(pd.to_numeric(wom.get(f"{s} OK"), errors="coerce").fillna(0).sum()
                     for s in PROD_STAGES)) if len(wom) else 0
    rej_qty = int(sum(pd.to_numeric(wom.get(f"{s} Rej"), errors="coerce").fillna(0).sum()
                      for s in PROD_STAGES)) if len(wom) else 0
    return {
        "oars": len(m["OAR Register"]),
        "wos": len(wom),
        "holds": len(m["Hold Log"]),
        "intake_rejects": len(m["Rejected Log"]),
        "conversions": len(m["Conversion Ledger"]),
        "dispatch_rows": len(m["Dispatch Ledger"]),
        "exceptions": len(m["Exceptions"]),
        "ok_qty": ok_qty,
        "rej_qty": rej_qty,
        "conv_qty": int(pd.to_numeric(m["Conversion Ledger"].get("Qty"), errors="coerce").fillna(0).sum())
                    if len(m["Conversion Ledger"]) else 0,
        "dispatch_qty": int(pd.to_numeric(m["Dispatch Ledger"].get("Dispatched Qty"), errors="coerce").fillna(0).sum())
                        if len(m["Dispatch Ledger"]) else 0,
        "nc_status": (dict(zip(m["NC Register"]["NC Number"].astype(str),
                               m["NC Register"]["NC Status"].astype(str)))
                     if len(m["NC Register"]) else {}),
    }


def _cycle_diff(before, m):
    """Before/after diff -> exactly what this run added/changed, for the Dashboard's
    'TODAY'S CYCLE' section. See _cycle_snapshot() for why this beats date-filtering."""
    after = _cycle_snapshot(m)
    nc_opened = nc_closed = 0
    for ncn, status in after["nc_status"].items():
        prev = before["nc_status"].get(ncn)
        if prev is None:
            nc_opened += 1
        elif prev.lower() != "closed" and status.lower() == "closed":
            nc_closed += 1

    # Blocked conversions THIS RUN, with the reason -- per management decision, the engine
    # still never fabricates a missing WO (a conversion against an unknown source WO stays
    # blocked), but that shouldn't be invisible: every Exceptions row logged during this run
    # under a "Conversion: ..." type is surfaced here so it shows up on the Dashboard itself,
    # not just buried in the Exceptions sheet. Exceptions is append-only, so the rows added
    # since `before["exceptions"]` (the count taken right before this run started) are
    # exactly this run's new exceptions.
    exc = m["Exceptions"]
    new_exc = exc.iloc[before["exceptions"]:] if len(exc) else exc
    conv_exc = new_exc[new_exc["Type"].astype(str).str.startswith("Conversion:")] if len(new_exc) else new_exc
    conversions_blocked = int(len(conv_exc))
    conversions_blocked_detail = [
        f"{r['Type'].replace('Conversion: ', '')}: {r['Detail']}" for _, r in conv_exc.iterrows()
    ]

    return {
        "oars_created": after["oars"] - before["oars"],
        "wos_created": after["wos"] - before["wos"],
        "held_at_intake": after["holds"] - before["holds"],
        "rejected_at_intake": after["intake_rejects"] - before["intake_rejects"],
        "conversions_done": after["conversions"] - before["conversions"],
        "conversion_qty": after["conv_qty"] - before["conv_qty"],
        "conversions_blocked": conversions_blocked,
        "conversions_blocked_detail": conversions_blocked_detail,
        "dispatched_wos": after["dispatch_rows"] - before["dispatch_rows"],
        "dispatched_qty": after["dispatch_qty"] - before["dispatch_qty"],
        "ok_produced": after["ok_qty"] - before["ok_qty"],
        "rejected_qty": after["rej_qty"] - before["rej_qty"],
        "nc_opened": nc_opened,
        "nc_closed": nc_closed,
    }


# ------------------------------------------------------------------ main
def run(master, intake, mrb, conv, nc, history, outdir, require_all=True, keep_latest_only=False,
        wor=None):
    os.makedirs(outdir, exist_ok=True)
    yields, ynote = compute_yields(history)
    m = load_master(master)
    # v3: yields for any registry-registered stage default to 1.0 (no history yet)
    for s in PROD_STAGES:
        yields.setdefault(s, 1.0)
    cycle_before = _cycle_snapshot(m)  # baseline, captured before ANY of today's rows are applied
    provided = {"Order Intake": intake, "Gate Update": mrb, "Conversions": conv,
                "NC Tracker": nc, "WO Release": wor}
    # All FIVE inputs are required. Each is a daily sign-off from its function; submit an
    # empty-but-present file for "nothing today". A genuinely missing file blocks the run.

    # PREFLIGHT 1 — required inputs present. This still hard-blocks: if a file is genuinely
    # missing there is nothing to process, so there's no "valid rows" to salvage.
    missing = [k for k, v in provided.items() if not v or not os.path.exists(v)]
    if require_all and missing:
        path = write_block_report(outdir, missing, [], "MISSING REQUIRED INPUTS — RUN BLOCKED")
        print("BLOCKED — missing required inputs:", ", ".join(missing))
        print("Anomaly report ->", path)
        return None, path

    # BUG6 FIX: per-row anomalies (bad qty in intake, unknown WO/OAR, bad stage, etc.) used to
    # BLOCK THE ENTIRE RUN, discarding every valid row along with the handful of bad ones — even
    # though process_intake/process_mrb/process_conversions/process_nc already know how to skip
    # a single bad row safely and log it (to Exceptions / the anomaly report) without touching
    # the rest. We now collect anomalies for visibility but let the run proceed; valid rows are
    # always committed to the master and the report, and only the flagged rows are skipped.
    anomalies = validate_intake(intake)

    # Apply intake to in-memory master so today's new WOs are visible to reference checks
    # and to the row-level processors below (unaffected rows still go through even though
    # some intake rows may be flagged as anomalies above).
    process_intake(m, intake, yields)

    # v3: apply WO Releases BEFORE the Gate Update so today's routes govern today's
    # gate postings (and any new stage column exists before MRB validation runs).
    process_wor(m, wor, yields)

    # Reference anomalies (WO/OAR/stage), now intake-aware — informational only, doesn't block.
    anomalies += validate_refs(m, mrb, conv, nc)

    # Denominator for the Dashboard's anomaly-rate flag: total rows across the four files
    # `anomalies` actually covers (Intake/Gate Update/Conversions/NC Tracker -- WO Release
    # issues are reported separately via Exceptions, not this list, so it's excluded here
    # to keep the rate meaning "share of THESE rows that were skipped").
    total_input_rows = (_count_input_rows(intake, "Order Intake") + _count_input_rows(mrb, "Gate Update")
                        + _count_input_rows(conv, "Conversions") + _count_input_rows(nc, "NC Tracker"))

    # COMMIT — every valid row goes in; anything matching an anomaly above is skipped by the
    # row-level exception handling inside these functions (see their own "continue" branches).
    process_mrb(m, mrb, yields)
    process_conversions(m, conv, yields, wor_path=wor)
    process_nc(m, nc)
    cycle = _cycle_diff(cycle_before, m)  # exactly what THIS run changed, for the Dashboard

    # "Source/dest WO not found" conversion failures are already caught by validate_refs
    # above and are in `anomalies`. "Insufficient qty at expected stage" can only be known
    # once the master is actually checked (needs real stage quantities), so it's detected
    # inside process_conversions itself and logged straight to Exceptions. Fold those into
    # the same Anomaly Report here too, so every blocked conversion reason is visible in one
    # place -- not "found in Exceptions, missing from the Anomaly Report."
    new_exc = m["Exceptions"].iloc[cycle_before["exceptions"]:]
    for _, er in new_exc.iterrows():
        if er["Type"] == "Conversion: insufficient qty at expected stage":
            src_row = er["Source Row"]
            rownum = src_row.replace("Conv row ", "") if isinstance(src_row, str) and src_row.startswith(
                "Conv row") else "-"
            anomalies.append(["Conversions", rownum, "-", er["Detail"]])
        elif er["Type"] == "MRB: WO at multiple stages same day":
            # extract the WO id from the detail for the anomaly's WO/OAR column
            wo_id = er["Detail"].split(":")[0] if ":" in er["Detail"] else "-"
            anomalies.append(["Gate Update", "-", wo_id, er["Detail"]])
        elif er["Type"] == "WO has no route (WO Release missing)":
            wo_id = er["Detail"].split(":")[0] if ":" in er["Detail"] else "-"
            anomalies.append(["Gate Update (WARN)", "-", wo_id, er["Detail"]])

    # FULL-MASTER REFRESH (fix): _recompute_wo() above only ever runs on the WOs that appear
    # in TODAY's WO Release / Gate Update / Conversions rows. Any WO not touched this cycle —
    # which is most of them on any given day, and ALL of them right after a migration from a
    # pre-v3.3 master that never tracked "{stage} OnHand"/"{stage} Ent" — keeps whatever those
    # derived fields last were (0/blank if they never existed). That silently understates
    # On-Hand Qty for untouched WOs in the "1b WO Stage Tracking" report even though the stage
    # genuinely has completed-but-not-yet-fed-forward material sitting on it. 3a/3c don't have
    # this problem because they recompute WIP fresh, for every open WO, every cycle, straight
    # from OK/Rej — not from a stored per-WO field. This loop gives WO Master the same guarantee:
    # every open WO's InProc/OnHand/Status/Current Stage/Projected/Shortfall are freshly derived
    # from its cumulative OK/Rej/Ent every run, whether or not it was touched today.
    for _n in m["WO Master"].index:
        _recompute_wo(m["WO Master"], _n, yields)

    rpath, nopen, nshort, open_nc = build_reports(m, outdir, yields, ynote,
                                                  anomaly_count=len(anomalies),
                                                  total_input_rows=total_input_rows,
                                                  cycle=cycle)
    mpath = save_master(m, outdir)

    if keep_latest_only:
        cleanup_old_dated_files(outdir, TODAY)

    apath = None
    if anomalies:
        apath = write_block_report(outdir, [], anomalies,
                                    "ANOMALIES FOUND — these specific rows were skipped; everything else was applied",
                                    blocked=False)
        print(f"NOTE — {len(anomalies)} anomaly(ies) found; those rows were skipped. "
              f"Master and report were still updated with every valid row.")
        for a in anomalies[:10]:
            print("  ", a)
        if len(anomalies) > 10:
            print(f"  ...and {len(anomalies) - 10} more — see anomaly report.")
        print("Anomaly report ->", apath)

    if cycle.get("conversions_blocked", 0):
        print(f"\nNOTE — {cycle['conversions_blocked']} conversion(s) blocked this run "
              f"(no WO was fabricated — see Dashboard 'Conversions Blocked' / Exceptions):")
        for d in cycle.get("conversions_blocked_detail", []):
            print("  ", d)

    print("Yields:", ynote)
    print(f"OARs:{len(m['OAR Register'])} WOs:{len(m['WO Master'])} Open:{nopen} "
          f"Shortfalls:{nshort} OpenNC:{open_nc} Conversions:{len(m['Conversion Ledger'])} "
          f"Exceptions:{len(m['Exceptions'])}")
    print("Master ->", mpath);
    print("Report ->", rpath)
    return mpath, rpath


def _cli_audit(argv):
    """Stock-audit sub-commands:
        audit-template  --outdir DIR                      -> blank fillable template
        audit-sheet     --master M.xlsx --outdir DIR      -> sheet pre-filled from the master
        run-audit       --master M.xlsx --audit A.xlsx [--history H] --outdir DIR
                                                          -> apply audit, write new master + report
    """
    mode = argv[0]
    p = argparse.ArgumentParser(prog=f"oms_engine.py {mode}")
    p.add_argument("--master"); p.add_argument("--audit")
    p.add_argument("--history"); p.add_argument("--outdir", default="./out")
    a = p.parse_args(argv[1:])
    if mode == "audit-template":
        write_audit_template(a.outdir)
    elif mode == "audit-sheet":
        if not a.master:
            p.error("audit-sheet needs --master")
        generate_audit_sheet(a.master, a.outdir)
    elif mode == "run-audit":
        if not a.master or not a.audit:
            p.error("run-audit needs --master and --audit")
        run_audit(a.master, a.audit, a.outdir, history=a.history)


if __name__ == "__main__":
    import sys
    _MODES = {"audit-template", "audit-sheet", "run-audit"}
    if len(sys.argv) > 1 and sys.argv[1] in _MODES:
        _cli_audit(sys.argv[1:])
    else:
        p = argparse.ArgumentParser(description="VSPL Order Management Engine v3")
        for a in ("master", "intake", "mrb", "conv", "nc", "history", "wor"):
            p.add_argument(f"--{a}")
        p.add_argument("--outdir", default="./out")
        p.add_argument("--allow-partial", action="store_true",
                       help="permit a run even if some of the four inputs are missing")
        p.add_argument("--keep-latest-only", action="store_true",
                       help="after a successful run, delete previous days' Master/Daily Report/"
                            "Anomaly Report files from --outdir, keeping only today's")
        a = p.parse_args()
        run(a.master, a.intake, a.mrb, a.conv, a.nc, a.history, a.outdir,
            require_all=not a.allow_partial, keep_latest_only=a.keep_latest_only, wor=a.wor)