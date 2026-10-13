"""One-off, guarded migration: drop the legacy `packing_transactions.packed_qty` column,
after backfilling its historical values into `packed_quantity` (the column the current
`PackingTransaction` model actually uses). Validated on disposable copies of the Stage 1
backup -- see the OMS local-drift investigation reports for the full forensic evidence.

Why this is not in app/core/database.py's auto_migrate_schema(): that function is
purely additive (ADD COLUMN IF NOT EXISTS style) by design. This migration is the first
one that destroys a column, so it is deliberately kept as a standalone, explicit,
opt-in script instead of folded into the automatic startup path.

SAFETY GATES (all enforced, in order, before any write):
  1. --db PATH is required; there is no default.
  2. PATH is rejected outright if it resolves to either known original database:
       - backend/vspl_smes.db (the canonical local dev database)
       - the parent-directory stray database next to the repo root
  3. --execute must be passed explicitly; without it the script only prints what it
     would do (dry run) and makes no connection that could write.
  4. The resolved absolute target path is printed before any write happens.
  5. Everything runs inside a single transaction; any exception triggers a rollback
     and the script exits non-zero without having committed anything.
  6. If a row's pre-existing `packed_quantity` is already non-zero/non-null and
     disagrees with `packed_qty`, the script ABORTS and reports every such row --
     it never guesses a reconciliation rule.

RERUN SAFETY: the backfill and the column drop are gated behind a single
`PRAGMA table_info` check for `packed_qty`'s presence. If the column is already
gone, the script performs a safe no-op and exits 0 -- it never re-issues the
UPDATE or the ALTER TABLE in that case (both would error once the column is gone).

RECOVERY: if anything looks wrong after a real run, restore the database file
from a backup taken via a read-only `sqlite3.Connection.backup()` snapshot made
immediately before running this script with --execute; this script does not take
its own backup, so the caller must create and verify one beforehand (per the OMS
Stage 1 backup-and-verify procedure: size, PRAGMA integrity_check, row counts,
SHA-256, all re-checked against the live source right before running).

Usage:
    python scripts/migrate_packing_transactions_packed_qty.py --db <disposable_copy.db>            # dry run
    python scripts/migrate_packing_transactions_packed_qty.py --db <disposable_copy.db> --execute   # apply
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


def _reject_if_original(db_path: Path) -> None:
    resolved = db_path.resolve()
    if resolved in FORBIDDEN_PATHS:
        print(f"REFUSING: '{resolved}' is an original database, not a disposable copy. Aborting.", file=sys.stderr)
        sys.exit(2)


def migrate(conn: sqlite3.Connection) -> dict:
    """Runs inside an already-open connection/transaction. Returns a summary dict.
    Raises on any detected conflict or integrity problem -- the caller rolls back."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(packing_transactions)").fetchall()]
    if "packed_qty" not in cols:
        return {"action": "no_op", "reason": "packed_qty already absent"}

    row_count_before = conn.execute("SELECT COUNT(*) FROM packing_transactions").fetchone()[0]

    # Abort on any row whose existing packed_quantity already looks genuinely populated
    # (non-null, non-zero) and disagrees with packed_qty -- never invent a reconciliation rule.
    conflicts = conn.execute(
        "SELECT id, packed_qty, packed_quantity FROM packing_transactions "
        "WHERE packed_quantity IS NOT NULL AND packed_quantity != 0 AND packed_quantity != packed_qty"
    ).fetchall()
    if conflicts:
        raise RuntimeError(
            f"ABORTING: {len(conflicts)} row(s) have a non-zero packed_quantity that disagrees "
            f"with packed_qty -- refusing to guess a reconciliation rule. Rows: {conflicts}"
        )

    cur = conn.execute(
        "UPDATE packing_transactions SET packed_quantity = packed_qty "
        "WHERE packed_qty IS NOT NULL AND (packed_quantity IS NULL OR packed_quantity = 0)"
    )
    rows_backfilled = cur.rowcount

    # Preservation check: every row's packed_quantity must now equal its original packed_qty.
    after_backfill = conn.execute("SELECT id, packed_qty, packed_quantity FROM packing_transactions").fetchall()
    lost = [(rid, qty, quantity) for rid, qty, quantity in after_backfill if quantity != qty]
    if lost:
        raise RuntimeError(f"ABORTING: {len(lost)} row(s) lost their historical quantity after backfill: {lost}")

    conn.execute("ALTER TABLE packing_transactions DROP COLUMN packed_qty")

    row_count_after = conn.execute("SELECT COUNT(*) FROM packing_transactions").fetchone()[0]
    if row_count_after != row_count_before:
        raise RuntimeError(f"ABORTING: row count changed ({row_count_before} -> {row_count_after})")

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"ABORTING: PRAGMA integrity_check reported '{integrity}', not 'ok'")

    fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    new_fk_violations = [v for v in fk_violations if v[0] == "packing_transactions"]
    if new_fk_violations:
        raise RuntimeError(f"ABORTING: new foreign_key_check violations on packing_transactions: {new_fk_violations}")

    return {
        "action": "migrated",
        "row_count_before": row_count_before,
        "row_count_after": row_count_after,
        "rows_backfilled": rows_backfilled,
        "integrity_check": integrity,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="Path to a DISPOSABLE sqlite copy. Never an original database.")
    parser.add_argument("--execute", action="store_true", help="Actually apply the migration. Without this flag, dry-run only.")
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
        result = migrate(conn)
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
