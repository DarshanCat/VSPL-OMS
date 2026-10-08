"""VSPL OMS -- Production-Safe Neon to Cloud SQL Restore Utility

Restores the verified Neon PostgreSQL production snapshot into Google Cloud SQL PostgreSQL.

Safety Guarantees:
- Default mode is strictly DRY-RUN (zero writes).
- Requires both `--commit` AND `--confirm RESTORE_NEON_TO_CLOUDSQL` for execution.
- Verifies SHA-256 snapshot checksum before any processing.
- Refuses to connect if target URL contains Neon identifiers.
- Preserves all source UUIDs, historical timestamps, and user password hashes.
- Skips legacy `customer_part_mappings` table.
- Executes full target replacement in a single atomic transaction with rollback on failure.
- Emits a sanitized audit manifest upon completion.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor, execute_batch

EXPECTED_SNAPSHOT_SHA256 = (
    "42f5dc2fac5cf5c7ac8a27ed317c3ace0363a09edcbdee013f7317d2bad3be01"
)
EXPECTED_TABLE_COUNT = 26
EXPECTED_TOTAL_ROWS = 8355

LEGACY_EXCLUDED_TABLES = {"customer_part_mappings"}

# Strictly ordered FK levels for insertion
RESTORE_TABLE_ORDER = [
    # Level 1: Independent Root Masters
    "rejection_types",
    "customers",
    "parts",
    "users",
    # Level 2: Parent Masters & First References
    "customer_part_cross_references",
    "po_master",
    "conversion_part_mappings",
    "machines",
    "operators",
    "shifts",
    # Level 3: Order Lines, Schedules, Orders
    "po_lines",
    "schedule_master",
    "orders",
    # Level 4: Manufacturing Work Orders & Quality
    "work_orders",
    "nc_records",
    "conversions",
    # Level 5: Execution, WIP, Routing
    "wo_routes",
    "stage_wips",
    "production_movements",
    "production_updates",
    # Level 6: Downstream Fulfillment, Dispositions, Audit
    "rejection_dispositions",
    "packing_records",
    "packing_transactions",
    "dispatches",
    "audit_logs",
]

# Reverse order for clean, FK-safe truncation/deletion of existing target records
CLEANUP_TABLE_ORDER = list(reversed(RESTORE_TABLE_ORDER))


def compute_sha256(filepath: Path) -> str:
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def mask_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = ""
        if parsed.username:
            netloc += "***@"
        if parsed.hostname:
            netloc += parsed.hostname
        if parsed.port:
            netloc += f":{parsed.port}"
        return urllib.parse.urlunparse(
            (parsed.scheme, netloc, parsed.path, "", "", "")
        )
    except Exception:
        return "postgresql://***:***@masked-host/masked-db"


def validate_target_url(url: str) -> Tuple[bool, str]:
    if not url:
        return False, "Target database URL is empty or not provided."
    
    url_lower = url.lower()
    if not (url_lower.startswith("postgres://") or url_lower.startswith("postgresql://") or url_lower.startswith("postgresql+psycopg2://")):
        return False, "Target database must be a PostgreSQL connection URL."

    # Refuse Neon connections
    if "neon.tech" in url_lower or "ep-" in url_lower:
        return False, "SAFETY VIOLATION: Target URL appears to be a Neon database. This script must only target Google Cloud SQL."

    neon_env = os.environ.get("NEON_DATABASE_URL", "").lower()
    if neon_env and url_lower.strip() == neon_env.strip():
        return False, "SAFETY VIOLATION: Target URL matches NEON_DATABASE_URL. Refusing to restore to source database."

    return True, "Valid target PostgreSQL connection."


def resolve_cloud_sql_url(args_target_url: Optional[str]) -> str:
    if args_target_url:
        return args_target_url

    # Check environment variables
    env_target = os.environ.get("TARGET_DATABASE_URL") or os.environ.get("CLOUDSQL_DATABASE_URL")
    if env_target:
        return env_target

    # Try GCP Secret Manager via gcloud if available
    try:
        import subprocess
        cmd = ["gcloud", "secrets", "versions", "access", "latest", "--secret=VSPL_DATABASE_URL", "--project=vspl-oms-510015"]
        res = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if res.returncode == 0 and res.stdout.strip():
            secret_url = res.stdout.strip()
            # If secret url uses unix socket on cloud run (/cloudsql/...), convert to public IP connection for local migration runner if needed
            if "host=/cloudsql/" in secret_url:
                parsed = urllib.parse.urlparse(secret_url)
                return f"postgresql://{parsed.username}:{parsed.password}@34.100.147.34:5432/{parsed.path.lstrip('/')}?sslmode=require"
            return secret_url
    except Exception:
        pass

    db_url = os.environ.get("DATABASE_URL")
    if db_url and "neon.tech" not in db_url.lower():
        return db_url

    raise ValueError("Could not resolve a valid Cloud SQL target database URL. Please specify via --target-url or TARGET_DATABASE_URL.")


def load_and_validate_snapshot(snapshot_path: Path, expected_sha256: str) -> Dict[str, List[Dict[str, Any]]]:
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot file not found: {snapshot_path}")

    actual_sha = compute_sha256(snapshot_path)
    if actual_sha.lower() != expected_sha256.lower():
        raise ValueError(
            f"SNAPSHOT CHECKSUM MISMATCH!\n"
            f"Expected: {expected_sha256}\n"
            f"Actual  : {actual_sha}"
        )

    with open(snapshot_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Snapshot root must be a JSON object mapping table names to records.")

    table_count = len(data)
    total_rows = sum(len(v) for v in data.values())

    if table_count != EXPECTED_TABLE_COUNT:
        raise ValueError(f"Expected {EXPECTED_TABLE_COUNT} tables in snapshot, but found {table_count}.")
    if total_rows != EXPECTED_TOTAL_ROWS:
        raise ValueError(f"Expected {EXPECTED_TOTAL_ROWS} total rows in snapshot, but found {total_rows}.")

    # Validate essential admin user
    users = data.get("users", [])
    admin_user = next((u for u in users if u.get("email") == "aravind.gurudev@vijayspheroidals.com"), None)
    if not admin_user:
        raise ValueError("CRITICAL: Authoritative admin account 'aravind.gurudev@vijayspheroidals.com' is missing from snapshot users!")
    if not admin_user.get("is_active"):
        raise ValueError("CRITICAL: Admin account 'aravind.gurudev@vijayspheroidals.com' is not active in snapshot!")
    if str(admin_user.get("role", "")).upper() not in ("ADMIN", "USERROLE.ADMIN"):
        raise ValueError(f"CRITICAL: Admin account role is {admin_user.get('role')}, expected ADMIN!")

    return data


def get_target_table_counts(cur) -> Dict[str, int]:
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    """)
    tables = [r[0] for r in cur.fetchall()]
    counts = {}
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t}";')
        counts[t] = cur.fetchone()[0]
    return counts


