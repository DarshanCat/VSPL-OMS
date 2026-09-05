from pydantic import BaseModel
from typing import Optional


class OMSRunResult(BaseModel):
    status: str  # "success" | "blocked"
    message: str
    master_file: Optional[str] = None
    report_file: Optional[str] = None
    download_master: Optional[str] = None
    download_report: Optional[str] = None