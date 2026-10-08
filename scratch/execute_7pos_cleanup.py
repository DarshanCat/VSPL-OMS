import subprocess
import json
from urllib.parse import urlparse, unquote
from datetime import datetime, date
from uuid import UUID
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2.credentials import Credentials
import pg8000.dbapi

# Custom JSON encoder for UUID, datetime, date
class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

TARGET_PO_IDS = [
    "1226e1ca-65ad-43cb-b693-7e2e2ed856e7",  # 91160310
    "48c46ab0-8aea-48d7-815f-a2e40b65a184",  # Schedule
    "aadc2984-a134-480e-abd4-bbe34bc22760",  # 4510284161
    "d1dffb2d-140b-4ceb-a2e6-b73b476e842c",  # MS/GEN/262251
    "2457a77c-a193-46db-838a-faf12efe4849",  # ACNC/VSPL/18 /2026-27
    "f864db6b-a915-4337-9a76-b965ab4d2503",  # PO-009-OEM/26-27
    "75533993-0dfa-44a1-abbf-11b333e60204",  # ACNC/VSPL/16/2026-27
]

TARGET_LINE_IDS = [
    "c2658f52-d6f0-4902-ba3f-4d2ac789088d",
    "d2aeb3cb-4cbe-459f-9565-c8b2f8839dc1",
    "7ef5272b-3046-4e34-a938-a5d72ef42201",
    "69f9fbc3-f76e-47a6-9d75-9971acce0deb",
    "382fbee5-5f64-41a9-b1bb-c05e7d95d90d",
    "a112a018-4526-4ba6-a8a5-a9c80e025a58",
    "6cfce7ef-01cb-4e6a-bd94-e6781da877e7",
    "49dc16ae-c406-4558-8ceb-e951866b5628",
    "a22cd7a4-6c17-47fc-84d8-880f43145acd",
    "45298605-2b0c-4862-973a-e425ae1eb5e5",
    "f97fbd27-8af6-47a7-bdd0-917156b1cd1f",
    "8135dca2-8445-4379-a3af-febdd72c8428",
    "8a6960c1-8bbd-4b9f-b739-9605a4f6700f",
    "cc290650-3ac8-4e5a-bb82-6e6bf80d7578",
    "b878d417-574d-4952-9695-3fbcd65cb7fb",
    "80d0b72c-68f2-4d11-b84b-6bc258a86e64",
]