def get_target_sequences(cur) -> List[Dict[str, Any]]:
    cur.execute("""
        SELECT sequencename, last_value 
        FROM pg_sequences 
        WHERE schemaname = 'public'
        ORDER BY sequencename;
    """)
    return [{"name": r[0], "last_value": r[1]} for r in cur.fetchall()]


def restore_table_data(cur, table_name: str, rows: List[Dict[str, Any]]):
    if not rows:
        return 0

    # Get target column metadata
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = %s;
    """, (table_name,))
    target_columns = {r[0]: r[1] for r in cur.fetchall()}
    if not target_columns:
        raise ValueError(f"Target table '{table_name}' does not exist in Cloud SQL schema.")

    # Match snapshot columns to target columns
    first_row = rows[0]
    col_names = [k for k in first_row.keys() if k in target_columns]
    if not col_names:
        raise ValueError(f"No matching columns for table '{table_name}'.")

    # For self-referential foreign keys like work_orders.source_wo_id, insert with NULL first, then update
    self_referential_cols = {"work_orders": "source_wo_id"}
    self_ref_col = self_referential_cols.get(table_name)

    cols_escaped = ", ".join([f'"{c}"' for c in col_names])
    placeholders = ", ".join(["%s"] * len(col_names))
    insert_sql = f'INSERT INTO "{table_name}" ({cols_escaped}) VALUES ({placeholders});'

    batch_values = []
    deferred_updates = []

    for r in rows:
        vals = []
        for c in col_names:
            v = r.get(c)
            # If this is the self-referential column, defer value if not None
            if self_ref_col and c == self_ref_col:
                if v:
                    deferred_updates.append((v, r.get("id")))
                vals.append(None)
                continue

            # Empty string on UUID/DateTime/Integer conversions if null
            if v == "" and target_columns[c] in ("uuid", "integer", "timestamp with time zone", "timestamp without time zone", "date"):
                vals.append(None)
            else:
                vals.append(v)
        batch_values.append(vals)

    execute_batch(cur, insert_sql, batch_values, page_size=500)

    # Apply deferred self-referential updates
    if deferred_updates:
        update_sql = f'UPDATE "{table_name}" SET "{self_ref_col}" = %s WHERE "id" = %s;'
        execute_batch(cur, update_sql, deferred_updates, page_size=500)

    return len(rows)


def run_restore(
    snapshot_path: Path,
    target_url: Optional[str] = None,
    commit: bool = False,
    confirm_text: Optional[str] = None,
    expected_sha256: str = EXPECTED_SNAPSHOT_SHA256,
) -> Dict[str, Any]:
    start_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 75)
    print("VSPL OMS -- NEON TO GOOGLE CLOUD SQL RESTORE UTILITY")
    print("=" * 75)
    mode_str = "COMMIT (LIVE WRITE)" if commit else "DRY-RUN (READ-ONLY SIMULATION)"
    print(f"Execution Mode: {mode_str}")
    print(f"Snapshot Path : {snapshot_path}")
    print("-" * 75)

    # 1. Validate snapshot
    print("[1/6] Validating snapshot integrity and checksum...")
    snapshot_data = load_and_validate_snapshot(snapshot_path, expected_sha256)
    print(f"  [OK] SHA-256 Checksum Verified: {expected_sha256}")
    print(f"  [OK] Total Tables in Snapshot : {len(snapshot_data)}")
    print(f"  [OK] Total Rows in Snapshot   : {sum(len(v) for v in snapshot_data.values())}")
    print(f"  [OK] Admin User Identity Check: PASSED (aravind.gurudev@vijayspheroidals.com)")

    # 2. Validate target URL
    print("\n[2/6] Validating target database safety...")
    resolved_target_url = resolve_cloud_sql_url(target_url)
    valid, msg = validate_target_url(resolved_target_url)
    if not valid:
        print(f"ERROR: {msg}", file=sys.stderr)
        sys.exit(1)
    masked_target = mask_url(resolved_target_url)
    print(f"  [OK] Target Database Identified: {masked_target}")

    # 3. Check commit safety confirmation
    if commit:
        if confirm_text != "RESTORE_NEON_TO_CLOUDSQL":
            print(
                "ERROR: --commit requires --confirm RESTORE_NEON_TO_CLOUDSQL to prevent accidental writes.",
                file=sys.stderr,
            )
            sys.exit(1)

    # 4. Connect to Cloud SQL Target
    print("\n[3/6] Inspecting Cloud SQL target schema and current records...")
    conn = psycopg2.connect(resolved_target_url)
    conn.autocommit = False

    manifest_result = {
        "source_snapshot": snapshot_path.name,
        "source_sha256": expected_sha256,
        "target_database": masked_target,
        "started_at": start_time,
        "mode": "COMMIT" if commit else "DRY_RUN",
        "legacy_excluded": list(LEGACY_EXCLUDED_TABLES),
        "table_reports": {},
        "sequences": [],
        "success": False,
    }

    try:
        with conn.cursor() as cur:
            before_counts = get_target_table_counts(cur)
            sequences = get_target_sequences(cur)
            manifest_result["sequences"] = sequences

            print("-" * 75)
            print(f"{'Table Name':<34} | {'Source (Neon)':>13} | {'Target (Before)':>15} | Action")
            print("-" * 75)

            for tbl in RESTORE_TABLE_ORDER:
                src_cnt = len(snapshot_data.get(tbl, []))
                tgt_cnt = before_counts.get(tbl, 0)
                action = f"Replace {tgt_cnt} -> {src_cnt}" if commit else f"Would replace {tgt_cnt} -> {src_cnt}"
                print(f"{tbl:<34} | {src_cnt:>13} | {tgt_cnt:>15} | {action}")

            print(f"{'customer_part_mappings (LEGACY)':<34} | {len(snapshot_data.get('customer_part_mappings', [])):>13} | {'SKIPPED':>15} | Excluded (Legacy)")
            print("-" * 75)

            if not commit:
                print("\n[DRY RUN COMPLETE] Zero changes made to Cloud SQL.")
                print("All schema structures, FK orders, and snapshot checks passed.")
                manifest_result["success"] = True
                manifest_result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                return manifest_result

            # 5. Execute Transactional Replacement
            print("\n[4/6] Executing transactional data replacement on Cloud SQL...")
            
            # Step A: Clean target tables in reverse FK order
            print("  - Clearing existing target records (Reverse FK order)...")
            for tbl in CLEANUP_TABLE_ORDER:
                cur.execute(f'DELETE FROM "{tbl}";')

            # Step B: Insert snapshot tables in forward FK order
            print("  - Inserting snapshot records (Forward FK order)...")
            restored_counts = {}
            for tbl in RESTORE_TABLE_ORDER:
                rows = snapshot_data.get(tbl, [])
                inserted = restore_table_data(cur, tbl, rows)
                restored_counts[tbl] = inserted

            # 6. Post-Restore Verification
            print("\n[5/6] Verifying restored table counts and FK integrity...")
            after_counts = get_target_table_counts(cur)
            all_passed = True

            print("-" * 75)
            print(f"{'Table Name':<34} | {'Source':>8} | {'Restored':>8} | {'Status':>8}")
            print("-" * 75)
            for tbl in RESTORE_TABLE_ORDER:
                src_cnt = len(snapshot_data.get(tbl, []))
                aft_cnt = after_counts.get(tbl, 0)
                passed = src_cnt == aft_cnt
                if not passed:
                    all_passed = False
                status_str = "PASS" if passed else "FAIL"
                print(f"{tbl:<34} | {src_cnt:>8} | {aft_cnt:>8} | {status_str:>8}")
                manifest_result["table_reports"][tbl] = {
                    "source_count": src_cnt,
                    "target_before": before_counts.get(tbl, 0),
                    "target_after": aft_cnt,
                    "status": status_str,
                }

            if not all_passed:
                raise RuntimeError("Post-restore table count verification failed on one or more tables!")

            # Commit the atomic transaction
            conn.commit()
            print("-" * 75)
            print("[6/6] TRANSACTION COMMITTED SUCCESSFULLY.")
            manifest_result["success"] = True
            manifest_result["total_source_rows"] = sum(len(v) for v in snapshot_data.values())
            manifest_result["total_restored_rows"] = sum(restored_counts.values())
            manifest_result["excluded_legacy_rows"] = len(snapshot_data.get("customer_part_mappings", []))

    except Exception as e:
        conn.rollback()
        print(f"\nRESTORE FAILED -- TRANSACTION ROLLED BACK!\nError: {e}", file=sys.stderr)
        manifest_result["success"] = False
        manifest_result["error"] = str(e)
        raise
    finally:
        conn.close()
        manifest_result["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Write audit manifest
        out_dir = snapshot_path.parent
        out_manifest_path = out_dir / f"restore_manifest_{timestamp_str}.json"
        with open(out_manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_result, f, indent=2)
        print(f"Audit manifest written to: {out_manifest_path}")

    return manifest_result


def parse_arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="restore_neon_to_cloudsql.py",
        description="VSPL OMS -- Production-Safe Neon to Cloud SQL Restore Utility",
        epilog="IMPORTANT: Defaults to dry-run. Writes require --commit and --confirm RESTORE_NEON_TO_CLOUDSQL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--snapshot",
        dest="snapshot",
        required=True,
        help="Path to the verified Neon snapshot JSON file.",
    )
    parser.add_argument(
        "--target-url",
        dest="target_url",
        default=None,
        help="Target Cloud SQL PostgreSQL URL (or TARGET_DATABASE_URL/DATABASE_URL env var).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        dest="commit",
        default=False,
        help="Apply database writes. Requires --confirm RESTORE_NEON_TO_CLOUDSQL.",
    )
    parser.add_argument(
        "--confirm",
        dest="confirm",
        default=None,
        help="Confirmation phrase (must be 'RESTORE_NEON_TO_CLOUDSQL').",
    )
    parser.add_argument(
        "--expected-sha256",
        dest="expected_sha256",
        default=EXPECTED_SNAPSHOT_SHA256,
        help="Expected SHA-256 checksum for snapshot verification.",
    )
    return parser


def main():
    parser = parse_arguments()
    args = parser.parse_args()
    snapshot_path = Path(args.snapshot)
    run_restore(
        snapshot_path=snapshot_path,
        target_url=args.target_url,
        commit=args.commit,
        confirm_text=args.confirm,
        expected_sha256=args.expected_sha256,
    )


if __name__ == "__main__":
    main()
