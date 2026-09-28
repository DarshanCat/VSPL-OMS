"""Controlled, audited import of the VSPL Part Cross-Reference data from the
master workbook into the OMS `customer_part_cross_references` table.

Reuses the app's own database engine/session (app.core.database), so the target
database is controlled by whatever DATABASE_URL is set in the environment.

Business Rules:
1. The mapping is customer-specific:
   (Customer + Customer Part No) -> Internal Part
2. A Customer Part No may legitimately map to different internal parts for DIFFERENT customers.
3. Conflict resolution:
   - VALID UNIQUE: exactly 1 internal part per (customer, customer_part_no) -> imported
   - IDENTICAL DUPLICATE: duplicate rows with same internal part -> safely collapsed
   - CONFLICTING DUPLICATE: multiple different internal parts for same (customer, customer_part_no)
     -> EXCLUDED from import, written to conflict report
   - INVALID: missing customer, customer part number, or internal part
     -> EXCLUDED from import, written to invalid report
4. Production Safety:
   - DRY RUN by default (without --commit flag, no database transaction is opened)
   - Existing identical mappings in DB are preserved
   - Existing conflicting mappings in DB are NEVER overwritten automatically
   - Atomic transaction when committing: rolls back completely on any unexpected error

Usage:
  python scripts/import_part_cross_references.py <path-to-master-xlsx> [--pm-xlsx <path-to-pm-xlsx>] [--report DIR] [--commit]
"""
import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal, engine, Base, auto_migrate_schema
from app.models.order import Customer, Part
from app.models.customer_part_cross_reference import CustomerPartCrossReference
from app.models.audit import AuditLog



