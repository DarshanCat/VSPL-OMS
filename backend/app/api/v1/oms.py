from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import require_roles
from app.models.user import UserRole
from app.schemas.oms import OMSRunResult
from app.oms_core import storage
from app.oms_core.oms_engine import run as run_oms_cycle
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/api/v1/oms", tags=["oms"])

ALLOWED_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER)


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Engine error: {e}")

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