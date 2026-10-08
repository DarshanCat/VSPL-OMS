"""China constraint suite: every CHECK constraint and unique index on the cc_* tables, proven by
inserting bad rows into an isolated in-memory SQLite database (nothing on disk).

SQLite does not enforce foreign keys by default, so FK integrity is not covered here.
Runs as a pytest test (one assertion over all checks) and as a script:
    python tests/test_cc_constraints.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # lets `python tests/test_cc_constraints.py` work

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import *  # noqa: F401,F403  (registers every table)
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WOStatus
from app.models import continuous_casting as cc

EXPECTED_CHECKS = 103   # 69 through Phase 7, +8 Phase 8 (split shape, own parent), +26 Phase 9 (hold/scrap/adjustment shapes)


def run_checks():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert engine.url.database == ":memory:"
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    results = []

    def ok(label, cond):
        results.append((label, bool(cond)))

    cust = Customer(customer_code="C1", name="Cust")
    part = Part(part_number="P1", description="p")
    db.add_all([cust, part])
    db.flush()
    order = Order(oar_number="OAR-1", customer_id=cust.id, part_id=part.id, customer_po="PO",
                  po_qty=10, max_batch_size=10, status=OrderStatus.ACCEPT)
    db.add(order)
    db.flush()

    def mk_wo(n):
        w = WorkOrder(wo_number=n, order_id=order.id, physical_wo_qty=10, current_stage="F1",
                      projected_final_good=10, status=WOStatus.IN_PRODUCTION)
        db.add(w)
        db.flush()
        return w

    wo1, wo2 = mk_wo("WO-T1"), mk_wo("WO-T2")
    db.commit()

    def rejects(label, build):
        """The row must be rejected by a database constraint."""
        try:
            db.add(build())
            db.flush()
            db.rollback()
            ok(label + " [should reject]", False)
        except IntegrityError:
            db.rollback()
            ok(label + " [rejected]", True)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            ok(label + f" [wrong error {type(e).__name__}]", False)

    def accepts(label, build):
        try:
            obj = build()
            db.add(obj)
            db.flush()
            db.commit()
            ok(label + " [accepted]", True)
            return obj
        except Exception as e:  # noqa: BLE001
            db.rollback()
            ok(label + f" [wrongly rejected: {type(e).__name__}: {e}]", False)

    # ---- material
    C = cc.ContinuousCastingMaterial
    mat = accepts("valid material", lambda: C(material_code="M1", grade="G", section="ROUND", stock_dimension_a_mm=200))
    rejects("material dim_a = 0", lambda: C(material_code="M2", grade="G", section="ROUND", stock_dimension_a_mm=0))
    rejects("material duplicate code", lambda: C(material_code="M1", grade="G", section="ROUND", stock_dimension_a_mm=200))

    # ---- inward
    I = cc.ContinuousCastingInward

    def inw(n, pieces=3, length=3000):
        return I(inward_number=n, material_id=mat.id, grade="G", section="ROUND", stock_dimension_a_mm=200,
                 received_piece_count=pieces, received_total_length_mm=length)

    inward = accepts("valid inward", lambda: inw("INW-001"))
    rejects("inward negative pieces", lambda: inw("INW-002", pieces=-1))
    rejects("inward negative length", lambda: inw("INW-003", length=-5))
    rejects("inward duplicate number", lambda: inw("INW-001"))

    # ---- stock unit
    U = cc.ContinuousCastingStockUnit

    def unit(n, orig=1000, rem=1000, res=0, iss=0, con=0, parent=None):
        return U(unit_number=n, inward_id=inward.id, original_length_mm=orig, remaining_length_mm=rem,
                 reserved_length_mm=res, issued_length_mm=iss, consumed_length_mm=con, parent_unit_id=parent)

    u1 = accepts("valid unit", lambda: unit("UNIT-001"))
    accepts("valid unit partly committed", lambda: unit("UNIT-002", res=400, iss=300))
    rejects("unit original = 0", lambda: unit("UNIT-X1", orig=0, rem=0))
    rejects("unit negative remaining", lambda: unit("UNIT-X2", rem=-1))
    rejects("unit negative reserved", lambda: unit("UNIT-X3", res=-1))
    rejects("unit reserved+issued > remaining", lambda: unit("UNIT-X4", rem=500, res=300, iss=300))
    rejects("unit remaining+consumed > original", lambda: unit("UNIT-X5", orig=1000, rem=800, con=300))
    accepts("valid remnant child unit", lambda: unit("UNIT-009", orig=700, rem=700, parent=u1.id))
    rejects("unit duplicate number", lambda: unit("UNIT-001"))

    def own_parent():
        x = unit("UNIT-X9")
        x.id = __import__("uuid").uuid4()
        x.parent_unit_id = x.id
        return x

    rejects("unit is its own parent", own_parent)

    # ---- routing
    R = cc.ContinuousCastingRouting

    def rt(wo, ver, status="DRAFT", src="CONTINUOUS_CASTING", full=True, **kw):
        d = dict(work_order_id=wo.id, version=ver, material_source=src, status=status)
        if full and src == "CONTINUOUS_CASTING":
            d.update(required_grade="G", required_section="ROUND", blank_length_mm=100,
                     planned_blanks=10, gross_required_length_mm=1200)
        d.update(kw)
        return R(**d)

    r1 = accepts("routing v1 ACTIVE", lambda: rt(wo1, 1, "ACTIVE"))
    rejects("second ACTIVE routing same WO", lambda: rt(wo1, 2, "ACTIVE"))
    rejects("duplicate (wo, version)", lambda: rt(wo1, 1, "DRAFT"))
    accepts("DRAFT v2 alongside ACTIVE v1", lambda: rt(wo1, 2, "DRAFT"))
    accepts("ACTIVE routing on a different WO", lambda: rt(wo2, 1, "ACTIVE"))
    rejects("routing version 0", lambda: rt(wo2, 0, "DRAFT"))
    rejects("routing invalid material_source", lambda: rt(wo2, 5, "DRAFT", src="BOGUS"))
    rejects("CC routing missing required fields", lambda: rt(wo2, 6, "DRAFT", full=False))
    accepts("F1_PRODUCTION routing without CC fields", lambda: rt(wo2, 7, "DRAFT", src="F1_PRODUCTION"))
    rejects("routing blank_length 0", lambda: rt(wo2, 8, "DRAFT", blank_length_mm=0))
    rejects("routing negative kerf", lambda: rt(wo2, 9, "DRAFT", kerf_mm=-1))
    rejects("routing finished_axial_length 0", lambda: rt(wo2, 10, "DRAFT", finished_axial_length_mm=0))
    accepts("routing finished_axial_length positive", lambda: rt(wo2, 11, "DRAFT", finished_axial_length_mm=100))
    r1.status = "SUPERSEDED"
    db.flush()
    accepts("new ACTIVE after v1 superseded", lambda: rt(wo1, 3, "ACTIVE"))
    db.commit()

    # ---- allocation
    A = cc.ContinuousCastingAllocation

    def al(n, routing, unit_, planned=500, res=0, iss=0, con=0):
        return A(allocation_number=n, routing_id=routing.id, stock_unit_id=unit_.id, planned_length_mm=planned,
                 reserved_length_mm=res, issued_length_mm=iss, consumed_length_mm=con)

    a1 = accepts("valid allocation", lambda: al("ALC-001", r1, u1, res=200, iss=100))
    rejects("duplicate (routing, unit)", lambda: al("ALC-002", r1, u1))
    rejects("alloc reserved+issued > planned", lambda: al("ALC-003", r1, u1, planned=100, res=80, iss=80))
    rejects("alloc negative planned", lambda: al("ALC-004", r1, u1, planned=-1))
    rejects("alloc negative consumed", lambda: al("ALC-005", r1, u1, con=-1))
    db.commit()

    # ---- stock ledger
    L = cc.ContinuousCastingStockLedger

    def lg(n, mtype="RESERVE", length=100, crid=None, pieces=None):
        return L(transaction_number=n, movement_type=mtype, inward_id=inward.id, stock_unit_id=u1.id,
                 allocation_id=a1.id, length_mm=length, client_request_id=crid, piece_qty=pieces)

    accepts("valid ledger row", lambda: lg("TXN-001", crid="REQ-1"))
    rejects("ledger invalid movement type", lambda: lg("TXN-X1", mtype="BOGUS"))
    rejects("ledger negative length", lambda: lg("TXN-X2", length=-1))
    rejects("ledger negative pieces", lambda: lg("TXN-X3", pieces=-1))
    rejects("ledger duplicate client_request_id", lambda: lg("TXN-X4", crid="REQ-1"))
    rejects("ledger duplicate transaction number", lambda: lg("TXN-001", crid="REQ-9"))
    accepts("ledger no idempotency key (1st)", lambda: lg("TXN-002"))
    accepts("ledger no idempotency key (2nd, NULLs allowed)", lambda: lg("TXN-003"))
    ok("tuple contains SPLIT_OUT and SPLIT_IN",
       "SPLIT_OUT" in cc.LEDGER_MOVEMENT_TYPES and "SPLIT_IN" in cc.LEDGER_MOVEMENT_TYPES)
    ok("tuple has exactly 13 types (ADJUSTMENT split into _IN/_OUT, HOLD_RELEASE added)",
       len(cc.LEDGER_MOVEMENT_TYPES) == 13 and len(set(cc.LEDGER_MOVEMENT_TYPES)) == 13)
    ok("tuple has no directionless ADJUSTMENT",
       "ADJUSTMENT" not in cc.LEDGER_MOVEMENT_TYPES and "ADJUSTMENT_IN" in cc.LEDGER_MOVEMENT_TYPES
       and "ADJUSTMENT_OUT" in cc.LEDGER_MOVEMENT_TYPES and "HOLD_RELEASE" in cc.LEDGER_MOVEMENT_TYPES)
    split_peer = db.query(U).filter_by(unit_number="UNIT-009").one()      # a second unit for split rows
    SPLITS = ("SPLIT_OUT", "SPLIT_IN")
    HOLDS = ("HOLD", "HOLD_RELEASE")
    DISPOSALS = ("SCRAP", "ADJUSTMENT_IN", "ADJUSTMENT_OUT")

    def split_row(n, mtype, **kw):
        # a split row names the OTHER unit, has no allocation and no piece_qty (Phase 8)
        row = lg(n, mtype=mtype, **{k: v for k, v in kw.items() if k in ("length",)})
        row.allocation_id, row.related_stock_unit_id = None, kw.get("related", split_peer.id)
        row.piece_qty = kw.get("pieces")
        return row

    def shaped(n, mtype, length=None, reason="because", reference="REF-1", alloc=False, related=False, pieces=None):
        # HOLD/HOLD_RELEASE: zero length + reason; SCRAP/ADJUSTMENT_*: positive length + reason + reference (Phase 9)
        row = lg(n, mtype=mtype, length=(0 if mtype in HOLDS else 100) if length is None else length)
        row.allocation_id = a1.id if alloc else None
        row.related_stock_unit_id = split_peer.id if related else None
        row.piece_qty, row.reason = pieces, reason
        row.reference = reference if mtype in DISPOSALS else None
        return row

    for mtype in cc.LEDGER_MOVEMENT_TYPES:
        if mtype in SPLITS:
            accepts(f"ledger type {mtype}", lambda m=mtype: split_row(f"TXN-T-{m}", m))
        elif mtype in HOLDS or mtype in DISPOSALS:
            accepts(f"ledger type {mtype}", lambda m=mtype: shaped(f"TXN-T-{m}", m))
        else:
            accepts(f"ledger type {mtype}", lambda m=mtype: lg(f"TXN-T-{m}", mtype=m))
    rejects("HOLD with a length", lambda: shaped("TXN-H1", "HOLD", length=5))
    rejects("HOLD_RELEASE with a length", lambda: shaped("TXN-H2", "HOLD_RELEASE", length=5))
    rejects("HOLD without a reason", lambda: shaped("TXN-H3", "HOLD", reason=None))
    rejects("HOLD with an allocation", lambda: shaped("TXN-H4", "HOLD", alloc=True))
    rejects("HOLD with a related unit", lambda: shaped("TXN-H5", "HOLD", related=True))
    rejects("HOLD_RELEASE with piece_qty", lambda: shaped("TXN-H6", "HOLD_RELEASE", pieces=1))
    rejects("SCRAP of zero length", lambda: shaped("TXN-D1", "SCRAP", length=0))
    rejects("SCRAP without a reason", lambda: shaped("TXN-D2", "SCRAP", reason=None))
    rejects("SCRAP without a reference", lambda: shaped("TXN-D3", "SCRAP", reference=None))
    rejects("SCRAP with an allocation", lambda: shaped("TXN-D4", "SCRAP", alloc=True))
    rejects("SCRAP with piece_qty", lambda: shaped("TXN-D5", "SCRAP", pieces=1))
    rejects("ADJUSTMENT_IN with a related unit", lambda: shaped("TXN-D6", "ADJUSTMENT_IN", related=True))
    rejects("ADJUSTMENT_OUT without a reference", lambda: shaped("TXN-D7", "ADJUSTMENT_OUT", reference=None))
    rejects("ADJUSTMENT_OUT of zero length", lambda: shaped("TXN-D8", "ADJUSTMENT_OUT", length=0))
    rejects("legacy directionless ADJUSTMENT", lambda: lg("TXN-D9", mtype="ADJUSTMENT"))
    accepts("client_request_id on a SCRAP", lambda: (lambda r: (setattr(r, "client_request_id", "KEY-1"), r)[1])(
        shaped("TXN-K1", "SCRAP")))
    rejects("duplicate client_request_id", lambda: (lambda r: (setattr(r, "client_request_id", "KEY-1"), r)[1])(
        shaped("TXN-K2", "ADJUSTMENT_OUT")))
    rejects("unit scrapped negative", lambda: (lambda x: (setattr(x, "scrapped_length_mm", -1), x)[1])(
        unit("UNIT-S1")))
    rejects("unit remaining+consumed+scrapped > original", lambda: (lambda x: (setattr(x, "scrapped_length_mm", 200), x)[1])(
        unit("UNIT-S2", rem=800, con=100)))
    accepts("unit remaining+consumed+scrapped == original", lambda: (lambda x: (setattr(x, "scrapped_length_mm", 100), x)[1])(
        unit("UNIT-S3", rem=800, con=100)))
    rejects("split row without related unit", lambda: split_row("TXN-S1", "SPLIT_OUT", related=None))
    rejects("split row related to itself", lambda: split_row("TXN-S2", "SPLIT_IN", related=u1.id))
    rejects("split row with piece_qty", lambda: split_row("TXN-S3", "SPLIT_OUT", pieces=1))
    rejects("split row of zero length", lambda: split_row("TXN-S4", "SPLIT_OUT", length=0))
    rejects("split row with an allocation", lambda: (lambda r: (setattr(r, "allocation_id", a1.id), r)[1])(
        split_row("TXN-S5", "SPLIT_OUT")))
    rejects("non-split row naming a related unit", lambda: (lambda r: (setattr(r, "related_stock_unit_id",
                                                                                split_peer.id), r)[1])(lg("TXN-S6")))
    rejects("second SPLIT_IN for one unit", lambda: split_row("TXN-S7", "SPLIT_IN"))
    for i, bad in enumerate(("SPLIT", "split_out", "SPLIT_OUT ", "TRANSFER", "", "hold_release", "ADJUSTMENT_")):
        rejects(f"ledger near-miss type {bad!r}", lambda b=bad, i=i: lg(f"TXN-BAD-{i}", mtype=b))
    ddl = db.execute(text("SELECT sql FROM sqlite_master WHERE name='cc_stock_ledger'")).scalar()
    ok("DB constraint text lists SPLIT_OUT and SPLIT_IN", "'SPLIT_OUT'" in ddl and "'SPLIT_IN'" in ddl)
    ok("DB constraint text lists HOLD_RELEASE, ADJUSTMENT_IN and ADJUSTMENT_OUT",
       all(f"'{t}'" in ddl for t in ("HOLD_RELEASE", "ADJUSTMENT_IN", "ADJUSTMENT_OUT")))
    db.commit()

    row = db.query(L).filter_by(transaction_number="TXN-001").one()
    try:
        row.reason = "tamper"
        db.flush()
        db.rollback()
        ok("ledger UPDATE blocked", False)
    except ValueError:
        db.rollback()
        ok("ledger UPDATE blocked", True)
    row = db.query(L).filter_by(transaction_number="TXN-001").one()
    try:
        db.delete(row)
        db.flush()
        db.rollback()
        ok("ledger DELETE blocked", False)
    except ValueError:
        db.rollback()
        ok("ledger DELETE blocked", True)

    # ---- cut record
    K = cc.ContinuousCastingCutRecord

    def ct(n, **kw):
        d = dict(cut_number=n, work_order_id=wo1.id, allocation_id=a1.id, stock_unit_id=u1.id,
                 planned_blanks=5, actual_good_blanks=4, rejected_blanks=1, blank_length_mm=100)
        d.update(kw)
        return K(**d)

    accepts("valid cut record", lambda: ct("CUT-001"))
    rejects("cut negative good blanks", lambda: ct("CUT-X1", actual_good_blanks=-1))
    rejects("cut blank_length 0", lambda: ct("CUT-X2", blank_length_mm=0))
    rejects("cut invalid reconciliation status", lambda: ct("CUT-X3", reconciliation_status="BOGUS"))
    rejects("cut negative remnant length", lambda: ct("CUT-X4", retained_remnant_length_mm=-1))
    db.commit()

    db.close()
    engine.dispose()
    return results


def test_every_constraint_check_passes():
    results = run_checks()
    failed = [label for label, good in results if not good]
    assert not failed, failed
    assert len(results) == EXPECTED_CHECKS, len(results)


if __name__ == "__main__":
    results = run_checks()
    for label, good in results:
        print(("PASS  " if good else "FAIL  ") + label)
    passed = sum(1 for _, good in results if good)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) == EXPECTED_CHECKS else 1)
