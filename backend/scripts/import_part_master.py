"""One-time import of the official VSPL Part Master Excel into the existing OMS
`parts` table. Reuses the app's own DB engine/session (app.core.database), so the
target database is controlled purely by whatever DATABASE_URL is set in the
environment this script runs under -- nothing here is hardcoded to dev or prod.

Source-of-truth mapping (see conversation for full analysis):
  Part Master sheet, 'Unique Internal Code'  -> Part.part_number (authoritative key)
  Part Master sheet, 'Customer Part No'      -> Part.description
  Part Master CP sheet, 'Internal Grade'     -> Part.grade (only when every CP row
                                                 for that Internal ID agrees; left
                                                 untouched otherwise)

Rows are classified before any write:
  invalid   -- blank or '#N/A' key
  conflict  -- same key appears >1 time in the sheet with a different customer or
               description (excluded from import, reported for manual review)
  valid     -- everything else (duplicate-but-identical rows are collapsed to one)

Usage:
  python scripts/import_part_master.py <path-to-xlsx> [--commit] [--report DIR]

Without --commit this is a dry run: it computes and prints every count and writes
CSV reports, but never opens a transaction against the database. --commit performs
the insert/update pass inside a single transaction and rolls back on any error.
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.order import Part
from app.models.audit import AuditLog


def _norm(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    return v


def load_part_master_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Part Master"]
    rows = list(ws.iter_rows(values_only=True))[1:]

    records = []
    invalid = []
    for excel_row_num, r in enumerate(rows, start=2):
        key = _norm(r[3]) if len(r) > 3 else None
        if key is None or str(key) == "#N/A":
            invalid.append({"row": excel_row_num, "raw": r})
            continue
        records.append({
            "row": excel_row_num,
            "part_number": str(key),
            "customer": _norm(r[0]) if len(r) > 0 else None,
            "description": str(_norm(r[6])) if len(r) > 6 and _norm(r[6]) is not None else None,
        })
    return records, invalid


def load_grade_map(path):
    """Internal ID -> grade, only where every CP row for that ID agrees. Ambiguous
    IDs are returned separately so they can be reported rather than guessed."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Part Master CP"]
    rows = list(ws.iter_rows(values_only=True))[1:]

    grades_by_id = defaultdict(set)
    for r in rows:
        iid = _norm(r[3]) if len(r) > 3 else None
        if iid is None:
            continue
        grade_val = _norm(r[5]) if len(r) > 5 else None
        # 'Internal Grade' is a lookup code (e.g. 'SG 450-B'); some rows carry a bare
        # 0 as a placeholder for "not set" rather than a real grade -- treat that the
        # same as blank, never as a literal grade value.
        if not isinstance(grade_val, str):
            continue
        grades_by_id[str(iid)].add(grade_val)

    unambiguous = {k: next(iter(v)) for k, v in grades_by_id.items() if len(v) == 1}
    ambiguous = {k: v for k, v in grades_by_id.items() if len(v) > 1}
    return unambiguous, ambiguous


def classify(records):
    by_key = defaultdict(list)
    for rec in records:
        by_key[rec["part_number"]].append(rec)

    identical_dupe_keys = []
    conflict_groups = []
    valid_by_key = {}
    for key, recs in by_key.items():
        if len(recs) == 1:
            valid_by_key[key] = recs[0]
            continue
        descs = {r["description"] for r in recs}
        custs = {r["customer"] for r in recs}
        if len(descs) == 1 and len(custs) == 1:
            identical_dupe_keys.append(key)
            valid_by_key[key] = recs[0]
        else:
            conflict_groups.append((key, recs))

    return valid_by_key, identical_dupe_keys, conflict_groups


