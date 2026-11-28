"""Route card: a read-only, live printable card per work order (docs/route-card-architecture.md)."""
from datetime import datetime

from tests.test_setup_planning import env, mkwo, mksetup, T, d, WorkOrder  # noqa: F401
from app.models.mrb import MRBReview
from app.models.vendor import VendorDispatch
from app.models.production_movement import StageWIP, ProductionMovement
from app.models.work_order import WORoute
from app.services.route_card_service import build_route_card


def _mrb(env, wo, stage, status, ok, rej=0, v_ok=None, v_rej=None, n=[0]):
    n[0] += 1
    env.db.add(MRBReview(mrb_number=f"MRB-R{n[0]:04d}", work_order_id=wo.id, stage=stage, reported_ok_qty=ok,
                         reported_reject_qty=rej, status=status, verified_ok_qty=v_ok, verified_reject_qty=v_rej))
    env.db.commit()


def _gate(card, gate):
    return next(g for g in card["gates"] if g["gate"] == gate)


def test_unknown_work_order_returns_none(env):
    assert build_route_card(env.db, "WO-NOPE") is None


def test_header_and_gate_rows(env):
    s = mksetup(env, "S-RC1")
    wo = mkwo(env, "WO-RC1", qty=8, setup=s, heats=["H-1", "H-2"], planned={"F1": (d(1), d(2)), "FI": (d(5), d(6))})
    card = build_route_card(env.db, "WO-RC1")
    assert card["wo_number"] == "WO-RC1" and card["wo_type"] == "Regular"
    assert card["fg_qty"] == 8 and card["rc_qty"] == 8 and card["is_draft"] is False
    assert card["po_numbers"] == ["PO-WO-RC1"] and card["setup_number"] == "S-RC1"
    assert card["heat_numbers"] == ["H-1", "H-2"]
    assert card["unique_production_code"] == card["internal_part_number"]
    assert card["die_id"] is None and card["bath_no"] is None and card["bin_id"] is None
    gates = [g["gate"] for g in card["gates"]]
    assert gates and "DISPATCH" not in gates                      # dispatch is not printed
    assert _gate(card, "F1")["start_date"] == d(1).isoformat()
    assert _gate(card, "F1")["responsibility"] is None            # roles come with the org chart
    assert _gate(card, "F1")["part_route"] == "IN_HOUSE"


def test_unreleased_work_order_is_a_draft(env):
    mkwo(env, "WO-RC2", qty=5, released=False)
    card = build_route_card(env.db, "WO-RC2")
    assert card["is_draft"] is True and card["rc_qty"] is None and card["gates"] == []


def test_quantities_come_from_mrb(env):
    wo = mkwo(env, "WO-RC3", qty=10, wip={"F1": (10, 10, 0, 0, 10)})
    _mrb(env, wo, "F1", "APPROVED", ok=6, rej=1, v_ok=5, v_rej=2)     # verified numbers win
    _mrb(env, wo, "F1", "PENDING", ok=3, rej=0)
    g = _gate(build_route_card(env.db, "WO-RC3"), "F1")
    assert g["quantity_source"] == "MRB"
    assert g["production_qty"] == 10                                   # 7 + 3 reported by the floor
    assert g["accepted_qty"] == 5 and g["rejected_qty"] == 2 and g["pending_qty"] == 3


def test_rejected_mrb_ticket_is_not_production(env):
    wo = mkwo(env, "WO-RC4", qty=10, wip={"F1": (10, 4, 0, 6, 4)})
    _mrb(env, wo, "F1", "REJECTED", ok=4)
    g = _gate(build_route_card(env.db, "WO-RC4"), "F1")
    assert g["production_qty"] == 0 and g["accepted_qty"] == 0


def test_gate_without_mrb_falls_back_to_recorded_quantities(env):
    wo = mkwo(env, "WO-RC5", qty=10, wip={"FI": (10, 8, 2, 0, 8)})
    g = _gate(build_route_card(env.db, "WO-RC5"), "FI")
    assert g["quantity_source"] == "FLOOR"
    assert (g["production_qty"], g["accepted_qty"], g["rejected_qty"], g["pending_qty"]) == (10, 8, 2, 0)
    assert _gate(build_route_card(env.db, "WO-RC5"), "F2")["quantity_source"] == "NONE"


def test_vendor_trip_shows_on_the_gate_row(env):
    wo = mkwo(env, "WO-RC6", qty=10)
    env.db.add(VendorDispatch(work_order_id=wo.id, dispatch_stage="F2", vendor_name="Acme HT", dc_number="DC-77",
                              process_name="Stress Relieving", dispatched_qty=10, received_qty=4, scrap_qty=1,
                              status="PARTIALLY_RECEIVED"))
    env.db.add(VendorDispatch(work_order_id=wo.id, dispatch_stage="F3", vendor_name="Gone", dc_number="DC-78",
                              dispatched_qty=5, status="AT_VENDOR", cancelled_at=datetime.now()))
    env.db.commit()
    card = build_route_card(env.db, "WO-RC6")
    g = _gate(card, "F2")
    assert g["part_route"] == "VENDOR" and g["qty_out_at_vendor"] == 5
    assert g["vendor_trips"][0]["dc_number"] == "DC-77" and g["vendor_trips"][0]["process_name"] == "Stress Relieving"
    assert _gate(card, "F3")["part_route"] == "IN_HOUSE"               # cancelled trip is ignored


def test_building_the_card_writes_nothing(env):
    wo = mkwo(env, "WO-RC7", qty=10, wip={"F1": (10, 10, 0, 0, 10)})
    _mrb(env, wo, "F1", "APPROVED", ok=10, v_ok=10)
    counts = lambda: (env.db.query(StageWIP).count(), env.db.query(MRBReview).count(), env.db.query(WORoute).count(),
                      env.db.query(ProductionMovement).count(), env.db.query(VendorDispatch).count())
    before = counts()
    snap = [(r.stage, r.ok_qty, r.onhand_qty) for r in env.db.query(StageWIP).all()]
    build_route_card(env.db, "WO-RC7")
    build_route_card(env.db, "WO-RC7")
    assert counts() == before
    assert snap == [(r.stage, r.ok_qty, r.onhand_qty) for r in env.db.query(StageWIP).all()]
    assert not env.db.dirty and not env.db.new


def test_replacement_and_npd_types(env):
    wo = mkwo(env, "WO-RC8", qty=5)
    wo.classification = "NPD"
    env.db.commit()
    assert build_route_card(env.db, "WO-RC8")["wo_type"] == "NPD"
    wo.is_replacement = True
    env.db.commit()
    assert build_route_card(env.db, "WO-RC8")["wo_type"] == "Replacement"


def test_route_card_roles_and_switch(env):
    from app.api.v1.work_orders import ROUTE_CARD_ROLES
    from app.models.user import UserRole
    assert UserRole.PLANNER in ROUTE_CARD_ROLES and UserRole.SCM in ROUTE_CARD_ROLES
    for r in (UserRole.OPERATOR, UserRole.SALES, UserRole.STORE, UserRole.F1_SUPERVISOR, UserRole.ACCOUNTS):
        assert r not in ROUTE_CARD_ROLES
