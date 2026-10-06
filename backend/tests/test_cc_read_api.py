"""Continuous Casting READ API (Phase 11C). In-memory SQLite only; no database file.

The read layer must not become a second source of truth, so these tests build a rich world through the real WRITE
endpoints (two inwards feeding two Work Orders, a shared unit, a split remnant, a hold, a scrap, adjustments, cut
results, an unlinked CUT_CONSUME, a superseded routing) and then check every read endpoint against the cached
columns, the ledger and the existing services -- including that GET requests are provably read-only (no INSERT,
UPDATE, DELETE or commit), that list query counts do not grow with the page size, and that the gate-status verdict is
pinned to what the real Phase 10 gate does.
"""
import uuid

import pytest
from sqlalchemy import event

from app.models import continuous_casting as cc
from app.models.production_movement import StageWIP
from app.models.user import UserRole
from app.models.work_order import WorkOrder
from app.schemas import continuous_casting_read as S
from app.services.continuous_casting_gate_service import ContinuousCastingGateService as Gate

from test_cc_api_router import api, test_db, ok, ROUTING, PREFIX, _reset_rate_limiter  # noqa: F401
from test_cc_reservation_service import make_wo
from test_cc_phase10_gate import build, reconciled, produce, do_cut, record, PER_BLANK

Unit, Inward, Alloc, Routing, Ledger, Cut = (cc.ContinuousCastingStockUnit, cc.ContinuousCastingInward,
                                             cc.ContinuousCastingAllocation, cc.ContinuousCastingRouting,
                                             cc.ContinuousCastingStockLedger, cc.ContinuousCastingCutRecord)

LIST_ENDPOINTS = [("/materials", 50), ("/inwards", 50), ("/stock-units", 50), ("/routings", 50),
                  ("/allocations", 50), ("/ledger", 100), ("/cut-results", 50)]


