"""One-time cleanup of this LOCAL DEV database's test-run residue, ahead of loading
the real OMS Master workbook. NEVER run this against production -- it deletes every
Order/WorkOrder/Customer/Part that isn't part of the app's own baseline demo seed or
the already-approved VSPL Part Master Excel import.

What is kept (never touched):
  - Users (login accounts)
  - The app's own baseline demo seed: 4 customers (CUST-VALVE/PUMP/HEAVY/DEF),
    5 parts (BRZ-*), 4 orders (OAR-0001..0004), 7 work orders (WO-1001..1007) --
    see app/services/seed_service.py, the only place that ever creates these.
  - Every part_number that was actually inserted by scripts/import_part_master.py
    (recomputed here from the same source workbook, not guessed).

Everything else -- every OAR/WO/customer/part/PO/schedule created by this session's
pytest runs or manual E2E clicking -- is deleted, cascading through every table that
references work_orders/orders/customers/parts, inside one transaction.

Usage:
  python scripts/clean_dev_test_data.py [--commit]

Without --commit this is a dry run: it prints exactly what would be deleted and
changes nothing.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal
from app.models.order import Customer, Part, Order
from app.models.work_order import WorkOrder, WORoute
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord, PackingTransaction
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord
from app.models.rejection_disposition import RejectionDisposition
from app.models.conversion import Conversion
from app.models.production import ProductionUpdate
from app.models.master_data import POMaster, POLine, ScheduleMaster

BASELINE_CUSTOMER_CODES = {"CUST-VALVE", "CUST-PUMP", "CUST-HEAVY", "CUST-DEF"}
BASELINE_PART_NUMBERS = {"BRZ-BUSH-100", "BRZ-RING-250", "BRZ-SLV-400", "BRZ-GEAR-150", "BRZ-FLG-300"}
BASELINE_OAR_NUMBERS = {f"OAR-{i:04d}" for i in range(1, 5)}
BASELINE_WO_NUMBERS = {f"WO-100{i}" for i in range(1, 8)}

PART_MASTER_XLSX = r"C:\Users\Darshan\Downloads\Part Master - Control Plan(D&E) (2).xlsx"


def imported_part_numbers():
    """Recompute the exact set of part_numbers the approved Part Master import
    inserted, from the same source workbook -- not guessed, not re-derived by pattern."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from import_part_master import load_part_master_rows, classify
    records, _invalid = load_part_master_rows(PART_MASTER_XLSX)
    valid_by_key, _identical, conflict_groups = classify(records)
    conflict_keys = {k for k, _ in conflict_groups}
    return set(valid_by_key.keys()) - conflict_keys


