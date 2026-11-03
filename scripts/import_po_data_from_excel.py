"""
VSPL OMS -- Import PO & Schedule Master Data from Excel Dump
Imports Open_Orders_OAR sheet from VSPL_PO_OAR_WO_Data_Template (1).xlsx
into Cloud SQL / PostgreSQL (po_master, po_lines, schedule_master, customers, parts, orders link).
"""

import argparse
import datetime
import math
import os
import sys
import uuid
import openpyxl
import psycopg2
from psycopg2.extras import RealDictCursor

DEFAULT_DB_URL = "postgresql://vspl_user:hV8_Lsf.8.npPLclTk_cajQg8K3APTALuaVRsE49@34.100.147.34:5432/vspl_smes"
DEFAULT_EXCEL_PATH = r"C:\VSPL\VSPL smart\VSPL_PO_OAR_WO_Data_Template (1).xlsx"

SCHEDULE_KEYWORDS = [
    "SCH", "SCHEDULE", "SCHDULE", "SCHEDULKE", "SCHEULE",
    "SEP SCHEDULE", "JULY SCHEDULE", "APRIL SCHEDULE", "OCT SCH", "SCH DEC", "SEP"
]

def is_schedule_ref(val: str) -> bool:
    if not val:
        return False
    clean = str(val).strip().upper()
    return any(k == clean or clean.startswith(k + " ") or clean.endswith(" " + k) for k in SCHEDULE_KEYWORDS)

