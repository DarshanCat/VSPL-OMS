import shutil
import uuid
import re
from pathlib import Path
from typing import Optional
from fastapi import UploadFile

BASE_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
MASTERS_DIR = BASE_DATA_DIR / "masters"
REPORTS_DIR = BASE_DATA_DIR / "reports"
UPLOADS_DIR = BASE_DATA_DIR / "uploads"

for d in (MASTERS_DIR, REPORTS_DIR, UPLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)

_MASTER_DATE_RE = re.compile(r"Master_(\d{4}-\d{2}-\d{2})\.xlsx$")


def get_latest_master() -> Optional[Path]:
    """Return the most recent Master_<date>.xlsx on disk, or None if none exist yet."""
    candidates = []
    for p in MASTERS_DIR.glob("Master_*.xlsx"):
        m = _MASTER_DATE_RE.search(p.name)
        if m:
            candidates.append((m.group(1), p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]


async def save_upload(file: Optional[UploadFile], run_dir: Path) -> Optional[str]:
    """Save an uploaded file into run_dir; return its path, or None if no file was given."""
    if file is None or not file.filename:
        return None
    dest = run_dir / file.filename
    with open(dest, "wb") as f:
        f.write(await file.read())
    return str(dest)


def new_run_dir() -> Path:
    d = UPLOADS_DIR / uuid.uuid4().hex
    d.mkdir(parents=True, exist_ok=True)
    return d


def promote_master(mpath: Optional[str]) -> Optional[str]:
    """Copy a freshly generated master into MASTERS_DIR so the next run picks it up as 'latest'."""
    if not mpath:
        return None
    src = Path(mpath)
    dest = MASTERS_DIR / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return str(dest)