def run(commit: bool):
    keep_parts = BASELINE_PART_NUMBERS | imported_part_numbers()

    db = SessionLocal()
    try:
        all_customers = db.query(Customer).all()
        del_customers = [c for c in all_customers if c.customer_code not in BASELINE_CUSTOMER_CODES]
        keep_customer_ids = {c.id for c in all_customers if c.customer_code in BASELINE_CUSTOMER_CODES}

        all_orders = db.query(Order).all()
        del_orders = [o for o in all_orders if o.oar_number not in BASELINE_OAR_NUMBERS]
        del_order_ids = {o.id for o in del_orders}

        all_wos = db.query(WorkOrder).all()
        del_wos = [w for w in all_wos if w.wo_number not in BASELINE_WO_NUMBERS or w.order_id in del_order_ids]
        del_wo_ids = {w.id for w in del_wos}

        all_parts = db.query(Part).all()
        del_parts = [p for p in all_parts if p.part_number not in keep_parts]
        del_part_ids = {p.id for p in del_parts}

        # Parts referenced by a KEPT order must never be deleted, even if they'd
        # otherwise look like test noise (defensive -- shouldn't happen given the
        # baseline seed's own parts are already in keep_parts, but never risk an FK
        # violation on a row we're keeping).
        keep_order_part_ids = {o.part_id for o in all_orders if o.id not in del_order_ids}
        del_part_ids -= keep_order_part_ids
        del_parts = [p for p in del_parts if p.id in del_part_ids]

        nc_records = db.query(NCRecord).filter(NCRecord.work_order_id.in_(del_wo_ids)).all() if del_wo_ids else []
        nc_ids = {n.id for n in nc_records}
        dispositions = db.query(RejectionDisposition).filter(RejectionDisposition.nc_record_id.in_(nc_ids)).all() if nc_ids else []
        conversions = db.query(Conversion).filter(
            (Conversion.source_wo_id.in_(del_wo_ids)) |
            (Conversion.destination_order_id.in_(del_order_ids)) |
            (Conversion.conversion_wo_id.in_(del_wo_ids))
        ).all() if (del_wo_ids or del_order_ids) else []
        po_masters = db.query(POMaster).all()  # none are baseline; all created post-hoc
        schedules = db.query(ScheduleMaster).all()  # same
        prod_updates_count = db.query(ProductionUpdate).filter(ProductionUpdate.work_order_id.in_(del_wo_ids)).count() if del_wo_ids else 0

        print("=" * 70)
        print("DEV TEST-DATA CLEANUP --", "COMMIT" if commit else "DRY RUN")
        print("=" * 70)
        print(f"Customers: keep {len(keep_customer_ids)}, delete {len(del_customers)} (of {len(all_customers)})")
        print(f"Orders (OAR): keep {len(all_orders) - len(del_orders)}, delete {len(del_orders)} (of {len(all_orders)})")
        print(f"Work Orders: keep {len(all_wos) - len(del_wos)}, delete {len(del_wos)} (of {len(all_wos)})")
        print(f"Parts: keep {len(all_parts) - len(del_parts)}, delete {len(del_parts)} (of {len(all_parts)})")
        print(f"NC Records to delete: {len(nc_records)}")
        print(f"Rejection Dispositions to delete: {len(dispositions)}")
        print(f"Conversions to delete: {len(conversions)}")
        print(f"PO Masters to delete: {len(po_masters)} (all -- none are baseline)")
        print(f"Schedules to delete: {len(schedules)} (all -- none are baseline)")
        print(f"Production Updates to delete: {prod_updates_count}")
        print()

        if not commit:
            print("Dry run only -- no database changes made. Re-run with --commit to apply.")
            return

        for d in dispositions:
            db.delete(d)
        for n in nc_records:
            db.delete(n)
        for c in conversions:
            db.delete(c)
        if del_wo_ids:
            db.query(ProductionUpdate).filter(ProductionUpdate.work_order_id.in_(del_wo_ids)).delete(synchronize_session=False)
            db.query(ProductionMovement).filter(ProductionMovement.work_order_id.in_(del_wo_ids)).delete(synchronize_session=False)
            db.query(StageWIP).filter(StageWIP.work_order_id.in_(del_wo_ids)).delete(synchronize_session=False)
            db.query(WORoute).filter(WORoute.work_order_id.in_(del_wo_ids)).delete(synchronize_session=False)
            db.query(PackingTransaction).filter(PackingTransaction.work_order_id.in_(del_wo_ids)).delete(synchronize_session=False)
            db.query(PackingRecord).filter(PackingRecord.work_order_id.in_(del_wo_ids)).delete(synchronize_session=False)
            db.query(Dispatch).filter(Dispatch.work_order_id.in_(del_wo_ids)).delete(synchronize_session=False)
        for w in del_wos:
            db.delete(w)
        for o in del_orders:
            db.delete(o)
        for p in po_masters:
            db.delete(p)  # cascades to POLine via model relationship
        for s in schedules:
            db.delete(s)
        for c in del_customers:
            db.delete(c)
        for p in del_parts:
            db.delete(p)

        db.commit()
        print("COMMITTED.")
        print(f"Final counts -- customers: {db.query(Customer).count()}, parts: {db.query(Part).count()}, "
              f"orders: {db.query(Order).count()}, work_orders: {db.query(WorkOrder).count()}")
    except Exception:
        db.rollback()
        print("ERROR -- transaction rolled back, no changes were persisted.", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    run(args.commit)