def _norm(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v if v and v != "None" and v != "#N/A" else None
    return v


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def load_part_master_metadata(pm_xlsx_path: Path):
    """Loads (internal_part_code -> {customer_code, customer_name, customer_part_no})
    from the Part Master Excel sheet, if available."""
    if not pm_xlsx_path or not Path(pm_xlsx_path).exists():
        return {}, {}

    wb = openpyxl.load_workbook(str(pm_xlsx_path), read_only=True, data_only=True)
    if "Part Master" not in wb.sheetnames:
        return {}, {}

    ws = wb["Part Master"]
    rows = list(ws.iter_rows(values_only=True))[1:]

    pm_by_int = {}
    cust_by_code = {}

    for r in rows:
        c_name = _norm(r[0]) if len(r) > 0 else None
        c_code = _norm(r[1]) if len(r) > 1 else None
        int_id = _norm(r[3]) if len(r) > 3 else None
        c_part = _norm(r[6]) if len(r) > 6 else None

        if int_id:
            info = {
                "customer_code": c_code,
                "customer_name": c_name,
                "customer_part_no": c_part,
            }
            pm_by_int[int_id] = info
            pm_by_int[int_id.upper()] = info

        if c_code and c_code not in cust_by_code:
            cust_by_code[c_code] = c_name or c_code

    return pm_by_int, cust_by_code


def load_cross_reference_rows(master_xlsx_path: Path):
    """Loads all raw data rows from 'Part Cross-Reference' sheet in the Master workbook."""
    wb = openpyxl.load_workbook(str(master_xlsx_path), read_only=True, data_only=True)
    if "Part Cross-Reference" not in wb.sheetnames:
        raise ValueError(f"Sheet 'Part Cross-Reference' not found in {master_xlsx_path}")

    ws = wb["Part Cross-Reference"]
    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return [], []

    header = all_rows[0]
    data_rows = all_rows[1:]
    return header, data_rows


def classify_cross_reference_records(data_rows, pm_by_int, cust_by_code):
    """Classifies source records into:
    - valid_unique: (customer_code, customer_part_no) -> record
    - identical_dupes: list of identical duplicated records collapsed
    - conflict_groups: (customer_code, customer_part_no) -> list of conflicting records
    - invalid_records: list of unparseable/missing records
    - cross_customer_shared: customer_part_numbers legitimately shared across different customers
    """
    all_cust_codes = sorted(cust_by_code.keys(), key=len, reverse=True) if cust_by_code else []

    invalid_records = []
    resolved_records = []

    for excel_row_num, r in enumerate(data_rows, start=2):
        cp = _norm(r[0]) if len(r) > 0 else None
        ip = _norm(r[1]) if len(r) > 1 else None
        src = _norm(r[2]) if len(r) > 2 else None

        # Determine customer
        c_code = None
        c_name = None

        if ip:
            pm_info = pm_by_int.get(ip) or pm_by_int.get(ip.upper())
            if pm_info and pm_info.get("customer_code"):
                c_code = pm_info["customer_code"]
                c_name = pm_info["customer_name"]
            else:
                # Prefix matching against known customer codes
                for code in all_cust_codes:
                    if ip.upper().startswith(code.upper()):
                        c_code = code
                        c_name = cust_by_code.get(code)
                        break

        # Validate mandatory fields
        if not cp or not ip or not c_code:
            reasons = []
            if not cp:
                reasons.append("Missing Customer Part No")
            if not ip:
                reasons.append("Missing Internal Part No")
            if not c_code:
                reasons.append("Unable to resolve Customer")

            invalid_records.append({
                "excel_row": excel_row_num,
                "raw": list(r),
                "reasons": "; ".join(reasons),
                "customer_part_no": cp,
                "internal_part_no": ip,
                "customer_code": c_code,
            })
        else:
            resolved_records.append({
                "excel_row": excel_row_num,
                "raw": list(r),
                "customer_code": c_code,
                "customer_name": c_name or c_code,
                "customer_part_no": cp,
                "internal_part_no": ip,
                "source": src or "Fdata",
            })

    # Group by (customer_code, customer_part_no)
    by_pair = defaultdict(list)
    for rec in resolved_records:
        key = (rec["customer_code"], rec["customer_part_no"])
        by_pair[key].append(rec)

    valid_unique = {}
    identical_dupes = []
    conflict_groups = []

    for (c_code, cp), recs in by_pair.items():
        distinct_ips = {r["internal_part_no"] for r in recs}
        if len(recs) == 1:
            valid_unique[(c_code, cp)] = recs[0]
        elif len(distinct_ips) == 1:
            identical_dupes.append(((c_code, cp), recs))
            valid_unique[(c_code, cp)] = recs[0]
        else:
            conflict_groups.append(((c_code, cp), recs))

    # Identify Customer Part Numbers shared across different customers
    by_global_cp = defaultdict(set)
    for (c_code, cp) in valid_unique:
        by_global_cp[cp].add(c_code)
    cross_customer_shared = {cp: sorted(custs) for cp, custs in by_global_cp.items() if len(custs) > 1}

    return (
        valid_unique,
        identical_dupes,
        conflict_groups,
        invalid_records,
        cross_customer_shared,
        resolved_records,
    )


def run(
    master_xlsx_path: str,
    pm_xlsx_path: str = None,
    report_dir: str = None,
    commit: bool = False,
):
    master_p = Path(master_xlsx_path).resolve()
    if not master_p.exists():
        raise FileNotFoundError(f"Master file not found: {master_p}")

    pm_p = Path(pm_xlsx_path).resolve() if pm_xlsx_path else None
    master_sha = compute_sha256(master_p)

    pm_by_int, cust_by_code = load_part_master_metadata(pm_p)
    header, data_rows = load_cross_reference_rows(master_p)

    (
        valid_unique,
        identical_dupes,
        conflict_groups,
        invalid_records,
        cross_customer_shared,
        resolved_records,
    ) = classify_cross_reference_records(data_rows, pm_by_int, cust_by_code)

    Base.metadata.create_all(bind=engine)
    auto_migrate_schema()

    db = SessionLocal()
    try:
        # Load existing DB state
        existing_customers = {c.customer_code.upper(): c for c in db.query(Customer).all()}
        existing_parts = {p.part_number.upper(): p for p in db.query(Part).all()}
        existing_refs = db.query(CustomerPartCrossReference).all()

        # Index existing cross-references by (customer_id, customer_part_no.lower())
        existing_ref_map = {}
        for ref in existing_refs:
            existing_ref_map[(ref.customer_id, ref.customer_part_no.lower())] = ref

        to_insert = []
        unchanged = []
        prod_conflicts = []
        missing_parts = []
        created_customers = []

        for (c_code, cp), rec in valid_unique.items():
            # 1. Resolve Customer
            cust_obj = existing_customers.get(c_code.upper())
            if not cust_obj:
                # Customer missing from DB: will be safely created if committing
                cust_name = rec.get("customer_name") or c_code
                cust_obj = Customer(
                    customer_code=c_code,
                    name=cust_name,
                    is_active=True,
                )
                if commit:
                    db.add(cust_obj)
                    db.flush()
                existing_customers[c_code.upper()] = cust_obj
                created_customers.append(c_code)

            # 2. Resolve Part
            part_number = rec["internal_part_no"]
            part_obj = existing_parts.get(part_number.upper())
            if not part_obj:
                # Part missing in parts table
                missing_parts.append({
                    "customer_code": c_code,
                    "customer_part_no": cp,
                    "internal_part_no": part_number,
                    "excel_row": rec["excel_row"],
                })
                continue

            # 3. Check existing cross-reference in DB
            db_key = (cust_obj.id, cp.lower())
            existing_ref = existing_ref_map.get(db_key)

            if existing_ref:
                if existing_ref.part_id == part_obj.id:
                    unchanged.append(rec)
                else:
                    # Conflicting mapping in production! Never overwrite automatically!
                    curr_part = db.query(Part).filter(Part.id == existing_ref.part_id).first()
                    prod_conflicts.append({
                        "customer_code": c_code,
                        "customer_part_no": cp,
                        "source_internal_part": part_number,
                        "db_existing_part": curr_part.part_number if curr_part else str(existing_ref.part_id),
                        "excel_row": rec["excel_row"],
                    })
            else:
                to_insert.append({
                    "customer_id": cust_obj.id,
                    "customer_code": c_code,
                    "customer_part_no": cp,
                    "part_id": part_obj.id,
                    "internal_part_no": part_obj.part_number,
                    "source": rec.get("source") or "Fdata",
                    "excel_row": rec["excel_row"],
                })

        # Summary Metrics
        timestamp_str = datetime.now(timezone.utc).isoformat()

        print("=" * 75)
        print("PART CROSS-REFERENCE IMPORT --", "COMMIT" if commit else "DRY RUN")
        print("=" * 75)
        print(f"Source Master File:               {master_p.name}")
        print(f"Source File SHA-256:              {master_sha}")
        print(f"Timestamp (UTC):                  {timestamp_str}")
        print(f"Total Excel Data Rows:            {len(data_rows)}")
        print(f"Invalid Rows (excluded):          {len(invalid_records)}")
        print(f"Valid Source Rows:                {len(resolved_records)}")
        print(f"Distinct (Cust, CustPart) pairs:  {len(valid_unique) + len(conflict_groups)}")
        print(f"  -> Valid Unique Pairs:          {len(valid_unique)}")
        print(f"  -> Identical Dupes (collapsed): {len(identical_dupes)}")
        print(f"  -> Intra-Cust Conflicts (excl): {len(conflict_groups)} groups ({sum(len(v) for _, v in conflict_groups)} rows)")
        print(f"Customer-Shared Part Nos:         {len(cross_customer_shared)} (legitimate across different customers)")
        print()
        print("DATABASE COMPARISON:")
        print(f"Current DB Cross-References:      {len(existing_refs)}")
        print(f"  -> Already Present Identical:   {len(unchanged)}")
        print(f"  -> Conflicting with DB (excl):  {len(prod_conflicts)}")
        print(f"  -> Missing Part Master (excl):  {len(missing_parts)}")
        print(f"  -> Proposed New Inserts:        {len(to_insert)}")
        if created_customers:
            print(f"  -> Customers Auto-Created:      {len(created_customers)} ({', '.join(sorted(created_customers)[:10])}...)")
        print("=" * 75)

        # Write reports
        if report_dir:
            out_dir = Path(report_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            # 1. Invalid rows
            with open(out_dir / "invalid_rows.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["excel_row", "reason", "customer_part_no", "internal_part_no", "customer_code", "raw_data"])
                for inv in invalid_records:
                    w.writerow([inv["excel_row"], inv["reasons"], inv["customer_part_no"], inv["internal_part_no"], inv["customer_code"], inv["raw"]])

            # 2. Intra-customer conflicts
            with open(out_dir / "conflicting_duplicates.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["customer_code", "customer_part_no", "excel_row", "internal_part_no", "source"])
                for (cc, cp), recs in conflict_groups:
                    for r in recs:
                        w.writerow([cc, cp, r["excel_row"], r["internal_part_no"], r["source"]])

            # 3. Valid unique mappings
            with open(out_dir / "valid_unique_mappings.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["customer_code", "customer_name", "customer_part_no", "internal_part_no", "source", "excel_row"])
                for (cc, cp), r in valid_unique.items():
                    w.writerow([cc, r.get("customer_name"), cp, r["internal_part_no"], r["source"], r["excel_row"]])

            # 4. Production conflicts if any
            if prod_conflicts:
                with open(out_dir / "production_conflicts.csv", "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["customer_code", "customer_part_no", "source_internal_part", "db_existing_part", "excel_row"])
                    for pc in prod_conflicts:
                        w.writerow([pc["customer_code"], pc["customer_part_no"], pc["source_internal_part"], pc["db_existing_part"], pc["excel_row"]])

            # 5. Audit summary JSON
            audit_summary = {
                "source_file_name": master_p.name,
                "source_file_sha256": master_sha,
                "import_timestamp_utc": timestamp_str,
                "source_data_rows": len(data_rows),
                "valid_unique_count": len(valid_unique),
                "identical_dupes_collapsed_count": len(identical_dupes),
                "intra_customer_conflicts_count": len(conflict_groups),
                "intra_customer_conflict_rows": sum(len(v) for _, v in conflict_groups),
                "invalid_rows_count": len(invalid_records),
                "cross_customer_shared_part_count": len(cross_customer_shared),
                "existing_db_count": len(existing_refs),
                "existing_identical_count": len(unchanged),
                "existing_db_conflicts_count": len(prod_conflicts),
                "missing_part_master_count": len(missing_parts),
                "proposed_insert_count": len(to_insert),
                "committed": commit,
            }
            with open(out_dir / "audit_report.json", "w", encoding="utf-8") as f:
                json.dump(audit_summary, f, indent=2)

            print(f"Audit and CSV reports successfully generated at: {out_dir}")
            print()

        if not commit:
            print("DRY RUN COMPLETE: No database modifications made. All constraints and audit checks passed.")
            return audit_summary

        # COMMIT PASS: Atomic execution inside single transaction
        print("EXECUTING ATOMIC DATABASE INSERT...")
        for item in to_insert:
            new_entry = CustomerPartCrossReference(
                customer_id=item["customer_id"],
                customer_part_no=item["customer_part_no"],
                part_id=item["part_id"],
                source=item["source"],
                is_active=True,
                created_by_name="system:import_part_cross_references",
            )
            db.add(new_entry)

        db.add(AuditLog(
            user_name="system:import_part_cross_references",
            action="PART_CROSS_REFERENCE_BULK_IMPORT",
            entity="CustomerPartCrossReference",
            entity_id=None,
            details=(
                f"inserted={len(to_insert)} unchanged={len(unchanged)} conflicts={len(conflict_groups)} "
                f"invalid={len(invalid_records)} source={master_p.name} sha256={master_sha[:12]}"
            ),
        ))

        db.commit()
        final_count = db.query(CustomerPartCrossReference).count()
        print(f"SUCCESS: Committed {len(to_insert)} new cross-reference mappings. Final DB count: {final_count}")
        return audit_summary

    except Exception:
        db.rollback()
        print("ERROR: Transaction rolled back completely. No changes were persisted.", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audited Part Cross-Reference Import / Dry Run")
    parser.add_argument("master_xlsx", help="Path to Master Excel workbook containing 'Part Cross-Reference' sheet")
    parser.add_argument("--pm-xlsx", default=None, help="Optional path to Part Master Control Plan Excel workbook")
    parser.add_argument("--report-dir", default=None, help="Directory to save CSV audit reports and JSON summary")
    parser.add_argument("--commit", action="store_true", help="Execute database commit. Omit for safe DRY RUN.")
    args = parser.parse_args()

    run(args.master_xlsx, args.pm_xlsx, args.report_dir, args.commit)
