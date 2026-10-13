import csv
import io
import logging
import re
from pathlib import Path
from typing import List, Optional, Union
import pandas as pd
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import require_roles
from app.core.roles import PLANNING_ROLES
from app.schemas.oms import OMSRunResult, WOOarLinkRow, LinkResult
from app.services.oms_integration_service import OMSIntegrationService
from app.oms_core import storage
from app.oms_core.oms_engine import run as run_oms_cycle
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/v1/oms", tags=["oms"])
logger = logging.getLogger(__name__)

# OMS Engine batch upload/download is master-data-adjacent (it ingests the same
# master workbook this system's Masters UI now edits directly) -- Planning-only,
# per the OMS Roles & Responsibilities spec's "Master-data administration" line.
ALLOWED_ROLES = PLANNING_ROLES


def _safe_name(filename: str) -> str:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return filename


@router.post("/run-cycle", response_model=OMSRunResult)
async def run_cycle(
    intake: UploadFile = File(None),
    mrb: UploadFile = File(None),
    conv: UploadFile = File(None),
    nc: UploadFile = File(None),
    wo_release: UploadFile = File(None),
    history: UploadFile = File(None),
    master: UploadFile = File(None),
    allow_partial: bool = Form(False),
    user=Depends(require_roles(*ALLOWED_ROLES)),
):
    run_dir = storage.new_run_dir()

    master_path = await storage.save_upload(master, run_dir)
    if not master_path:
        latest = storage.get_latest_master()
        master_path = str(latest) if latest else None

    intake_path = await storage.save_upload(intake, run_dir)
    mrb_path = await storage.save_upload(mrb, run_dir)
    conv_path = await storage.save_upload(conv, run_dir)
    nc_path = await storage.save_upload(nc, run_dir)
    wo_release_path = await storage.save_upload(wo_release, run_dir)
    history_path = await storage.save_upload(history, run_dir)

    outdir = str(storage.REPORTS_DIR)

    try:
        mpath, rpath = await run_in_threadpool(
            run_oms_cycle,
            master_path, intake_path, mrb_path, conv_path, nc_path, history_path,
            outdir, require_all=not allow_partial, wor=wo_release_path,
        )
    except Exception:
        logger.exception("OMS engine run-cycle failed")
        raise HTTPException(status_code=500, detail="Engine error — see server logs for detail.")

    if mpath is None:
        report_name = Path(rpath).name if rpath else None
        return OMSRunResult(
            status="blocked",
            message="Run blocked by the engine's own validation — see anomaly report. Master was not changed.",
            report_file=report_name,
            download_report=f"/api/v1/oms/download/report/{report_name}" if report_name else None,
        )

    storage.promote_master(mpath)

    return OMSRunResult(
        status="success",
        message="Daily cycle completed.",
        master_file=Path(mpath).name,
        report_file=Path(rpath).name,
        download_master=f"/api/v1/oms/download/master/{Path(mpath).name}",
        download_report=f"/api/v1/oms/download/report/{Path(rpath).name}",
    )


@router.get("/download/master/{filename}")
def download_master(filename: str, user=Depends(require_roles(*ALLOWED_ROLES))):
    filename = _safe_name(filename)
    path = storage.MASTERS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


@router.get("/download/report/{filename}")
def download_report(filename: str, user=Depends(require_roles(*ALLOWED_ROLES))):
    filename = _safe_name(filename)
    path = storage.REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


@router.get("/latest-master")
def latest_master(user=Depends(require_roles(*ALLOWED_ROLES))):
    latest = storage.get_latest_master()
    return {"latest_master": latest.name if latest else None}


def _clean_val(v) -> str:
    if v is None or pd.isna(v):
        return ""
    return str(v).strip()


def _clean_int_val(v) -> Optional[int]:
    if v is None or pd.isna(v):
        return None
    try:
        val = int(float(v))
        return val
    except Exception:
        return None


