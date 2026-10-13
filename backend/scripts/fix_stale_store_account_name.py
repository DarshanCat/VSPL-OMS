"""One-off, guarded correction: update the stale seeded `store@vspl.com` account's
`full_name` from the old seed value ("Prakash Store Incharge") to the current seed
value in app/services/seed_service.py ("Krishna Murthy (Store)"). This does NOT touch
seed_database_if_empty() or any general seed-upsert/reconciliation behavior -- it is a
single, narrowly-scoped, guarded UPDATE for one already-identified row.

SAFETY GATES:
  1. --db PATH is required; no default.
  2. PATH is rejected if it resolves to either original database (backend/vspl_smes.db
     or the parent-directory stray database).
  3. --execute must be passed explicitly; without it, dry run only, no connection opened.
  4. The resolved absolute target path is printed before any write.
  5. The account is verified unique (exactly one row for email='store@vspl.com') before
     any UPDATE is attempted.
  6. The UPDATE predicate itself guards against a race: it only matches a row whose
     full_name is still exactly the old stale value, so a rerun (or a prior unrelated
     change) safely affects zero rows instead of overwriting something unexpected.
  7. id, role, is_active, and employee_id are re-read after the update and compared
     against their pre-update values; any difference aborts (rolls back) the script.

Usage:
    python scripts/fix_stale_store_account_name.py --db <disposable_copy.db>            # dry run
    python scripts/fix_stale_store_account_name.py --db <disposable_copy.db> --execute   # apply
"""
import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FORBIDDEN_PATHS = {
    (REPO_ROOT / "backend" / "vspl_smes.db").resolve(),
    (REPO_ROOT / "vspl_smes.db").resolve(),
}

EMAIL = "store@vspl.com"
OLD_NAME = "Prakash Store Incharge"
NEW_NAME = "Krishna Murthy (Store)"


def _reject_if_original(db_path: Path) -> None:
    resolved = db_path.resolve()
    if resolved in FORBIDDEN_PATHS:
        print(f"REFUSING: '{resolved}' is an original database, not a disposable copy. Aborting.", file=sys.stderr)
        sys.exit(2)


def fix(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT id, full_name, role, is_active, employee_id FROM users WHERE email = ?", (EMAIL,)
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"ABORTING: expected exactly 1 row for {EMAIL}, found {len(rows)}: {rows}")

    uid, full_name, role, is_active, employee_id = rows[0]
    if full_name != OLD_NAME:
        return {"action": "no_op", "reason": f"full_name is '{full_name}', not the expected stale value '{OLD_NAME}'"}

    cur = conn.execute(
        "UPDATE users SET full_name = ? WHERE email = ? AND full_name = ?",
        (NEW_NAME, EMAIL, OLD_NAME),
    )
    if cur.rowcount != 1:
        raise RuntimeError(f"ABORTING: expected to update exactly 1 row, updated {cur.rowcount}")

    uid2, full_name2, role2, is_active2, employee_id2 = conn.execute(
        "SELECT id, full_name, role, is_active, employee_id FROM users WHERE email = ?", (EMAIL,)
    ).fetchone()
    if (uid2, role2, is_active2, employee_id2) != (uid, role, is_active, employee_id):
        raise RuntimeError(
            "ABORTING: identity fields changed unexpectedly "
            f"(id/role/is_active/employee_id before={(uid, role, is_active, employee_id)} "
            f"after={(uid2, role2, is_active2, employee_id2)})"
        )
    if full_name2 != NEW_NAME:
        raise RuntimeError(f"ABORTING: full_name after update is '{full_name2}', expected '{NEW_NAME}'")

    return {"action": "updated", "id": uid, "old_name": OLD_NAME, "new_name": NEW_NAME}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="Path to a DISPOSABLE sqlite copy. Never an original database.")
    parser.add_argument("--execute", action="store_true", help="Actually apply the fix. Without this flag, dry-run only.")
    args = parser.parse_args()

    db_path = Path(args.db)
    _reject_if_original(db_path)
    if not db_path.is_file():
        print(f"REFUSING: '{db_path}' does not exist.", file=sys.stderr)
        sys.exit(2)

    resolved = db_path.resolve()
    print(f"Target database (absolute path): {resolved}")

    if not args.execute:
        print("Dry run only (pass --execute to apply). No connection opened, nothing was read or written.")
        return

    conn = sqlite3.connect(str(resolved))
    try:
        conn.execute("BEGIN")
        result = fix(conn)
        conn.commit()
        print(f"SUCCESS: {result}")
    except Exception as e:
        conn.rollback()
        print(f"FAILED, rolled back: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