def main():
    token = subprocess.check_output('gcloud.cmd auth print-access-token', shell=True).decode().strip()
    credentials = Credentials(token)

    secret = subprocess.check_output('gcloud.cmd secrets versions access latest --secret=VSPL_DATABASE_URL --project=vspl-oms-510015', shell=True).decode().strip()
    parsed = urlparse(secret)
    username = unquote(parsed.username) if parsed.username else 'vspl_user'
    password = unquote(parsed.password) if parsed.password else ''
    dbname = parsed.path.lstrip('/')

    connector = Connector(credentials=credentials)
    conn = connector.connect(
        'vspl-oms-510015:asia-south1:vspl-oms-db',
        'pg8000',
        user=username,
        password=password,
        db=dbname,
        ip_type=IPTypes.PUBLIC
    )
    # Turn off autocommit so we control the transaction explicitly
    conn.autocommit = False
    cur = conn.cursor()

    print("==================================================")
    print("STEP 1: PRE-EXECUTION SNAPSHOT & ASSERTIONS")
    print("==================================================")

    # 1. Fetch full snapshot of po_master rows
    cur.execute(f"""
    SELECT id, po_number, customer_id, status, po_date, validity_date, created_by_id, created_at
    FROM po_master
    WHERE id IN ({','.join(['%s']*len(TARGET_PO_IDS))});
    """, tuple(TARGET_PO_IDS))
    po_cols = ['id', 'po_number', 'customer_id', 'status', 'po_date', 'validity_date', 'created_by_id', 'created_at']
    po_snapshot = [dict(zip(po_cols, row)) for row in cur.fetchall()]
    assert len(po_snapshot) == 7, f"Expected 7 po_master rows, found {len(po_snapshot)}"

    # 2. Fetch full snapshot of po_lines rows
    cur.execute(f"""
    SELECT id, po_id, part_id, po_qty, required_date, created_at
    FROM po_lines
    WHERE id IN ({','.join(['%s']*len(TARGET_LINE_IDS))});
    """, tuple(TARGET_LINE_IDS))
    line_cols = ['id', 'po_id', 'part_id', 'po_qty', 'required_date', 'created_at']
    line_snapshot = [dict(zip(line_cols, row)) for row in cur.fetchall()]
    assert len(line_snapshot) == 16, f"Expected 16 po_lines rows, found {len(line_snapshot)}"

    full_snapshot = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "po_master": po_snapshot,
        "po_lines": line_snapshot,
        "target_po_count": len(po_snapshot),
        "target_line_count": len(line_snapshot)
    }

    snapshot_file = r"c:\VSPL\VSPL smart\scratch\pre_cleanup_snapshot_7pos_23rows.json"
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(full_snapshot, f, indent=2, cls=CustomEncoder)
    print(f"Snapshot written successfully to {snapshot_file} ({len(po_snapshot)} po_master, {len(line_snapshot)} po_lines)")

    # 3. Reconfirm 0 operational records
    operational_tables = [
        'orders', 'work_orders', 'wo_engineering_readiness', 'wo_routes',
        'production_updates', 'production_movements', 'stage_wips',
        'nc_records', 'rejection_dispositions', 'conversions',
        'packing_records', 'packing_transactions', 'dispatches'
    ]
    for t in operational_tables:
        cur.execute(f"SELECT COUNT(*) FROM {t};")
        cnt = cur.fetchone()[0]
        assert cnt == 0, f"Table {t} has {cnt} rows, expected 0!"
    print("All operational table counts confirmed = 0")

    # 4. Check baseline protected counts
    protected_baselines = {
        'customers': 119,
        'parts': 5504,
        'customer_part_mappings': 5168,
        'customer_part_cross_references': 1891,
        'cc_materials': 15,
        'cc_inwards': 15,
        'cc_stock_units': 273,
        'cc_stock_ledger': 273,
        'users': 27,
        'audit_logs': 330
    }
    for t, expected in protected_baselines.items():
        cur.execute(f"SELECT COUNT(*) FROM {t};")
        cnt = cur.fetchone()[0]
        assert cnt == expected, f"Table {t} count mismatch: got {cnt}, expected {expected}"
    print("All protected master table counts confirmed baseline matching")

    print("\n==================================================")
    print("STEP 2: EXECUTING ATOMIC TRANSACTION")
    print("==================================================")

    try:
        # Step 2a: Delete po_lines
        cur.execute(f"""
        DELETE FROM po_lines
        WHERE id IN ({','.join(['%s']*len(TARGET_LINE_IDS))});
        """, tuple(TARGET_LINE_IDS))
        deleted_lines = cur.rowcount
        print(f"Deleted po_lines: {deleted_lines} rows (expected 16)")
        assert deleted_lines == 16, f"Expected exactly 16 po_lines deleted, got {deleted_lines}"

        # Step 2b: Delete po_master
        cur.execute(f"""
        DELETE FROM po_master
        WHERE id IN ({','.join(['%s']*len(TARGET_PO_IDS))});
        """, tuple(TARGET_PO_IDS))
        deleted_pos = cur.rowcount
        print(f"Deleted po_master: {deleted_pos} rows (expected 7)")
        assert deleted_pos == 7, f"Expected exactly 7 po_master deleted, got {deleted_pos}"

        # Step 2c: In-transaction post-assertions
        cur.execute("SELECT COUNT(*) FROM po_lines;")
        remaining_lines = cur.fetchone()[0]
        assert remaining_lines == 0, f"Expected 0 remaining po_lines, got {remaining_lines}"

        cur.execute("SELECT COUNT(*) FROM po_master;")
        remaining_pos = cur.fetchone()[0]
        assert remaining_pos == 0, f"Expected 0 remaining po_master, got {remaining_pos}"

        for t, expected in protected_baselines.items():
            cur.execute(f"SELECT COUNT(*) FROM {t};")
            cnt = cur.fetchone()[0]
            assert cnt == expected, f"Protected table {t} mutated inside txn: got {cnt}, expected {expected}"

        # Step 2d: COMMIT
        conn.commit()
        print("\n>>> TRANSACTION COMMITTED SUCCESSFULLY <<<")

    except Exception as e:
        conn.rollback()
        print(f"\n!!! TRANSACTION FAILED & ROLLED BACK: {e} !!!")
        raise

    print("\n==================================================")
    print("STEP 3: POST-COMMIT VERIFICATION")
    print("==================================================")

    cur.execute("SELECT COUNT(*) FROM po_master;")
    post_pos = cur.fetchone()[0]
    print(f"Final po_master count: {post_pos}")

    cur.execute("SELECT COUNT(*) FROM po_lines;")
    post_lines = cur.fetchone()[0]
    print(f"Final po_lines count: {post_lines}")

    target_po_nums = ['91160310', 'Schedule', '4510284161', 'MS/GEN/262251', 'ACNC/VSPL/18 /2026-27', 'PO-009-OEM/26-27', 'ACNC/VSPL/16/2026-27']
    for p in target_po_nums:
        cur.execute("SELECT COUNT(*) FROM po_master WHERE po_number = %s;", (p,))
        cnt = cur.fetchone()[0]
        print(f"Target PO '{p}' count in po_master: {cnt}")
        assert cnt == 0

    cur.execute("SELECT COUNT(*) FROM po_lines WHERE po_id NOT IN (SELECT id FROM po_master);")
    orphaned_lines = cur.fetchone()[0]
    print(f"Orphaned po_lines count: {orphaned_lines}")
    assert orphaned_lines == 0

    print("\nFinal Protected Tables Check:")
    for t, expected in protected_baselines.items():
        cur.execute(f"SELECT COUNT(*) FROM {t};")
        cnt = cur.fetchone()[0]
        print(f"  {t}: {cnt} (expected {expected})")
        assert cnt == expected

    cur.close()
    conn.close()
    connector.close()
    print("\nALL POST-VERIFICATIONS PASSED!")

if __name__ == "__main__":
    main()