def _dict_to_link_row(d: dict) -> WOOarLinkRow:
    k_map = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in d.items()}

    wo_id = (
        k_map.get("woid")
        or k_map.get("wo")
        or k_map.get("wono")
        or k_map.get("wonumber")
        or d.get("wo_id")
        or d.get("WO")
        or d.get("WO NO")
        or ""
    )

    oar_no = (
        k_map.get("oarno")
        or k_map.get("oar")
        or k_map.get("oarnumber")
        or d.get("oar_no")
        or d.get("OAR")
        or d.get("OAR NO")
        or None
    )

    customer = (
        k_map.get("customer")
        or k_map.get("customername")
        or k_map.get("customercode")
        or d.get("customer")
        or d.get("Customer")
        or ""
    )

    customer_po = (
        k_map.get("customerponumber")
        or k_map.get("customerpo")
        or k_map.get("ponumber")
        or k_map.get("po")
        or d.get("customer_po_number")
        or d.get("Customer PO Number")
        or d.get("PO NUMBER")
        or ""
    )

    part_no = (
        k_map.get("partno")
        or k_map.get("partnumber")
        or k_map.get("part")
        or d.get("part_no")
        or d.get("Part No")
        or d.get("PART NO")
        or ""
    )

    grade = k_map.get("grade") or d.get("grade") or d.get("Grade") or "Standard"

    po_qty_raw = k_map.get("poquantity") or k_map.get("poqty") or d.get("po_quantity") or d.get("PO Qty")
    po_quantity = _clean_int_val(po_qty_raw)

    wo_qty_raw = (
        k_map.get("woquantity")
        or k_map.get("woqty")
        or k_map.get("releaseqty")
        or d.get("wo_quantity")
        or d.get("WO Qty")
        or d.get("RELEASE QTY")
        or 0
    )
    wo_quantity = _clean_int_val(wo_qty_raw) or 0

    deliv_date = (
        k_map.get("custdeliverydate")
        or k_map.get("setupdate")
        or k_map.get("deliverydate")
        or k_map.get("reqdate")
        or d.get("cust_delivery_date")
        or d.get("Setup Date")
        or d.get("Req Date")
        or None
    )

    return WOOarLinkRow(
        wo_id=_clean_val(wo_id),
        oar_no=_clean_val(oar_no) or None,
        customer=_clean_val(customer),
        customer_po_number=_clean_val(customer_po),
        part_no=_clean_val(part_no),
        grade=_clean_val(grade) or "Standard",
        po_quantity=po_quantity,
        wo_quantity=wo_quantity,
        cust_delivery_date=deliv_date,
    )


@router.post("/wo-oar-link", response_model=LinkResult)
async def link_wo_to_oar_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(require_roles(*ALLOWED_ROLES)),
):
    """
    Links team-assigned Work Order IDs to OARs (Orders) idempotently.
    Accepts:
    - JSON list of row objects e.g. [{"wo_id": "...", ...}] or object with {"rows": [...]}
    - Multipart form upload with CSV or Excel file (field name 'file')
    - Raw text/csv content
    """
    content_type = request.headers.get("content-type", "").lower()
    rows: List[WOOarLinkRow] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        file_item = form.get("file")
        if not file_item or not hasattr(file_item, "read"):
            raise HTTPException(status_code=400, detail="Form upload missing 'file' field.")
        contents = await file_item.read()
        filename = getattr(file_item, "filename", "upload.csv") or "upload.csv"
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(contents))
            rows = [_dict_to_link_row(r) for r in df.to_dict(orient="records")]
        else:
            text_data = contents.decode("utf-8", errors="ignore")
            reader = csv.DictReader(io.StringIO(text_data))
            rows = [_dict_to_link_row(r) for r in reader]

    elif "text/csv" in content_type:
        body_bytes = await request.body()
        text_data = body_bytes.decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text_data))
        rows = [_dict_to_link_row(r) for r in reader]

    else:
        # Default to JSON body
        try:
            body = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse request body: {str(e)}")

        if isinstance(body, list):
            rows = [_dict_to_link_row(item) for item in body]
        elif isinstance(body, dict) and "rows" in body and isinstance(body["rows"], list):
            rows = [_dict_to_link_row(item) for item in body["rows"]]
        elif isinstance(body, dict):
            rows = [_dict_to_link_row(body)]
        else:
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON format. Expected list of rows or object with 'rows' list.",
            )

    return OMSIntegrationService.link_wo_to_oar(db, rows)