def run(xlsx_path, commit, report_dir):
    records, invalid = load_part_master_rows(xlsx_path)
    grade_map, ambiguous_grades = load_grade_map(xlsx_path)
    valid_by_key, identical_dupes, conflict_groups = classify(records)

    conflict_keys = {k for k, _ in conflict_groups}

    db = SessionLocal()
    try:
        existing = {p.part_number: p for p in db.query(Part).all()}

        to_insert = []
        to_update = []
        unchanged = []
        grade_reported_blank = []

        for key, rec in valid_by_key.items():
            grade = grade_map.get(key)
            if key not in grade_map and key not in ambiguous_grades:
                pass  # no CP row at all for this part -- grade simply stays null
            if key in ambiguous_grades:
                grade_reported_blank.append(key)

            existing_part = existing.get(key)
            if existing_part is None:
                to_insert.append((key, rec["description"], grade))
            else:
                new_desc = rec["description"]
                new_grade = grade if grade is not None else existing_part.grade
                if (existing_part.description or None) == (new_desc or None) and \
                   (existing_part.grade or None) == (new_grade or None):
                    unchanged.append(key)
                else:
                    to_update.append((existing_part, new_desc, new_grade))

        print("=" * 70)
        print("PART MASTER IMPORT --", "COMMIT" if commit else "DRY RUN")
        print("=" * 70)
        print(f"Excel data rows:                  {len(records) + len(invalid)}")
        print(f"Invalid (blank/#N/A key):         {len(invalid)}")
        print(f"Valid rows:                       {len(records)}")
        print(f"Distinct valid part numbers:      {len(valid_by_key) + len(conflict_keys)}")
        print(f"  identical duplicates collapsed: {len(identical_dupes)}")
        print(f"  conflicting duplicates excluded:{len(conflict_groups)} groups ({sum(len(v) for _, v in conflict_groups)} rows)")
        print(f"Importable distinct parts:        {len(valid_by_key)}")
        print(f"  -> INSERT (new):                {len(to_insert)}")
        print(f"  -> UPDATE (changed):            {len(to_update)}")
        print(f"  -> UNCHANGED:                   {len(unchanged)}")
        print(f"Grade: unambiguous available:     {len([k for k in valid_by_key if k in grade_map])}")
        print(f"Grade: ambiguous in CP (blank):   {len(grade_reported_blank)}")
        print(f"Current DB part count:            {len(existing)}")
        print()

        if report_dir:
            report_dir = Path(report_dir)
            report_dir.mkdir(parents=True, exist_ok=True)

            with open(report_dir / "invalid_rows.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["excel_row", "raw_data"])
                for item in invalid:
                    w.writerow([item["row"], item["raw"]])

            with open(report_dir / "conflicting_duplicates.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["part_number", "excel_row", "customer", "description"])
                for key, recs in conflict_groups:
                    for r in recs:
                        w.writerow([key, r["row"], r["customer"], r["description"]])

            with open(report_dir / "ambiguous_grades.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["part_number", "conflicting_grade_values"])
                for key in sorted(grade_reported_blank):
                    w.writerow([key, sorted(str(g) for g in ambiguous_grades[key])])

            print(f"Reports written to: {report_dir}")
            print()

        if not commit:
            print("Dry run only -- no database changes made. Re-run with --commit to apply.")
            return

        for key, desc, grade in to_insert:
            db.add(Part(part_number=key, description=desc, grade=grade))
        for part, new_desc, new_grade in to_update:
            part.description = new_desc
            part.grade = new_grade

        db.add(AuditLog(
            user_name="system:import_part_master",
            action="PART_MASTER_BULK_IMPORT",
            entity="Part",
            entity_id=None,
            details=(
                f"inserted={len(to_insert)} updated={len(to_update)} unchanged={len(unchanged)} "
                f"invalid={len(invalid)} conflicts={len(conflict_groups)} source={Path(xlsx_path).name}"
            ),
        ))

        db.commit()
        final_count = db.query(Part).count()
        print(f"COMMITTED. Final DB part count: {final_count}")
    except Exception:
        db.rollback()
        print("ERROR -- transaction rolled back, no changes were persisted.", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("xlsx_path")
    parser.add_argument("--commit", action="store_true", help="Actually write to the database. Omit for a dry run.")
    parser.add_argument("--report", default=None, help="Directory to write CSV reports of invalid/conflicting/ambiguous rows.")
    args = parser.parse_args()
    run(args.xlsx_path, args.commit, args.report)