def parse_date(val):
    if val is None:
        return None
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.date() if isinstance(val, datetime.datetime) else val
    try:
        s = str(val).strip()
        if not s or s.lower() in ("none", "null", "nat", ""):
            return None
        return datetime.datetime.strptime(s[:10], "%Y-%m-%d").date()
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser(description="Import PO & Schedule data from Excel to OMS database")
    parser.add_argument("--excel", default=DEFAULT_EXCEL_PATH, help="Path to Excel file")
    parser.add_argument("--db-url", default=DEFAULT_DB_URL, help="PostgreSQL Database URL")
    parser.add_argument("--commit", action="store_true", help="Commit changes to database (default is dry-run)")
    args = parser.parse_args()

    print("=" * 70)
    print(" VSPL OMS -- PO & SCHEDULE MASTER IMPORT UTILITY")
    print(f" Mode     : {'*** LIVE COMMIT ***' if args.commit else 'DRY RUN (No changes saved)'}")
    print(f" Excel    : {args.excel}")
    print(f" Database : {args.db_url.split('@')[-1] if '@' in args.db_url else args.db_url}")
    print("=" * 70)

    if not os.path.exists(args.excel):
        print(f"ERROR: Excel file not found: {args.excel}")
        sys.exit(1)

    print("Loading workbook...")
    wb = openpyxl.load_workbook(args.excel, data_only=True)
    if "Open_Orders_OAR" not in wb.sheetnames:
        print("ERROR: Sheet 'Open_Orders_OAR' not found in workbook.")
        sys.exit(1)

    ws = wb["Open_Orders_OAR"]
    rows = list(ws.iter_rows(values_only=True))
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(rows[0])]
    data_rows = [r for r in rows[1:] if any(r)]
    print(f"Found {len(data_rows)} data rows in Open_Orders_OAR.")

    conn = psycopg2.connect(args.db_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # 1. Cache existing Customers
        cur.execute("SELECT id, customer_code, name FROM customers;")
        db_custs = {r["customer_code"].strip().upper(): r for r in cur.fetchall() if r["customer_code"]}

        # 2. Cache existing Parts
        cur.execute("SELECT id, part_number, description FROM parts;")
        db_parts = {r["part_number"].strip().upper(): r for r in cur.fetchall() if r["part_number"]}

        # 3. Cache existing POMaster
        cur.execute("SELECT id, customer_id, po_number, total_value FROM po_master;")
        db_pos = {(str(r["customer_id"]), r["po_number"].strip().upper()): r for r in cur.fetchall()}

        # 4. Cache existing POLines
        cur.execute("SELECT id, po_id, part_id, po_qty, customer_part_number, unit_price FROM po_lines;")
        db_polines = set()
        for r in cur.fetchall():
            db_polines.add((str(r["po_id"]), str(r["part_id"]), int(r["po_qty"])))

        # 5. Cache existing Schedules
        cur.execute("SELECT id, schedule_number, customer_id, part_id, scheduled_qty, customer_schedule_ref FROM schedule_master;")
        existing_schedules = cur.fetchall()
        db_sch_count = len(existing_schedules)
        db_sch_keys = set((str(r["customer_id"]), str(r["part_id"]), int(r["scheduled_qty"]), str(r["customer_schedule_ref"] or "").strip().upper()) for r in existing_schedules)

        # 6. Cache existing Orders (OARs)
        cur.execute("SELECT id, oar_number, customer_id, part_id, po_line_id, schedule_id, source_type FROM orders WHERE oar_number IS NOT NULL;")
        db_oars = {r["oar_number"].strip().upper(): r for r in cur.fetchall()}

        # Statistics
        new_cust_count = 0
        new_part_count = 0
        new_po_count = 0
        existing_po_count = 0
        new_poline_count = 0
        existing_poline_count = 0
        new_sch_count = 0
        existing_sch_count = 0
        oars_linked_po = 0
        oars_linked_sch = 0

        # Step A: Ensure Customers exist
        excel_cust_codes = set(str(r[1]).strip().upper() for r in data_rows if r[1])
        for ccode in sorted(excel_cust_codes):
            if ccode not in db_custs:
                cid = uuid.uuid4()
                cname = f"{ccode} Customer"
                cur.execute(
                    "INSERT INTO customers (id, customer_code, name, is_active) VALUES (%s, %s, %s, %s);",
                    (str(cid), ccode, cname, True)
                )
                db_custs[ccode] = {"id": cid, "customer_code": ccode, "name": cname}
                new_cust_count += 1

        # Step B: Ensure Parts exist
        excel_part_numbers = set(str(r[5]).strip().upper() for r in data_rows if r[5])
        for pnum in sorted(excel_part_numbers):
            if pnum not in db_parts:
                pid = uuid.uuid4()
                pdesc = f"Cast Component {pnum}"
                cur.execute(
                    "INSERT INTO parts (id, part_number, grade, description) VALUES (%s, %s, %s, %s);",
                    (str(pid), pnum, "Standard", pdesc)
                )
                db_parts[pnum] = {"id": pid, "part_number": pnum, "description": pdesc}
                new_part_count += 1

        print(f"\n[Master Data Pre-check]")
        print(f" Customers : {len(db_custs)} total ({new_cust_count} newly registered)")
        print(f" Parts     : {len(db_parts)} total ({new_part_count} newly registered)")

        # Step C: Group POs vs Schedules
        po_map = {}   # (cust_code, po_num) -> list of line dicts
        sch_lines = [] # list of schedule dicts

        for idx, r in enumerate(data_rows, start=2):
            oar_num = str(r[0]).strip() if r[0] else None
            cust_code = str(r[1]).strip().upper() if r[1] else None
            cust_po = str(r[2]).strip() if r[2] else ""
            oar_date = parse_date(r[3])
            cust_pn = str(r[4]).strip() if r[4] else None
            int_pn = str(r[5]).strip().upper() if r[5] else None
            qty = int(round(float(r[6]))) if r[6] is not None and not math.isnan(float(r[6])) else 0
            unit_price = round(float(r[7]), 2) if r[7] is not None and not math.isnan(float(r[7])) else 0.0
            deliv_date = parse_date(r[8])
            commit_date = parse_date(r[9])
            classification = str(r[10]).strip() if r[10] else "Production"
            status = str(r[11]).strip() if r[11] else "Accept"

            if not cust_code or not int_pn:
                continue

            item = {
                "row_idx": idx,
                "oar_number": oar_num,
                "customer_code": cust_code,
                "customer_po": cust_po,
                "oar_date": oar_date,
                "customer_part_number": cust_pn,
                "internal_part_number": int_pn,
                "quantity": qty,
                "unit_price": unit_price,
                "delivery_date": deliv_date,
                "commitment_date": commit_date,
                "classification": classification,
                "status": status
            }

            if is_schedule_ref(cust_po):
                sch_lines.append(item)
            else:
                po_key = (cust_code, cust_po)
                if po_key not in po_map:
                    po_map[po_key] = []
                po_map[po_key].append(item)

        print(f"\n[Classification]")
        print(f" Confirmed PO Groups : {len(po_map)} POs across {sum(len(v) for v in po_map.values())} line items")
        print(f" Schedule Items      : {len(sch_lines)} lines")

        # Step D: Process Confirmed POs
        for (cust_code, po_num), lines in po_map.items():
            customer = db_custs[cust_code]
            cid_str = str(customer["id"])
            po_key = (cid_str, po_num.upper())

            # Find earliest date for header po_date
            dates = [l["oar_date"] for l in lines if l["oar_date"]]
            po_date = min(dates) if dates else None

            if po_key in db_pos:
                po_id = db_pos[po_key]["id"]
                existing_po_count += 1
            else:
                po_id = uuid.uuid4()
                cur.execute(
                    """
                    INSERT INTO po_master (id, po_number, customer_id, po_date, status, total_value, created_by_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """,
                    (str(po_id), po_num, cid_str, po_date, "OPEN", 0.0, "Excel Data Template Import")
                )
                db_pos[po_key] = {"id": po_id, "customer_id": customer["id"], "po_number": po_num}
                new_po_count += 1

            # Process PO Lines
            for line in lines:
                part = db_parts[line["internal_part_number"]]
                pid_str = str(part["id"])
                line_key = (str(po_id), pid_str, line["quantity"])

                poline_id = None
                if line_key in db_polines:
                    existing_poline_count += 1
                    # Retrieve the existing poline_id
                    cur.execute(
                        "SELECT id FROM po_lines WHERE po_id = %s AND part_id = %s AND po_qty = %s LIMIT 1;",
                        (str(po_id), pid_str, line["quantity"])
                    )
                    r_line = cur.fetchone()
                    if r_line:
                        poline_id = r_line["id"]
                else:
                    poline_id = uuid.uuid4()
                    line_total = round(line["quantity"] * line["unit_price"], 2)
                    cur.execute(
                        """
                        INSERT INTO po_lines (id, po_id, part_id, customer_part_number, po_qty, unit_price, line_total, required_date)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """,
                        (str(poline_id), str(po_id), pid_str, line["customer_part_number"], line["quantity"], line["unit_price"], line_total, line["delivery_date"])
                    )
                    db_polines.add(line_key)
                    new_poline_count += 1

                # Link with existing Order (OAR) if present
                if line["oar_number"] and poline_id:
                    oar_key = line["oar_number"].strip().upper()
                    if oar_key in db_oars:
                        ord_rec = db_oars[oar_key]
                        if not ord_rec["po_line_id"]:
                            cur.execute(
                                "UPDATE orders SET po_line_id = %s, source_type = 'po' WHERE id = %s;",
                                (str(poline_id), str(ord_rec["id"]))
                            )
                            oars_linked_po += 1

            # Recalculate POMaster total_value
            cur.execute(
                """
                UPDATE po_master
                SET total_value = COALESCE((SELECT SUM(line_total) FROM po_lines WHERE po_id = %s), 0.0)
                WHERE id = %s;
                """,
                (str(po_id), str(po_id))
            )

        # Step E: Process Schedule Items
        current_sch_seq = db_sch_count
        for item in sch_lines:
            customer = db_custs[item["customer_code"]]
            cid_str = str(customer["id"])
            part = db_parts[item["internal_part_number"]]
            pid_str = str(part["id"])
            ref_str = item["customer_po"].strip().upper()
            sch_key = (cid_str, pid_str, item["quantity"], ref_str)

            sch_id = None
            if sch_key in db_sch_keys:
                existing_sch_count += 1
                cur.execute(
                    "SELECT id FROM schedule_master WHERE customer_id = %s AND part_id = %s AND scheduled_qty = %s AND UPPER(customer_schedule_ref) = %s LIMIT 1;",
                    (cid_str, pid_str, item["quantity"], ref_str)
                )
                r_sch = cur.fetchone()
                if r_sch:
                    sch_id = r_sch["id"]
            else:
                current_sch_seq += 1
                sch_num = f"SCH-{current_sch_seq:05d}"
                sch_id = uuid.uuid4()
                total_val = round(item["quantity"] * item["unit_price"], 2)
                cur.execute(
                    """
                    INSERT INTO schedule_master (
                        id, schedule_number, customer_id, part_id, scheduled_qty, unit_price, total_value,
                        required_date, customer_schedule_ref, po_status, created_by_name
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """,
                    (
                        str(sch_id), sch_num, cid_str, pid_str, item["quantity"], item["unit_price"], total_val,
                        item["delivery_date"], item["customer_po"], "AWAITING_PO", "Excel Data Template Import"
                    )
                )
                db_sch_keys.add(sch_key)
                new_sch_count += 1

            # Link with existing Order (OAR) if present
            if item["oar_number"] and sch_id:
                oar_key = item["oar_number"].strip().upper()
                if oar_key in db_oars:
                    ord_rec = db_oars[oar_key]
                    if not ord_rec["schedule_id"]:
                        cur.execute(
                            "UPDATE orders SET schedule_id = %s, source_type = 'schedule', oar_po_status = 'awaiting_po' WHERE id = %s;",
                            (str(sch_id), str(ord_rec["id"]))
                        )
                        oars_linked_sch += 1

        print("\n" + "=" * 70)
        print(" IMPORT SUMMARY")
        print("=" * 70)
        print(f" New Customers Added         : {new_cust_count}")
        print(f" New Parts Added             : {new_part_count}")
        print(f" New POs Created (po_master) : {new_po_count}")
        print(f" Existing POs Updated        : {existing_po_count}")
        print(f" New PO Lines (po_lines)     : {new_poline_count}")
        print(f" Existing PO Lines Preserved : {existing_poline_count}")
        print(f" New Schedules Created       : {new_sch_count}")
        print(f" Existing Schedules Preserved: {existing_sch_count}")
        print(f" Orders Linked to PO Lines   : {oars_linked_po}")
        print(f" Orders Linked to Schedules  : {oars_linked_sch}")
        print("=" * 70)

        if args.commit:
            conn.commit()
            print(">>> SUCCESS: All changes successfully committed to Cloud SQL PostgreSQL!")
        else:
            conn.rollback()
            print(">>> DRY-RUN COMPLETE: Transaction rolled back. Zero changes made to database.")
            print(">>> Run with --commit to apply changes.")

    except Exception as e:
        conn.rollback()
        print(f"\nERROR DURING EXECUTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