# ------------------------------------------------------------------ helpers
class Spy:
    """Counts the SQL an engine executes and the commits it makes."""

    def __init__(self, engine):
        self.engine, self.statements, self.commits = engine, [], 0
        event.listen(engine, "before_cursor_execute", self._statement)
        event.listen(engine, "commit", self._commit)

    def _statement(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement.strip().upper())

    def _commit(self, conn):
        self.commits += 1

    def reset(self):
        self.statements, self.commits = [], 0

    def writes(self):
        return [s for s in self.statements if s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP"))]

    def selects(self):
        return sum(1 for s in self.statements if s.startswith("SELECT"))

    def close(self):
        event.remove(self.engine, "before_cursor_execute", self._statement)
        event.remove(self.engine, "commit", self._commit)


@pytest.fixture()
def spy(api):
    s = Spy(api.db.get_bind())
    yield s
    s.close()


def get(api, path, params=None, role=UserRole.STORE):
    return api.client.get(PREFIX + path, params=params, headers=api.headers(role))


def page(api, path, params=None):
    body = ok(get(api, path, params))
    assert set(body) == {"items", "total", "limit", "offset"}
    return body


def rich_world(api):
    """Built only through the write endpoints."""
    db = api.db
    m = ok(api.post("/materials", UserRole.ENGINEERING,
                    dict(material_code="CC-R1", grade="SG450", section="ROUND", stock_dimension_a_mm=200)))
    mid = m["material_id"]
    ok(api.post("/materials", UserRole.ENGINEERING,                          # a second, unreferenced material
                dict(material_code="CC-R2", grade="SG450", section="ROUND", stock_dimension_a_mm=250)))
    i1 = ok(api.post("/inwards", UserRole.STORE, dict(material_id=mid, unit_lengths_mm=[1000, 800, 600],
                                                      location="RACK-A", grn_reference="GRN-1")))
    i2 = ok(api.post("/inwards", UserRole.STORE, dict(material_id=mid, unit_lengths_mm=[900], location="RACK-B",
                                                      grn_reference="GRN-2")))
    i3 = ok(api.post("/inwards", UserRole.STORE, dict(material_id=mid, unit_lengths_mm=[500], location="RACK-C")))
    ok(api.post(f"/inwards/{i1['inward_id']}/qa", UserRole.QA, dict(decision="ACCEPTED", reason="mill cert")))
    ok(api.post(f"/inwards/{i2['inward_id']}/qa", UserRole.QA, dict(decision="ACCEPTED")))
    make_wo(db, "WO-1001")
    make_wo(db, "WO-1002")
    r1 = ok(api.post("/routings", UserRole.ENGINEERING, dict(wo_number="WO-1001", validated_material_id=mid, **ROUTING)))
    r2 = ok(api.post("/routings", UserRole.ENGINEERING, dict(wo_number="WO-1002", validated_material_id=mid, **ROUTING)))
    unit = {u.unit_number: u for u in db.query(Unit).all()}
    u1000, u800, u600 = (unit[i1["units"][k]["unit_number"]] for k in range(3))
    u900 = unit[i2["units"][0]["unit_number"]]
    u500 = unit[i3["units"][0]["unit_number"]]

    def allocate(routing, u, planned):
        return ok(api.post("/allocations", UserRole.PLANNER, dict(routing_id=routing["routing_id"],
                                                                  stock_unit_id=str(u.id), planned_length_mm=planned)))

    a1, ai2 = allocate(r1, u1000, 600), allocate(r1, u900, 400)          # WO-1001 draws on TWO inwards
    b1, b2 = allocate(r2, u1000, 300), allocate(r2, u800, 300)           # WO-1002 shares inward I1 with WO-1001

    def move(path, role, alloc, routing, u, length, **extra):
        body = dict(routing_id=routing["routing_id"], allocation_id=alloc["allocation_id"], length_mm=length, **extra)
        if path != "/reservations":
            body["stock_unit_id"] = str(u.id)
        return ok(api.post(path, role, body))

    def cut(alloc, routing, u, length, blanks=None):
        move("/reservations", UserRole.PLANNER, alloc, routing, u, length)
        move("/issues", UserRole.STORE, alloc, routing, u, length)
        txn = move("/cut-consume", UserRole.PRODUCTION_MANAGER, alloc, routing, u, length)["ledger_transaction_number"]
        if blanks:
            ok(api.post("/cut-results", UserRole.PRODUCTION_MANAGER, dict(
                routing_id=routing["routing_id"], allocation_id=alloc["allocation_id"], stock_unit_id=str(u.id),
                ledger_transaction_number=txn, consumed_length_mm=length, actual_good_blanks=blanks,
                rejected_blanks=0, actual_cuts=blanks, end_trim_mm=0)))
        return txn

    cut_a1 = cut(a1, r1, u1000, 5 * PER_BLANK, blanks=5)                 # 535 mm, RECONCILED, 5 usable blanks
    cut_i2 = cut(ai2, r1, u900, 2 * PER_BLANK, blanks=2)                 # 214 mm, 2 usable blanks
    cut_b1 = cut(b1, r2, u1000, PER_BLANK)                               # 107 mm consumed, NO cut result yet
    ok(api.post("/reservations", UserRole.PLANNER, dict(routing_id=r2["routing_id"], allocation_id=b2["allocation_id"],
                                                        length_mm=100)))   # stays reserved
    split = ok(api.post("/splits", UserRole.STORE, dict(stock_unit_id=str(u1000.id), inward_id=i1["inward_id"],
                                                         length_mm=100)))
    child_id = split["child_unit_id"]
    ok(api.post("/holds", UserRole.QA, dict(stock_unit_id=child_id, inward_id=i1["inward_id"], reason="crack")))
    ok(api.post("/scrap", UserRole.STORE, dict(stock_unit_id=str(u800.id), inward_id=i1["inward_id"], length_mm=50,
                                               reason="melt", reference="S-1")))
    ok(api.post("/adjustments/out", UserRole.ADMIN, dict(stock_unit_id=str(u600.id), inward_id=i1["inward_id"],
                                                         length_mm=10, reason="count", reference="C-1")))
    ok(api.post("/adjustments/in", UserRole.ADMIN, dict(stock_unit_id=str(u600.id), inward_id=i1["inward_id"],
                                                        length_mm=5, reason="recount", reference="C-2")))
    sup = ok(api.post("/routings/supersede", UserRole.ENGINEERING, dict(
        wo_number="WO-1002", validated_material_id=mid, reason="design change", **ROUTING)))
    db.expire_all()
    return dict(material=m, mid=mid, i1=i1, i2=i2, i3=i3, r1=r1, r2=r2, sup=sup, u1000=str(u1000.id), u800=str(u800.id),
                u600=str(u600.id), u900=str(u900.id), u500=str(u500.id), child=child_id, a1=a1, ai2=ai2, b1=b1, b2=b2,
                cut_a1=cut_a1, cut_i2=cut_i2, cut_b1=cut_b1)


@pytest.fixture()
def world(api):
    return rich_world(api)


READ_PATHS = [
    "/materials", "/materials/{id}", "/inwards", "/inwards/{id}", "/stock-units", "/stock-units/{id}", "/routings",
    "/routings/{id}", "/allocations", "/ledger", "/cut-results", "/cut-results/available?wo_number=WO-1001",
    "/cut-results/{id}", "/traceability/inwards/{id}", "/traceability/work-orders/WO-1001",
    "/work-orders/WO-1001/gate-status",
]


def fill(path, w, api):
    cut_id = str(api.db.query(Cut).first().id)
    return (path.replace("/materials/{id}", f"/materials/{w['mid']}")
            .replace("/inwards/{id}", f"/inwards/{w['i1']['inward_id']}")
            .replace("/stock-units/{id}", f"/stock-units/{w['u1000']}")
            .replace("/routings/{id}", f"/routings/{w['r1']['routing_id']}")
            .replace("/cut-results/{id}", f"/cut-results/{cut_id}"))


# ================================================================== authentication
@pytest.mark.parametrize("path", READ_PATHS)
def test_every_read_endpoint_needs_a_valid_token(api, path):
    url = PREFIX + path.replace("{id}", str(uuid.uuid4()))
    assert api.client.get(url).status_code == 401
    assert api.client.get(url, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_every_authenticated_role_may_read(api, world):
    for role in UserRole:
        assert get(api, "/inwards", role=role).status_code == 200
        assert get(api, "/stock-units", role=role).status_code == 200
        assert get(api, "/work-orders/WO-1001/gate-status", role=role).status_code == 200


# ================================================================== GET is provably read-only
def test_get_requests_never_write_or_commit(api, world, spy):
    paths = [fill(p, world, api) for p in READ_PATHS] + [
        f"/stock-units?inward_id={world['i1']['inward_id']}&available=true",
        f"/ledger?wo_number=WO-1001&movement_type=CUT_CONSUME", "/inwards?has_free_stock=true",
        "/cut-results/available?routing_id=" + world["r2"]["routing_id"]]
    spy.reset()
    for path in paths:
        assert get(api, path).status_code == 200, path
    assert spy.commits == 0
    assert spy.writes() == [], spy.writes()[:3]
    assert not api.db.new and not api.db.dirty and not api.db.deleted      # nothing was even staged in the session
    assert spy.selects() > len(paths)                                      # and they really did query


def test_a_get_does_not_repair_or_change_anything(api, world, spy):
    """A ledger inconsistency is reported as an informational flag; nothing is raised, repaired or written."""
    from sqlalchemy import text
    api.db.execute(text("UPDATE cc_stock_units SET remaining_length_mm = remaining_length_mm - 7 WHERE id = :i"),
                   {"i": world["u600"]})
    api.db.commit()
    spy.reset()
    body = ok(get(api, f"/stock-units/{world['u600']}"))
    assert body["integrity"]["consistent"] is False
    assert body["remaining_length_mm"] == body["integrity"]["ledger_remaining_length_mm"] - 7
    detail = ok(get(api, f"/inwards/{world['i1']['inward_id']}"))
    assert detail["conservation"]["consistent"] is False
    assert spy.writes() == [] and spy.commits == 0
    assert ok(get(api, f"/stock-units/{world['u600']}"))["remaining_length_mm"] == body["remaining_length_mm"]


# ================================================================== pagination
@pytest.mark.parametrize("path,default", LIST_ENDPOINTS)
def test_pagination_envelope_limits_and_offsets(api, world, path, default):
    body = page(api, path)
    assert (body["limit"], body["offset"]) == (default, 0) and body["total"] == len(body["items"]) > 1
    first = page(api, path, {"limit": 1})
    assert len(first["items"]) == 1 and first["total"] == body["total"] and first["limit"] == 1
    second = page(api, path, {"limit": 1, "offset": 1})
    assert second["offset"] == 1 and second["items"][0] != first["items"][0]
    assert page(api, path, {"limit": 500, "offset": 10_000})["items"] == []
    assert page(api, path, {"limit": 500, "offset": 10_000})["total"] == body["total"]
    for bad in ({"limit": 501}, {"limit": 0}, {"offset": -1}, {"limit": "x"}):
        assert get(api, path, bad).status_code == 422, bad


def test_pages_cover_the_whole_list_without_overlap(api, world):
    total = page(api, "/ledger")["total"]
    seen = []
    for offset in range(0, total, 7):
        seen += [r["transaction_number"] for r in page(api, "/ledger", {"limit": 7, "offset": offset})["items"]]
    assert len(seen) == total == len(set(seen))
    assert seen == sorted(seen, reverse=True)                              # transaction_number descending


# ================================================================== materials
def test_materials_list_and_filters(api, world):
    ok(api.post("/materials", UserRole.ENGINEERING,
                dict(material_code="OTHER-9", grade="SG500", section="SQUARE", stock_dimension_a_mm=50)))
    other = page(api, "/materials", {"search": "other"})["items"]
    assert [m["material_code"] for m in other] == ["OTHER-9"] and other[0]["referenced"] is False
    assert (other[0]["inward_count"], other[0]["routing_count"]) == (0, 0)
    r1 = page(api, "/materials", {"search": "cc-r1"})["items"][0]
    assert (r1["inward_count"], r1["routing_count"], r1["referenced"]) == (3, 3, True)    # 3 inwards; routings v1, v1, v2
    r2 = page(api, "/materials", {"search": "cc-r2"})["items"][0]
    assert (r2["inward_count"], r2["routing_count"], r2["referenced"]) == (0, 0, False)
    assert [m["material_code"] for m in page(api, "/materials", {"grade": "sg500"})["items"]] == ["OTHER-9"]
    assert [m["material_code"] for m in page(api, "/materials", {"section": "round"})["items"]] == ["CC-R1", "CC-R2"]
    api.call("PATCH", f"/materials/{other[0]['material_id']}", UserRole.ENGINEERING, json={"is_active": False})
    assert [m["material_code"] for m in page(api, "/materials", {"is_active": "false"})["items"]] == ["OTHER-9"]
    assert page(api, "/materials", {"is_active": "true"})["total"] == 2
    S.CCMaterialListResponse(**page(api, "/materials"))


# ================================================================== inwards
def test_inward_list_aggregates_and_filters(api, world):
    items = {i["inward_number"]: i for i in page(api, "/inwards")["items"]}
    i1 = items[world["i1"]["inward_number"]]
    assert (i1["unit_count"], i1["consumed_length_mm"], i1["scrapped_length_mm"], i1["reserved_length_mm"],
            i1["issued_length_mm"]) == (4, 642, 50, 100, 0)
    assert i1["remaining_length_mm"] == 1703 and i1["free_length_mm"] == 1603      # free = remaining - reserved - issued
    assert (i1["received_total_length_mm"], i1["received_piece_count"], i1["qa_status"], i1["location"]) == (
        2400, 3, "ACCEPTED", "RACK-A")
    for item in items.values():                                                    # sums equal the units' own balances
        units = page(api, "/stock-units", {"inward_id": item["inward_id"]})["items"]
        for field in ("remaining", "reserved", "issued", "consumed", "scrapped", "free"):
            assert item[f"{field}_length_mm"] == sum(u[f"{field}_length_mm"] for u in units), field
        assert item["unit_count"] == len(units)
    assert [i["inward_number"] for i in page(api, "/inwards", {"qa_status": "PENDING_QA"})["items"]] == [
        world["i3"]["inward_number"]]
    assert page(api, "/inwards", {"qa_status": "ACCEPTED"})["total"] == 2
    assert [i["inward_number"] for i in page(api, "/inwards", {"location": "rack-b"})["items"]] == [world["i2"]["inward_number"]]
    assert page(api, "/inwards", {"inward_number": world["i1"]["inward_number"]})["total"] == 1
    assert page(api, "/inwards", {"material_id": world["mid"]})["total"] == 3
    assert page(api, "/inwards", {"material_id": str(uuid.uuid4())})["total"] == 0
    assert page(api, "/inwards", {"has_free_stock": "true"})["total"] == 3
    assert page(api, "/inwards", {"received_from": "2000-01-01T00:00:00", "received_to": "2999-01-01T00:00:00"})["total"] == 3
    assert page(api, "/inwards", {"received_to": "2000-01-01T00:00:00"})["total"] == 0
    assert page(api, "/inwards", {"received_from": "2999-01-01T00:00:00"})["total"] == 0
    assert get(api, "/inwards", {"qa_status": "BOGUS"}).status_code == 422


def test_an_inward_with_no_free_stock_is_filtered_by_has_free_stock(api):
    m = ok(api.post("/materials", UserRole.ENGINEERING, dict(material_code="X", grade="G", section="S", stock_dimension_a_mm=5)))
    inw = ok(api.post("/inwards", UserRole.STORE, dict(material_id=m["material_id"], unit_lengths_mm=[300])))
    ok(api.post(f"/inwards/{inw['inward_id']}/qa", UserRole.QA, dict(decision="ACCEPTED")))
    unit = api.db.query(Unit).one()
    ok(api.post("/scrap", UserRole.STORE, dict(stock_unit_id=str(unit.id), inward_id=inw["inward_id"], length_mm=300,
                                               reason="all", reference="S")))
    assert page(api, "/inwards", {"has_free_stock": "true"})["total"] == 0
    only = page(api, "/inwards", {"has_free_stock": "false"})["items"]
    assert len(only) == 1 and only[0]["free_length_mm"] == 0 and only[0]["scrapped_length_mm"] == 300


def test_inward_detail_with_qa_decision_from_the_audit_history_and_conservation(api, world):
    d = ok(get(api, f"/inwards/{world['i1']['inward_id']}"))
    S.CCInwardDetail(**d)
    assert d["original_received_length_mm"] == 2400 and d["physical_piece_count"] == 3
    assert d["qa_decision"]["decision"] == "ACCEPTED" and d["qa_decision"]["reason"] == "mill cert"
    assert d["qa_decision"]["previous_qa_status"] == "PENDING_QA" and d["qa_decision"]["decided_by"]
    assert d["conservation"] == dict(accounted_length_mm=2395, expected_length_mm=2395, adjustments_in_mm=5,
                                     adjustments_out_mm=10, consistent=True)           # 2400 - 10 + 5
    pending = ok(get(api, f"/inwards/{world['i3']['inward_id']}"))
    assert pending["qa_decision"] is None and pending["qa_status"] == "PENDING_QA"
    assert get(api, f"/inwards/{uuid.uuid4()}").status_code == 404
    assert get(api, "/inwards/not-a-uuid").status_code == 422


# ================================================================== stock units
def test_stock_unit_list_balances_and_filters(api, world):
    units = page(api, "/stock-units")["items"]
    assert len(units) == 6 and all(u["piece_quantity"] == 1 for u in units)           # 1 bar per StockUnit
    for u in units:
        assert u["free_length_mm"] == u["remaining_length_mm"] - u["reserved_length_mm"] - u["issued_length_mm"]
        S.CCStockUnitOut(**u)
    by_id = {u["unit_id"]: u for u in units}
    u1000 = by_id[world["u1000"]]
    assert (u1000["remaining_length_mm"], u1000["consumed_length_mm"], u1000["status"]) == (258, 642, "IN_STOCK")
    child = by_id[world["child"]]
    assert (child["parent_unit_id"], child["parent_unit_number"], child["original_length_mm"], child["status"]) == (
        world["u1000"], u1000["unit_number"], 100, "ON_HOLD")
    assert by_id[world["u800"]]["scrapped_length_mm"] == 50 and by_id[world["u800"]]["reserved_length_mm"] == 100
    assert page(api, "/stock-units", {"inward_id": world["i1"]["inward_id"]})["total"] == 4
    assert page(api, "/stock-units", {"material_id": world["mid"]})["total"] == 6
    assert page(api, "/stock-units", {"status": "ON_HOLD"})["total"] == 1
    assert [u["unit_id"] for u in page(api, "/stock-units", {"on_hold": "true"})["items"]] == [world["child"]]
    assert page(api, "/stock-units", {"on_hold": "false"})["total"] == 5
    assert [u["unit_id"] for u in page(api, "/stock-units", {"parent_unit_id": world["u1000"]})["items"]] == [world["child"]]
    assert page(api, "/stock-units", {"location": "x"})["total"] == 0
    assert get(api, "/stock-units", {"status": "NOPE"}).status_code == 422


def test_available_means_exactly_the_allocation_eligibility_conditions(api, world):
    """inward ACCEPTED, unit IN_STOCK, free > 0 -- the same answer as the frozen predicate for every unit."""
    units = page(api, "/stock-units")["items"]
    expected = {u["unit_id"] for u in units if u["allocation_eligible"]}
    assert {u["unit_id"] for u in page(api, "/stock-units", {"available": "true"})["items"]} == expected
    assert {u["unit_id"] for u in page(api, "/stock-units", {"available": "false"})["items"]} == {
        u["unit_id"] for u in units} - expected
    by_id = {u["unit_id"]: u for u in units}
    assert by_id[world["u500"]]["allocation_eligible"] is False                         # PENDING_QA inward
    assert "PENDING_QA" in by_id[world["u500"]]["allocation_ineligible_reason"]
    assert by_id[world["child"]]["allocation_eligible"] is False                        # ON_HOLD unit
    assert "ON_HOLD" in by_id[world["child"]]["allocation_ineligible_reason"]
    assert by_id[world["u1000"]]["allocation_eligible"] is True
    for row in api.db.query(Unit).all():                                                # and the predicate itself agrees
        assert (cc.allocation_ineligibility_reason(row) is None) is by_id[str(row.id)]["allocation_eligible"]
    assert world["u500"] not in expected and world["child"] not in expected


def test_stock_unit_with_no_free_length_is_not_available(api):
    m = ok(api.post("/materials", UserRole.ENGINEERING, dict(material_code="Y", grade="G", section="S", stock_dimension_a_mm=5)))
    inw = ok(api.post("/inwards", UserRole.STORE, dict(material_id=m["material_id"], unit_lengths_mm=[300])))
    ok(api.post(f"/inwards/{inw['inward_id']}/qa", UserRole.QA, dict(decision="ACCEPTED")))
    unit = api.db.query(Unit).one()
    assert page(api, "/stock-units", {"available": "true"})["total"] == 1
    unit.reserved_length_mm = 0
    ok(api.post("/scrap", UserRole.STORE, dict(stock_unit_id=str(unit.id), inward_id=inw["inward_id"], length_mm=300,
                                               reason="all", reference="S")))
    assert page(api, "/stock-units", {"available": "true"})["total"] == 0              # SCRAPPED, free 0


def test_stock_unit_detail(api, world):
    d = ok(get(api, f"/stock-units/{world['u1000']}"))
    S.CCStockUnitDetail(**d)
    assert d["free_length_mm"] == 258 and [c["unit_id"] for c in d["children"]] == [world["child"]]
    assert d["integrity"]["consistent"] is True and d["integrity"]["ledger_consumed_length_mm"] == 642
    assert d["integrity"]["ledger_remaining_length_mm"] == 258 and d["net_adjustment_mm"] == 0
    assert sorted(a["wo_number"] for a in d["allocations"]) == ["WO-1001", "WO-1002"]    # one unit, TWO Work Orders
    child = ok(get(api, f"/stock-units/{world['child']}"))
    assert child["last_hold_event"]["movement_type"] == "HOLD" and child["last_hold_event"]["reason"] == "crack"
    assert child["parent_unit_number"] == d["unit_number"] and child["children"] == []
    adj = ok(get(api, f"/stock-units/{world['u600']}"))
    assert adj["net_adjustment_mm"] == -5 and adj["remaining_length_mm"] == 595
    assert ok(get(api, f"/stock-units/{world['u800']}"))["last_hold_event"] is None
    assert get(api, f"/stock-units/{uuid.uuid4()}").status_code == 404


def test_every_units_cached_balances_agree_with_the_ledger(api, world):
    for u in page(api, "/stock-units")["items"]:
        assert ok(get(api, f"/stock-units/{u['unit_id']}"))["integrity"]["consistent"] is True, u["unit_number"]


# ================================================================== routings / allocations
def test_routings_keep_their_version_history(api, world):
    items = page(api, "/routings")["items"]
    assert len(items) == 3
    wo2 = page(api, "/routings", {"wo_number": "WO-1002"})["items"]
    assert [(r["version"], r["status"], r["is_active"]) for r in wo2] == [(2, "ACTIVE", True), (1, "SUPERSEDED", False)]
    assert wo2[1]["supersede_reason"] == "design change" and wo2[1]["superseded_by"]
    assert wo2[0]["blank_length_mm"] == 104 and wo2[0]["planned_blanks"] == 10 and wo2[0]["kerf_mm"] == 3
    assert wo2[0]["gross_required_length_mm"] == 1070 and wo2[0]["validated_material_code"] == "CC-R1"
    assert wo2[1]["allocation_count"] == 2 and wo2[0]["allocation_count"] == 0       # allocations stay on the old version
    assert [r["wo_number"] for r in page(api, "/routings", {"status": "ACTIVE"})["items"]] == ["WO-1001", "WO-1002"]
    assert page(api, "/routings", {"status": "SUPERSEDED"})["total"] == 1
    assert page(api, "/routings", {"material_source": "CONTINUOUS_CASTING"})["total"] == 3
    assert page(api, "/routings", {"material_source": "F1_PRODUCTION"})["total"] == 0
    d = ok(get(api, f"/routings/{world['r1']['routing_id']}"))
    S.CCRoutingDetail(**d)
    assert len(d["allocations"]) == 2 and d["wo_number"] == "WO-1001"
    assert get(api, f"/routings/{uuid.uuid4()}").status_code == 404


def test_allocations_are_the_many_to_many_join(api, world):
    allocs = page(api, "/allocations")["items"]
    assert len(allocs) == 4
    for a in allocs:
        assert a["plan_remaining_length_mm"] == (a["planned_length_mm"] - a["reserved_length_mm"]
                                                 - a["issued_length_mm"] - a["consumed_length_mm"])
        S.CCAllocationOut(**a)
    a1 = next(a for a in allocs if a["allocation_id"] == world["a1"]["allocation_id"])
    assert (a1["planned_length_mm"], a1["consumed_length_mm"], a1["reserved_length_mm"], a1["issued_length_mm"],
            a1["plan_remaining_length_mm"], a1["wo_number"], a1["routing_version"]) == (600, 535, 0, 0, 65, "WO-1001", 1)
    assert {a["wo_number"] for a in page(api, "/allocations", {"stock_unit_id": world["u1000"]})["items"]} == {"WO-1001", "WO-1002"}
    assert {a["inward_number"] for a in page(api, "/allocations", {"wo_number": "WO-1001"})["items"]} == {
        world["i1"]["inward_number"], world["i2"]["inward_number"]}
    assert page(api, "/allocations", {"routing_id": world["r1"]["routing_id"]})["total"] == 2
    assert page(api, "/allocations", {"inward_id": world["i1"]["inward_id"]})["total"] == 3
    assert page(api, "/allocations", {"status": "PARTIALLY_CONSUMED"})["total"] >= 1
    assert page(api, "/allocations", {"wo_number": "NOPE"})["total"] == 0


# ================================================================== ledger
def test_ledger_history_filters_and_derived_links(api, world):
    allrows = page(api, "/ledger", {"limit": 500})
    assert allrows["total"] == api.db.query(Ledger).count()
    types = {r["movement_type"] for r in allrows["items"]}
    assert {"INWARD", "RESERVE", "ISSUE", "CUT_CONSUME", "SPLIT_OUT", "SPLIT_IN", "HOLD", "SCRAP", "ADJUSTMENT_OUT",
            "ADJUSTMENT_IN"} <= types
    for r in allrows["items"]:
        S.CCLedgerOut(**r)
        assert "client_request_id" not in r
    inward_rows = [r for r in allrows["items"] if r["movement_type"] == "INWARD"]
    assert all(r["allocation_id"] is None and r["wo_number"] is None and r["routing_id"] is None for r in inward_rows)
    cut = next(r for r in allrows["items"] if r["transaction_number"] == world["cut_a1"])
    assert (cut["movement_type"], cut["length_mm"], cut["wo_number"], cut["routing_version"], cut["unit_remaining_after_mm"]) == (
        "CUT_CONSUME", 535, "WO-1001", 1, 465)
    split_out = next(r for r in allrows["items"] if r["movement_type"] == "SPLIT_OUT")
    assert split_out["related_stock_unit_id"] == world["child"] and split_out["related_stock_unit_number"]
    assert split_out["piece_qty"] is None and all(r["piece_qty"] == 1 for r in inward_rows)
    assert allrows["items"][0]["transaction_number"] > allrows["items"][-1]["transaction_number"]
    assert page(api, "/ledger", {"movement_type": "CUT_CONSUME"})["total"] == 3
    assert {r["wo_number"] for r in page(api, "/ledger", {"wo_number": "WO-1002"})["items"]} == {"WO-1002"}
    assert page(api, "/ledger", {"routing_id": world["r1"]["routing_id"]})["total"] > 0
    assert page(api, "/ledger", {"allocation_id": world["a1"]["allocation_id"]})["total"] == 3   # RESERVE ISSUE CUT_CONSUME
    assert {r["stock_unit_id"] for r in page(api, "/ledger", {"stock_unit_id": world["u800"]})["items"]} == {world["u800"]}
    assert page(api, "/ledger", {"inward_id": world["i3"]["inward_id"]})["total"] == 1
    assert page(api, "/ledger", {"created_from": "2999-01-01T00:00:00"})["total"] == 0
    assert page(api, "/ledger", {"created_to": "2000-01-01T00:00:00"})["total"] == 0
    assert page(api, "/ledger", {"created_from": "2000-01-01T00:00:00", "created_to": "2999-01-01T00:00:00"})["total"] == allrows["total"]
    assert get(api, "/ledger", {"movement_type": "BOGUS"}).status_code == 422
    assert api.client.post(PREFIX + "/ledger", json={}, headers=api.headers(UserRole.ADMIN)).status_code == 405
    assert api.client.delete(PREFIX + "/ledger", headers=api.headers(UserRole.ADMIN)).status_code == 405


def test_a_scrap_row_names_its_nc_pointer_only_when_one_exists(api, world):
    scrap = next(r for r in page(api, "/ledger", {"movement_type": "SCRAP"})["items"])
    assert scrap["nc_record_id"] is None and scrap["nc_number"] is None
    assert scrap["reason"] == "melt" and scrap["reference"] == "S-1" and scrap["performed_by"]


# ================================================================== cut results
def test_cut_results_and_their_links(api, world):
    items = page(api, "/cut-results")["items"]
    assert len(items) == 2
    for c in items:
        S.CCCutResultOut(**c)
        assert not any(k.startswith("retained_remnant") for k in c) and "client_request_id" not in c
    by_txn = {c["ledger_transaction_number"]: c for c in items}
    c = by_txn[world["cut_a1"]]
    assert (c["wo_number"], c["actual_good_blanks"], c["rejected_blanks"], c["actual_cuts"], c["blank_length_mm"],
            c["kerf_mm"], c["end_trim_mm"], c["consumed_length_mm"], c["reconciliation_status"], c["variance_mm"],
            c["usable_for_oms"], c["planned_blanks"]) == ("WO-1001", 5, 0, 5, 104, 3, 0, 535, "RECONCILED", 0, True, 10)
    assert c["routing_version"] == 1 and c["allocation_number"] and c["stock_unit_number"] and c["inward_number"]
    assert ok(get(api, f"/cut-results/{c['cut_result_id']}")) == c
    assert page(api, "/cut-results", {"ledger_transaction_number": world["cut_i2"]})["total"] == 1
    assert page(api, "/cut-results", {"wo_number": "WO-1001"})["total"] == 2
    assert page(api, "/cut-results", {"wo_number": "WO-1002"})["total"] == 0
    assert page(api, "/cut-results", {"routing_id": world["r1"]["routing_id"]})["total"] == 2
    assert page(api, "/cut-results", {"allocation_id": world["ai2"]["allocation_id"]})["total"] == 1
    assert page(api, "/cut-results", {"stock_unit_id": world["u1000"]})["total"] == 1
    assert page(api, "/cut-results", {"reconciliation_status": "RECONCILED"})["total"] == 2
    assert page(api, "/cut-results", {"reconciliation_status": "VARIANCE"})["total"] == 0
    assert get(api, f"/cut-results/{uuid.uuid4()}").status_code == 404
    assert get(api, "/cut-results", {"reconciliation_status": "NOPE"}).status_code == 422
    assert api.client.patch(PREFIX + f"/cut-results/{c['cut_result_id']}", json={},
                            headers=api.headers(UserRole.ADMIN)).status_code == 405       # immutable: no write verb


def test_usable_flag_adds_up_to_the_gates_own_usable_blanks(api, world):
    flagged = sum(c["actual_good_blanks"] for c in page(api, "/cut-results")["items"] if c["usable_for_oms"])
    wo = api.db.query(WorkOrder).filter_by(wo_number="WO-1001").one()
    assert flagged == Gate.usable_good_blanks(api.db, wo, Gate.active_china_routing(api.db, wo)) == 7


def test_a_variance_result_is_listed_but_not_usable(api, world):
    # WO-1002's routing v2 is ACTIVE; cut through a fresh allocation on it, with 5 mm of unexplained consumption
    r2 = world["sup"]["routing_id"]
    alloc = ok(api.post("/allocations", UserRole.PLANNER, dict(routing_id=r2, stock_unit_id=world["u900"], planned_length_mm=300)))
    base = dict(routing_id=r2, allocation_id=alloc["allocation_id"])
    ok(api.post("/reservations", UserRole.PLANNER, dict(**base, length_mm=112)))
    ok(api.post("/issues", UserRole.STORE, dict(**base, stock_unit_id=world["u900"], length_mm=112)))
    txn = ok(api.post("/cut-consume", UserRole.PRODUCTION_MANAGER, dict(**base, stock_unit_id=world["u900"], length_mm=112)))[
        "ledger_transaction_number"]
    ok(api.post("/cut-results", UserRole.PRODUCTION_MANAGER, dict(
        **base, stock_unit_id=world["u900"], ledger_transaction_number=txn, consumed_length_mm=112,
        actual_good_blanks=1, rejected_blanks=0, actual_cuts=1, end_trim_mm=0)))      # needs 107: 5 mm variance
    v = page(api, "/cut-results", {"reconciliation_status": "VARIANCE"})["items"]
    assert len(v) == 1 and v[0]["variance_mm"] == 5 and v[0]["usable_for_oms"] is False


# ================================================================== cut-consume lookup
def test_available_lists_only_unlinked_cut_consumes_inside_the_requested_scope(api, world):
    wo2 = page(api, "/cut-results/available", {"wo_number": "WO-1002"})
    assert wo2["total"] == 1
    row = wo2["items"][0]
    S.CCCutAvailableOut(**row)
    assert (row["ledger_transaction_number"], row["consumed_length_mm"], row["wo_number"], row["routing_version"],
            row["routing_status"]) == (world["cut_b1"], 107, "WO-1002", 1, "SUPERSEDED")       # superseded is accepted
    assert (row["planned_blanks"], row["blank_length_mm"], row["kerf_mm"], row["planned_cuts"]) == (10, 104, 3, 10)
    assert (row["routing_blanks_recorded"], row["routing_blanks_remaining_in_plan"]) == (0, 10)
    assert "suggested" not in " ".join(row) and "blank_count" not in row                   # no blank count is suggested
    # the linked transactions of WO-1001 are NOT available, and WO-1002's transaction never leaks into WO-1001
    assert page(api, "/cut-results/available", {"wo_number": "WO-1001"})["total"] == 0
    assert page(api, "/cut-results/available", {"routing_id": world["r1"]["routing_id"]})["total"] == 0
    assert [i["ledger_transaction_number"] for i in page(
        api, "/cut-results/available", {"routing_id": world["r2"]["routing_id"]})["items"]] == [world["cut_b1"]]
    assert page(api, "/cut-results/available", {"routing_id": world["sup"]["routing_id"]})["total"] == 0   # v2: no cuts
    assert page(api, "/cut-results/available", {"wo_number": "WO-1001", "routing_id": world["r2"]["routing_id"]})["total"] == 0
    assert page(api, "/cut-results/available", {"wo_number": "NOPE"})["total"] == 0


def test_available_is_always_scoped_and_drops_a_transaction_once_it_has_a_result(api, world):
    for params in (None, {"limit": 5}, {"wo_number": " "}):
        r = get(api, "/cut-results/available", params)
        assert r.status_code == 400 and "routing_id or wo_number is required" in r.json()["detail"]
    assert get(api, "/cut-results/available", {"routing_id": "nope"}).status_code == 422
    body = dict(routing_id=world["r2"]["routing_id"], allocation_id=world["b1"]["allocation_id"],
                stock_unit_id=world["u1000"], ledger_transaction_number=world["cut_b1"], consumed_length_mm=107,
                actual_good_blanks=1, rejected_blanks=0, actual_cuts=1, end_trim_mm=0)
    ok(api.post("/cut-results", UserRole.PRODUCTION_MANAGER, body))                       # the Record Cut Result step
    assert page(api, "/cut-results/available", {"wo_number": "WO-1002"})["total"] == 0    # linked now: gone
    assert page(api, "/cut-results", {"wo_number": "WO-1002"})["total"] == 1


def test_available_hides_cuts_on_a_non_continuous_casting_routing(api, world):
    api.db.query(Routing).filter_by(id=uuid.UUID(world["r2"]["routing_id"])).update({"status": "DRAFT"})
    api.db.commit()
    assert page(api, "/cut-results/available", {"routing_id": world["r2"]["routing_id"]})["total"] == 0


# ================================================================== traceability
def test_inward_to_work_orders_preserves_many_to_many(api, world):
    t = ok(get(api, f"/traceability/inwards/{world['i1']['inward_id']}"))
    S.CCTraceInward(**t)
    assert t["inward"]["inward_number"] == world["i1"]["inward_number"] and t["units_total"] == 4
    assert {w["wo_number"] for w in t["work_orders"]} == {"WO-1001", "WO-1002"}      # ONE inward -> TWO Work Orders
    wo2 = next(w for w in t["work_orders"] if w["wo_number"] == "WO-1002")
    assert wo2["routing_versions"] == [1] and wo2["active_routing_version"] is None   # its allocations sit on SUPERSEDED v1
    units = {u["unit_id"]: u for u in t["units"]}
    assert len(units[world["u1000"]]["allocations"]) == 2                            # one unit -> two allocations
    assert units[world["child"]]["parent_unit_number"] == units[world["u1000"]]["unit_number"]   # remnant lineage
    assert units[world["child"]]["allocations"] == []
    assert [c["ledger_transaction_number"] for c in t["cut_results"]] == [world["cut_a1"]]
    assert t["ledger_totals_by_movement"]["INWARD"] == 2400 and t["ledger_totals_by_movement"]["CUT_CONSUME"] == 642
    assert t["ledger_rows_total"] == page(api, "/ledger", {"inward_id": world["i1"]["inward_id"]})["total"]
    assert len(t["recent_ledger"]) == min(100, t["ledger_rows_total"]) and t["truncated"] is False
    assert any("Downstream component traceability is not available" in line for line in t["limitations"])
    two = ok(get(api, f"/traceability/inwards/{world['i2']['inward_id']}"))
    assert {w["wo_number"] for w in two["work_orders"]} == {"WO-1001"} and two["units_total"] == 1
    untouched = ok(get(api, f"/traceability/inwards/{world['i3']['inward_id']}"))
    assert untouched["work_orders"] == [] and untouched["cut_results"] == []
    assert get(api, f"/traceability/inwards/{uuid.uuid4()}").status_code == 404


def test_work_order_to_inwards_preserves_many_to_many_and_routing_versions(api, world):
    t = ok(get(api, "/traceability/work-orders/WO-1001"))
    S.CCTraceWorkOrder(**t)
    assert {i["inward_number"] for i in t["inwards"]} == {world["i1"]["inward_number"], world["i2"]["inward_number"]}
    assert t["allocations_total"] == 2 and len(t["units"]) == 2 and t["active_routing_version"] == 1
    assert t["usable_good_blanks"] == 7 and t["cut_results_total"] == 2 and t["truncated"] is False
    roll = {i["inward_number"]: i for i in t["inwards"]}[world["i1"]["inward_number"]]
    assert (roll["unit_count"], roll["allocation_count"], roll["planned_length_mm"], roll["consumed_length_mm"]) == (1, 1, 600, 535)
    assert any("cannot prove" in line or "not available" in line for line in t["limitations"])
    t2 = ok(get(api, "/traceability/work-orders/WO-1002"))
    assert [r["version"] for r in t2["routings"]] == [2, 1] and t2["active_routing_version"] == 2
    assert {i["inward_number"] for i in t2["inwards"]} == {world["i1"]["inward_number"]}
    assert len(t2["allocations"]) == 2 and {a["routing_version"] for a in t2["allocations"]} == {1}
    assert t2["usable_good_blanks"] == 0
    assert get(api, "/traceability/work-orders/NOPE").status_code == 404


# ================================================================== gate status (pinned to the real Phase 10 gate)
def gate_status(api, wo_number):
    return ok(get(api, f"/work-orders/{wo_number}/gate-status"))


def pin(api, wo_number, ctx_stage="F2"):
    """The status's remaining capacity must be exactly what the real gate allows: capacity passes, capacity+1 does not."""
    from fastapi import HTTPException
    db = api.db
    wo = db.query(WorkOrder).filter_by(wo_number=wo_number).one()
    routes = sorted(wo.routes, key=lambda r: r.sequence)
    wip = db.query(StageWIP).filter_by(work_order_id=wo.id, stage=routes[0].stage).first()
    existing = (wip.ok_qty + wip.rejected_qty) if wip else 0
    s = gate_status(api, wo_number)
    allowed = lambda extra: Gate.enforce_first_stage_production(db, wo, routes, routes[0].stage, existing, extra) or True
    if s["verdict"] == "NOT_GATED":
        assert allowed(10_000)
        return s
    cap = s["remaining_capacity"] or 0 if s["first_stage_valid"] else 0
    if cap:
        assert allowed(cap)
    with pytest.raises(HTTPException) as e:
        Gate.enforce_first_stage_production(db, wo, routes, routes[0].stage, existing, cap + 1)
    assert e.value.status_code == 400
    return s


def test_gate_status_for_a_work_order_with_no_china_routing(api):
    build(api.db, "WO-G1", route=("F1", "F2", "DISPATCH"), with_routing=False)
    s = pin(api, "WO-G1")
    assert (s["verdict"], s["gate_applies"], s["material_source"], s["routing_id"]) == ("NOT_GATED", False, None, None)
    S.CCGateStatus(**s)


def test_gate_status_for_an_f1_production_routing(api):
    ctx = build(api.db, "WO-G2", route=("F1", "F2", "DISPATCH"), with_routing=False)
    api.db.add(Routing(work_order_id=ctx["wo"].id, version=1, material_source="F1_PRODUCTION", status="ACTIVE"))
    api.db.commit()
    s = pin(api, "WO-G2")
    assert (s["verdict"], s["gate_applies"], s["material_source"]) == ("NOT_GATED", False, "F1_PRODUCTION")


def test_gate_status_with_a_china_routing_and_no_usable_blanks(api):
    ctx = build(api.db, "WO-G3")
    s = pin(api, "WO-G3")
    assert (s["verdict"], s["gate_applies"], s["first_route_stage"], s["first_stage_valid"], s["usable_good_blanks"],
            s["remaining_capacity"], s["recorded_blanks"], s["planned_blanks"]) == (
        "BLOCKED_NO_USABLE_BLANKS", True, "F2", True, 0, 0, 0, 10)
    assert s["material_source"] == "CONTINUOUS_CASTING" and s["routing_version"] == 1 and s["reasons"]
    do_cut(ctx, 5 * PER_BLANK + 1)                                                    # a variance result: recorded, unusable
    record(ctx, api.db.query(Ledger).filter_by(movement_type="CUT_CONSUME").one().transaction_number, 5, 0, 5,
           consumed=5 * PER_BLANK + 1)
    s = pin(api, "WO-G3")
    assert s["verdict"] == "BLOCKED_NO_USABLE_BLANKS" and s["recorded_blanks"] == 5 and s["usable_good_blanks"] == 0


def test_gate_status_capacity_boundary_matches_real_production(api):
    ctx = build(api.db, "WO-G4")
    reconciled(ctx, good=4, rej=1)
    s = pin(api, "WO-G4")
    assert (s["verdict"], s["usable_good_blanks"], s["remaining_capacity"], s["first_stage_good_qty"],
            s["recorded_blanks"]) == ("ALLOWED_UP_TO", 4, 4, 0, 5)
    produce(ctx, "F2", 3)                                                             # real production through the OMS
    s = pin(api, "WO-G4")
    assert (s["verdict"], s["remaining_capacity"], s["first_stage_good_qty"]) == ("ALLOWED_UP_TO", 1, 3)
    produce(ctx, "F2", 0, 1)                                                          # a rejected piece counts too
    s = pin(api, "WO-G4")
    assert (s["verdict"], s["remaining_capacity"], s["first_stage_good_qty"], s["first_stage_rejected_qty"]) == (
        "EXHAUSTED", 0, 3, 1)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        produce(ctx, "F2", 1)                                                         # and the real gate agrees


def test_gate_status_when_f1_is_still_the_first_route_stage(api):
    ctx = build(api.db, "WO-G5", route=("F1", "F2", "DISPATCH"))
    reconciled(ctx, 4)
    s = pin(api, "WO-G5")
    assert (s["verdict"], s["gate_applies"], s["first_stage_valid"], s["first_route_stage"]) == (
        "BLOCKED_F1_FIRST_STAGE", True, False, "F1")
    assert s["usable_good_blanks"] is None and "F1" in s["reasons"][0]


@pytest.mark.parametrize("status", ["SUPERSEDED", "DRAFT"])
def test_gate_status_ignores_a_non_active_routing(api, status):
    ctx = build(api.db, "WO-G6")
    api.db.query(Routing).one().status = status
    api.db.commit()
    s = pin(api, "WO-G6")
    assert s["verdict"] == "NOT_GATED" and s["gate_applies"] is False


def test_gate_status_is_read_only_and_404s_for_unknown_work_orders(api, spy):
    build(api.db, "WO-G7")
    spy.reset()
    gate_status(api, "WO-G7")
    assert spy.writes() == [] and spy.commits == 0
    assert get(api, "/work-orders/NOPE/gate-status").status_code == 404


# ================================================================== performance: no N+1
def populate(api, inwards):
    m = ok(api.post("/materials", UserRole.ENGINEERING, dict(material_code="PERF", grade="G", section="S", stock_dimension_a_mm=9)))
    for k in range(inwards):
        inw = ok(api.post("/inwards", UserRole.STORE, dict(material_id=m["material_id"], unit_lengths_mm=[500, 400],
                                                           location=f"R{k}")))
        ok(api.post(f"/inwards/{inw['inward_id']}/qa", UserRole.QA, dict(decision="ACCEPTED")))


@pytest.mark.parametrize("path", ["/inwards", "/stock-units", "/ledger", "/allocations", "/routings", "/cut-results",
                                  "/materials"])
def test_list_query_count_does_not_grow_with_the_page_size(api, spy, path):
    populate(api, 12)                                                                  # 12 inwards, 24 units, many rows
    rich = rich_world(api)
    assert page(api, path, {"limit": 500})["total"] >= 2
    counts = {}
    for size in (1, 5, 25):
        spy.reset()
        assert len(page(api, path, {"limit": size})["items"]) == min(size, page(api, path, {"limit": 500})["total"])
        spy.reset()
        get(api, path, {"limit": size})
        counts[size] = spy.selects()
    assert len(set(counts.values())) == 1, counts                                       # constant, whatever the page size
    assert max(counts.values()) <= 10, counts                                           # and small
    assert rich is not None


def test_detail_and_traceability_query_counts_are_bounded(api, spy):
    populate(api, 8)
    w = rich_world(api)
    for path in (f"/stock-units/{w['u1000']}", f"/inwards/{w['i1']['inward_id']}", "/traceability/work-orders/WO-1001",
                 f"/traceability/inwards/{w['i1']['inward_id']}", "/work-orders/WO-1001/gate-status"):
        spy.reset()
        assert get(api, path).status_code == 200
        assert spy.selects() <= 26, (path, spy.selects())
        assert spy.writes() == []


# ================================================================== contract
def test_unknown_query_parameters_are_ignored_like_the_rest_of_the_application(api, world):
    assert get(api, "/inwards", {"bogus": 1}).status_code == 200
    assert page(api, "/inwards", {"bogus": 1})["total"] == page(api, "/inwards")["total"]


def test_read_endpoints_return_404_for_unknown_ids_and_422_for_malformed_ones(api, world):
    for path in ("/materials", "/inwards", "/stock-units", "/routings", "/cut-results", "/traceability/inwards"):
        assert get(api, f"{path}/{uuid.uuid4()}").status_code == 404, path
        assert get(api, f"{path}/not-a-uuid").status_code == 422, path
    assert get(api, "/cut-results/available/extra").status_code == 404


def test_the_available_route_is_not_swallowed_by_the_id_route(api, world):
    r = get(api, "/cut-results/available", {"wo_number": "WO-1002"})
    assert r.status_code == 200 and "items" in r.json()


def test_the_read_layer_adds_no_write_verbs(api, world):
    for path in ("/inwards", "/stock-units", "/ledger", "/cut-results", "/routings", "/allocations", "/materials"):
        for verb in ("put", "delete"):
            assert getattr(api.client, verb)(PREFIX + path, headers=api.headers(UserRole.ADMIN)).status_code == 405
    for path in ("/inwards/{i}", "/stock-units/{u}", "/cut-results/{c}", "/routings/{r}"):
        url = PREFIX + path.format(i=world["i1"]["inward_id"], u=world["u1000"], c=uuid.uuid4(),
                                   r=world["r1"]["routing_id"])
        for verb in ("put", "delete", "post"):
            assert getattr(api.client, verb)(url, headers=api.headers(UserRole.ADMIN)).status_code in (404, 405), (verb, path)
