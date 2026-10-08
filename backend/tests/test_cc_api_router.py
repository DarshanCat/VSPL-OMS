"""Continuous Casting write API router (Phase 11B). In-memory SQLite only; no database file.

The router is a thin adapter over services that already have hundreds of business-rule tests, so these tests
prove the ADAPTER: every endpoint reaches its service with the validated payload and the authenticated user and
returns the service's response unchanged; authentication and role dependencies use the frozen CC_* tuples;
malformed input and unknown fields are rejected before any service runs; service errors (400/404/409) propagate
untouched; replays keep their indicators; and the router never commits (or touches the database) by itself.
"""
import inspect
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.core.security import create_access_token, hash_password
from app.core import roles as R
from app.models import continuous_casting as cc
from app.models.audit import AuditLog
from app.models.user import User, UserRole
import app.api.v1.continuous_casting as router_module
from app.schemas.continuous_casting import (
    CCAllocationResult, CCCutResultResult, CCInwardQADecisionResult, CCInwardResult, CCMaterialResult,
    CCRoutingReleaseResult, CCRoutingResult, CCSplitResult, CCStockMovementResult, CCUnitMovementResult,
)

from test_cc_reservation_service import make_wo

PREFIX = "/api/v1/continuous-casting"
Unit, Ledger = cc.ContinuousCastingStockUnit, cc.ContinuousCastingStockLedger
CC_TABLES = ["cc_materials", "cc_inwards", "cc_stock_units", "cc_routings", "cc_allocations", "cc_stock_ledger",
             "cc_cut_records", "audit_logs"]

# (method, path template, allowed roles); None = any authenticated user
ENDPOINTS = [
    ("POST", "/materials", R.CC_MATERIAL_MASTER_ROLES),
    ("PATCH", "/materials/{id}", R.CC_MATERIAL_MASTER_ROLES),
    ("GET", "/materials/{id}", None),
    ("POST", "/inwards", R.CC_INWARD_ROLES),
    ("POST", "/inwards/{id}/qa", R.CC_QA_ROLES),
    ("POST", "/routings", R.CC_ROUTING_ROLES),
    ("POST", "/routings/supersede", R.CC_ROUTING_ROLES),
    ("POST", "/allocations", R.CC_RESERVE_ROLES),
    ("POST", "/reservations", R.CC_RESERVE_ROLES),
    ("POST", "/reservations/release", R.CC_RESERVE_ROLES),
    ("POST", "/routings/{id}/release-superseded", R.CC_RESERVE_ROLES),
    ("POST", "/issues", R.CC_ISSUE_ROLES),
    ("POST", "/cut-consume", R.CC_CUT_ROLES),
    ("POST", "/returns", R.CC_ISSUE_ROLES),
    ("POST", "/splits", R.CC_ISSUE_ROLES),
    ("POST", "/holds", R.CC_HOLD_ROLES),
    ("POST", "/holds/release", R.CC_HOLD_RELEASE_ROLES),
    ("POST", "/scrap", R.CC_SCRAP_ROLES),
    ("POST", "/adjustments/out", R.CC_ADJUSTMENT_ROLES),
    ("POST", "/adjustments/in", R.CC_ADJUSTMENT_ROLES),
    ("POST", "/cut-results", R.CC_CUT_ROLES),
]
WRITE_ENDPOINTS = [e for e in ENDPOINTS if e[0] != "GET"]
# The approved Phase 11C read endpoints (GET /materials/{id} is already part of ENDPOINTS above).
READ_ENDPOINTS_11C = [
    "/materials", "/stock-summary", "/inwards", "/inwards/{inward_id}", "/stock-units", "/stock-units/{unit_id}", "/routings",
    "/routings/{routing_id}", "/allocations", "/ledger", "/cut-results", "/cut-results/available",
    "/cut-results/{cut_result_id}", "/traceability/inwards/{inward_id}", "/traceability/work-orders/{wo_number}",
    "/work-orders/{wo_number}/gate-status",
]


def ids(endpoints):
    return [f"{m} {p}" for m, p, _r in endpoints]


# ------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert engine.url.database == ":memory:"
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


class Api:
    """TestClient wrapper: bearer tokens per role, and the number of database commits each request caused."""

    def __init__(self, db):
        self.db = db
        self.client = TestClient(app)
        self._users = {}
        self._commits = 0
        self.last_commits = 0
        event.listen(db.get_bind(), "commit", self._on_commit)

    def _on_commit(self, conn):
        self._commits += 1

    def close(self):
        event.remove(self.db.get_bind(), "commit", self._on_commit)

    def headers(self, role):
        if role not in self._users:
            email = f"{role.value}@example.test"
            user = User(full_name=f"{role.value} user", email=email, hashed_password=hash_password("x"),
                        role=role, is_active=True)
            self.db.add(user)
            self.db.commit()
            self._users[role] = create_access_token({"sub": email, "role": role.value})
        return {"Authorization": f"Bearer {self._users[role]}"}

    def call(self, method, path, role=None, json=None, headers=None):
        hdr = headers if headers is not None else (self.headers(role) if role is not None else {})
        before = self._commits
        resp = self.client.request(method, PREFIX + path, json=json, headers=hdr)
        self.last_commits = self._commits - before
        return resp

    def post(self, path, role, json=None):
        return self.call("POST", path, role, json)


@pytest.fixture()
def api(test_db):
    def override_get_db():
        yield test_db
    app.dependency_overrides[get_db] = override_get_db
    helper = Api(test_db)
    for role in UserRole:                       # tokens/users up front, so request commit counts are clean
        helper.headers(role)
    yield helper
    helper.close()
    app.dependency_overrides.clear()


def state(db):
    db.expire_all()
    from sqlalchemy import func, select
    return {t: db.execute(select(func.count()).select_from(Base.metadata.tables[t])).scalar() for t in CC_TABLES}


def ok(resp):
    assert resp.status_code == 200, (resp.status_code, resp.text)
    return resp.json()


ROUTING = dict(required_grade="SG450", required_section="ROUND", finished_dimension_a_mm=80,
               finished_axial_length_mm=100, machining_stock_a_mm=2, machining_stock_b_mm=2, planned_blanks=10,
               planned_cuts=10, kerf_mm=3, end_trim_mm=0)                       # blank 104 mm, kerf 3 mm


def build_world(api):
    """Material -> inward -> QA acceptance -> WO -> routing -> allocation, all through the API."""
    db = api.db
    m = ok(api.post("/materials", UserRole.ENGINEERING,
                    dict(material_code="CC-API-1", grade="SG450", section="ROUND", stock_dimension_a_mm=200)))
    inw = ok(api.post("/inwards", UserRole.STORE, dict(material_id=m["material_id"], unit_lengths_mm=[1000, 800])))
    ok(api.post(f"/inwards/{inw['inward_id']}/qa", UserRole.QA, dict(decision="ACCEPTED")))
    make_wo(db, "WO-1001")
    routing = ok(api.post("/routings", UserRole.ENGINEERING,
                          dict(wo_number="WO-1001", validated_material_id=m["material_id"], **ROUTING)))
    unit_a = db.query(Unit).filter_by(unit_number=inw["units"][0]["unit_number"]).one()
    unit_b = db.query(Unit).filter_by(unit_number=inw["units"][1]["unit_number"]).one()
    alloc = ok(api.post("/allocations", UserRole.PLANNER, dict(
        routing_id=routing["routing_id"], stock_unit_id=str(unit_a.id), planned_length_mm=600)))
    return dict(material=m, inward=inw, routing=routing, alloc=alloc, unit_a=str(unit_a.id), unit_b=str(unit_b.id),
                inward_id=inw["inward_id"], rid=routing["routing_id"], aid=alloc["allocation_id"])


@pytest.fixture()
def world(api):
    return build_world(api)


# ================================================================== router shape
def test_all_endpoints_are_registered_under_one_prefix():
    paths = app.openapi()["paths"]
    found = sorted((p, m.upper()) for p, v in paths.items() if p.startswith(PREFIX) for m in v)
    expected = sorted((PREFIX + path.replace("{id}", "{" + (
        "material_id" if "/materials/" in path else "inward_id" if "/inwards/" in path else "routing_id") + "}"),
        method) for method, path, _r in ENDPOINTS)
    assert len(expected) == 21                                       # the Phase 11B operations, unchanged
    expected = sorted(expected + [(PREFIX + path, "GET") for path in READ_ENDPOINTS_11C])
    assert found == expected and len(found) == 37


def test_the_router_contains_no_business_logic_and_never_touches_the_database():
    import ast
    tree = ast.parse(inspect.getsource(router_module))
    # no control flow, no error handling: a handler cannot decide, catch or rewrite anything
    for node in ast.walk(tree):
        assert not isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.Raise, ast.With, ast.Assert,
                                     ast.IfExp, ast.BoolOp, ast.Compare)), ast.dump(node)[:80]
    # no database access at all
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"commit", "rollback", "flush", "add", "query", "execute", "delete", "refresh", "begin",
                         "merge", "expunge", "close"}, called
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    modules = {(n.module if isinstance(n, ast.ImportFrom) else n.names[0].name) for n in imports}
    assert not any(m and m.startswith("sqlalchemy") and m != "sqlalchemy.orm" for m in modules)
    assert not any(m and m.startswith("app.models") and m != "app.models.user" for m in modules)
    assert "fastapi.exceptions" not in modules
    handlers = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert len(handlers) == 37                   # 21 write handlers (Phase 11B) + 16 read handlers (Phase 11C/Stock Summary)
    for fn in handlers:                          # a handler is: (optionally) build the request, then return ONE service call
        statements = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        assert isinstance(statements[-1], ast.Return), fn.name
        service_call = statements[-1].value
        assert isinstance(service_call, ast.Call) and service_call.func.value.id.startswith("ContinuousCasting"), fn.name
        for s in statements[:-1]:                # the only allowed pre-step: assigning the request built from the path id
            assert isinstance(s, ast.Assign) and s.targets[0].id == "request", fn.name
        assert len(statements) <= 2, fn.name


def test_role_dependencies_use_the_frozen_tuples():
    from app.core import roles
    for name in ("CC_MATERIAL_MASTER_ROLES", "CC_INWARD_ROLES", "CC_QA_ROLES", "CC_ROUTING_ROLES", "CC_RESERVE_ROLES",
                 "CC_ISSUE_ROLES", "CC_CUT_ROLES", "CC_HOLD_ROLES", "CC_HOLD_RELEASE_ROLES", "CC_SCRAP_ROLES",
                 "CC_ADJUSTMENT_ROLES"):
        assert hasattr(router_module, name) and getattr(router_module, name) is getattr(roles, name)


# ================================================================== authentication
def test_unauthenticated_requests_follow_the_existing_application_behaviour(api):
    baseline = api.client.get("/api/v1/roles").status_code                  # an existing authenticated router
    assert baseline in (401, 403)
    before = state(api.db)
    for method, path, _roles in ENDPOINTS:
        resp = api.call(method, path.format(id=uuid.uuid4()), headers={}, json={} if method != "GET" else None)
        assert resp.status_code == baseline, (method, path)
        assert api.last_commits == 0
    assert state(api.db) == before


@pytest.mark.parametrize("method,path,allowed", ENDPOINTS, ids=ids(ENDPOINTS))
def test_an_invalid_token_is_a_401(api, method, path, allowed):
    before = state(api.db)
    resp = api.call(method, path.format(id=uuid.uuid4()), headers={"Authorization": "Bearer not-a-token"},
                    json={} if method != "GET" else None)
    assert resp.status_code == 401 and api.last_commits == 0 and state(api.db) == before


def test_a_deactivated_user_is_a_401(api):
    headers = api.headers(UserRole.ENGINEERING)
    api.db.query(User).filter_by(role=UserRole.ENGINEERING).one().is_active = False
    api.db.commit()
    assert api.call("POST", "/materials", headers=headers, json={}).status_code == 401


# ================================================================== role authorization
@pytest.mark.parametrize("method,path,allowed", [e for e in ENDPOINTS if e[2] is not None],
                         ids=ids([e for e in ENDPOINTS if e[2] is not None]))
def test_roles_outside_the_tuple_get_403_and_roles_inside_get_through(api, method, path, allowed):
    url = path.format(id=uuid.uuid4())
    body = {} if method != "GET" else None
    before = state(api.db)
    for role in UserRole:
        resp = api.call(method, url, role, json=body)
        if role in allowed:
            assert resp.status_code not in (401, 403), (role, resp.status_code, resp.text)      # reached the adapter
        else:
            assert resp.status_code == 403 and resp.json()["detail"] == "Insufficient permissions", role
            assert api.last_commits == 0
    assert state(api.db) == before                                 # nothing written by any of those calls


def test_material_get_needs_only_authentication(api, world):
    for role in UserRole:
        resp = api.call("GET", f"/materials/{world['material']['material_id']}", role)
        assert resp.status_code == 200 and resp.json()["material_code"] == "CC-API-1"
        assert api.last_commits == 0


# ================================================================== malformed requests
@pytest.mark.parametrize("method,path,allowed", [e for e in WRITE_ENDPOINTS if "{id}" not in e[1]],
                         ids=ids([e for e in WRITE_ENDPOINTS if "{id}" not in e[1]]))
def test_malformed_bodies_are_422_and_never_reach_a_service(api, method, path, allowed):
    role = allowed[-1]
    before = state(api.db)
    for bad in ({}, {"length_mm": "abc"}, {"bogus": 1}, []):
        resp = api.call(method, path, role, json=bad)
        assert resp.status_code == 422, (bad, resp.status_code)
        assert isinstance(resp.json()["detail"], list)
        assert api.last_commits == 0
    assert state(api.db) == before


@pytest.mark.parametrize("path", ["/materials/not-a-uuid", "/inwards/not-a-uuid/qa", "/routings/not-a-uuid/release-superseded"])
def test_malformed_path_ids_are_422(api, path):
    method = "PATCH" if path.startswith("/materials") else "POST"
    assert api.call(method, path, UserRole.ADMIN, json={"decision": "ACCEPTED"} if "qa" in path else {}).status_code == 422
    assert api.call("GET", "/materials/not-a-uuid", UserRole.ADMIN).status_code == 422


def test_the_qa_body_enforces_the_reason_rule_at_the_boundary(api, world):
    before = state(api.db)
    for bad in ({"decision": "REJECTED"}, {"decision": "ON_HOLD", "reason": "  "}, {"decision": "PENDING_QA"},
                {"decision": "ACCEPTED", "inward_id": world["inward_id"]}, {}):
        assert api.post(f"/inwards/{world['inward_id']}/qa", UserRole.QA, bad).status_code == 422
    assert state(api.db) == before


# ================================================================== service errors propagate untouched
def test_service_400_404_409_propagate_with_the_services_own_messages(api, world):
    a = dict(routing_id=world["rid"], allocation_id=world["aid"])
    before = state(api.db)
    r = api.post("/reservations", UserRole.PLANNER, dict(**a, length_mm=601))                    # plan is 600 mm
    assert r.status_code == 400 and "planned" in r.json()["detail"] and api.last_commits == 0
    r = api.post("/reservations", UserRole.PLANNER, dict(routing_id=world["rid"], allocation_id=str(uuid.uuid4()),
                                                          length_mm=10))
    assert r.status_code == 404 and r.json()["detail"] == "Allocation not found." and api.last_commits == 0
    r = api.post("/materials", UserRole.ENGINEERING,                                              # duplicate code
                 dict(material_code="cc-api-1", grade="G", section="S", stock_dimension_a_mm=10))
    assert r.status_code == 409 and "already exists" in r.json()["detail"] and api.last_commits == 0
    r = api.call("PATCH", f"/materials/{uuid.uuid4()}", UserRole.ENGINEERING, json={"description": "x"})
    assert r.status_code == 404 and api.last_commits == 0
    r = api.call("PATCH", f"/materials/{world['material']['material_id']}", UserRole.ENGINEERING,
                 json={"grade": "SG999"})                                                         # referenced: frozen
    assert r.status_code == 400 and "can no longer be changed" in r.json()["detail"] and api.last_commits == 0
    r = api.post(f"/inwards/{world['inward_id']}/qa", UserRole.QA, dict(decision="REJECTED", reason="late"))
    assert r.status_code == 400 and "already ACCEPTED" in r.json()["detail"] and api.last_commits == 0
    assert state(api.db) == before


def test_a_422_body_is_the_applications_validation_shape(api):
    r = api.post("/scrap", UserRole.STORE, {"length_mm": "abc"})
    assert r.status_code == 422 and {"loc", "msg", "type"} <= set(r.json()["detail"][0])


# ================================================================== the whole flow, endpoint by endpoint
def test_every_write_endpoint_reaches_its_service_and_returns_the_service_response(api):
    db = api.db
    w = build_world(api)
    material_id, rid, aid, iid, ua, ub = w["material"]["material_id"], w["rid"], w["aid"], w["inward_id"], w["unit_a"], w["unit_b"]
    sent = {}                                               # endpoint -> a valid payload, for the unknown-field sweep

    def step(path, role, payload, parse=None, expect_commits=1):
        sent[path] = payload
        resp = api.post(path, role, payload)
        body = ok(resp)
        assert api.last_commits == expect_commits, (path, api.last_commits)     # the SERVICE committed once; the router never
        return parse(**body) if parse else body

    # material
    assert w["material"]["success"] and CCMaterialResult(**w["material"]).referenced is False
    got = ok(api.call("GET", f"/materials/{material_id}", UserRole.STORE))
    assert got["referenced"] is True and got["inward_count"] == 1 and got["routing_count"] == 1 and api.last_commits == 0
    patched = ok(api.call("PATCH", f"/materials/{material_id}", UserRole.ENGINEERING, json={"description": "bar"}))
    assert patched["description"] == "bar" and api.last_commits == 1
    cleared = ok(api.call("PATCH", f"/materials/{material_id}", UserRole.ADMIN, json={"description": None}))
    assert cleared["description"] is None and api.last_commits == 1             # an explicit null survives the adapter
    # inward / qa / routing / allocation (already exercised by build_world)
    assert CCInwardResult(**w["inward"]).reconciled and CCRoutingResult(**w["routing"]).status == "ACTIVE"
    assert CCAllocationResult(**w["alloc"]).planned_length_mm == 600
    # reserve -> issue -> cut -> cut result -> return
    base = dict(routing_id=rid, allocation_id=aid)
    r = step("/reservations", UserRole.PLANNER, dict(**base, length_mm=600), CCStockMovementResult)
    assert (r.movement_type, r.unit_reserved_length_mm) == ("RESERVE", 600)
    r = step("/issues", UserRole.STORE, dict(**base, stock_unit_id=ua, length_mm=600), CCStockMovementResult)
    assert (r.movement_type, r.unit_issued_length_mm, r.unit_reserved_length_mm) == ("ISSUE", 600, 0)
    r = step("/cut-consume", UserRole.PRODUCTION_MANAGER, dict(**base, stock_unit_id=ua, length_mm=535),
             CCStockMovementResult)
    assert (r.movement_type, r.unit_consumed_length_mm, r.unit_remaining_length_mm) == ("CUT_CONSUME", 535, 465)
    cut_txn = r.ledger_transaction_number
    cut_payload = dict(**base, stock_unit_id=ua, ledger_transaction_number=cut_txn, consumed_length_mm=535,
                       actual_good_blanks=5, rejected_blanks=0, actual_cuts=5, end_trim_mm=0,
                       client_request_id="CUT-API-1")
    cr = step("/cut-results", UserRole.PRODUCTION_MANAGER, cut_payload, CCCutResultResult)
    assert (cr.reconciliation_status, cr.variance_mm, cr.usable_for_oms, cr.replayed) == ("RECONCILED", 0, True, False)
    replay = ok(api.post("/cut-results", UserRole.ADMIN, cut_payload))                  # replay keeps its indicator
    assert replay["replayed"] is True and replay["cut_number"] == cr.cut_number and api.last_commits == 1
    assert api.post("/cut-results", UserRole.ADMIN, {**cut_payload, "actual_good_blanks": 4,
                                                     "rejected_blanks": 1}).status_code == 409
    r = step("/returns", UserRole.STORE, dict(**base, stock_unit_id=ua, inward_id=iid, length_mm=65),
             CCStockMovementResult)
    assert (r.movement_type, r.unit_issued_length_mm, r.unit_remaining_length_mm) == ("RETURN", 0, 465)
    # reserve again and release part of it
    step("/reservations", UserRole.PLANNER, dict(**base, length_mm=65), CCStockMovementResult)
    r = step("/reservations/release", UserRole.PLANNER, dict(**base, length_mm=30), CCStockMovementResult)
    assert (r.movement_type, r.unit_reserved_length_mm) == ("RELEASE", 35)
    # split -> hold -> hold release on the child
    s = step("/splits", UserRole.STORE, dict(stock_unit_id=ua, inward_id=iid, length_mm=100), CCSplitResult)
    child = s.child_unit_id
    assert (s.parent_remaining_length_mm, s.child_remaining_length_mm) == (365, 100)
    h = step("/holds", UserRole.QA, dict(stock_unit_id=child, inward_id=iid, reason="surface crack"),
             CCUnitMovementResult)
    assert (h.movement_type, h.unit_status) == ("HOLD", "ON_HOLD")
    h = step("/holds/release", UserRole.QA, dict(stock_unit_id=child, inward_id=iid, reason="cleared"),
             CCUnitMovementResult)
    assert (h.movement_type, h.unit_status) == ("HOLD_RELEASE", "IN_STOCK")
    # scrap (with replay), adjustments (with replay)
    scrap_payload = dict(stock_unit_id=child, inward_id=iid, length_mm=50, reason="melt", reference="S-1",
                         client_request_id="SCRAP-API-1")
    sc = step("/scrap", UserRole.STORE, scrap_payload, CCUnitMovementResult)
    assert (sc.movement_type, sc.unit_remaining_length_mm, sc.unit_scrapped_length_mm, sc.replayed) == ("SCRAP", 50, 50, False)
    sc2 = ok(api.post("/scrap", UserRole.STORE, scrap_payload))
    assert sc2["replayed"] is True and sc2["ledger_transaction_number"] == sc.ledger_transaction_number
    assert api.last_commits == 1
    out_payload = dict(stock_unit_id=ub, inward_id=iid, length_mm=10, reason="count", reference="C-1",
                       client_request_id="ADJ-OUT-1")
    ao = step("/adjustments/out", UserRole.ADMIN, out_payload, CCUnitMovementResult)
    assert (ao.movement_type, ao.unit_remaining_length_mm, ao.unit_net_adjustment_mm) == ("ADJUSTMENT_OUT", 790, -10)
    in_payload = dict(stock_unit_id=ub, inward_id=iid, length_mm=10, reason="recount", reference="C-2",
                      client_request_id="ADJ-IN-1")
    ai = step("/adjustments/in", UserRole.ADMIN, in_payload, CCUnitMovementResult)
    assert (ai.movement_type, ai.unit_remaining_length_mm, ai.unit_net_adjustment_mm) == ("ADJUSTMENT_IN", 800, 0)
    assert ok(api.post("/adjustments/out", UserRole.ADMIN, out_payload))["replayed"] is True
    # supersede the routing, then release what it still reserves
    sup_payload = dict(wo_number="WO-1001", validated_material_id=material_id, reason="design change", **ROUTING)
    sup = step("/routings/supersede", UserRole.ENGINEERING, sup_payload, CCRoutingResult)
    assert (sup.version, sup.superseded_version, sup.status) == (2, 1, "ACTIVE")
    rel_path = f"/routings/{rid}/release-superseded"
    rel = ok(api.post(rel_path, UserRole.PLANNER, {"reason": "routing superseded"}))
    assert api.last_commits == 1
    rel = CCRoutingReleaseResult(**rel)
    assert (rel.allocations_released, rel.total_released_length_mm) == (1, 35)
    again = ok(api.post(rel_path, UserRole.PLANNER, {}))                                  # nothing left to release
    assert again["allocations_released"] == 0
    # ledger and audit trail were written by the services
    assert db.query(Ledger).filter_by(movement_type="CUT_CONSUME").count() == 1
    assert db.query(AuditLog).filter(AuditLog.action == "CC_CUT_RESULT").count() == 1

    # unknown fields are refused with 422 on every endpoint that has a body, before any service runs
    before = state(db)
    for path, payload in sent.items():
        resp = api.post(path, UserRole.ADMIN, {**payload, "unknown_field": 1})
        assert resp.status_code == 422, path
        assert any(e["type"] == "extra_forbidden" for e in resp.json()["detail"]), path
        assert api.last_commits == 0
    for path, payload in ((f"/inwards/{iid}/qa", {"decision": "ACCEPTED", "unknown_field": 1}),
                          (rel_path, {"unknown_field": 1})):
        assert api.post(path, UserRole.ADMIN, payload).status_code == 422
    assert api.call("PATCH", f"/materials/{material_id}", UserRole.ADMIN, json={"unknown_field": 1}).status_code == 422
    assert state(db) == before


def test_every_write_endpoint_is_covered_by_the_flow():
    covered = {"/materials", "/materials/{id}", "/inwards", "/inwards/{id}/qa", "/routings", "/routings/supersede",
               "/allocations", "/reservations", "/reservations/release", "/routings/{id}/release-superseded", "/issues",
               "/cut-consume", "/returns", "/splits", "/holds", "/holds/release", "/scrap", "/adjustments/out",
               "/adjustments/in", "/cut-results"}
    assert {p for _m, p, _r in ENDPOINTS} == covered | set()


# ================================================================== the router never commits by itself
def test_failures_cause_no_commit_and_no_partial_writes(api, world):
    a = dict(routing_id=world["rid"], allocation_id=world["aid"])
    before = state(api.db)
    for path, role, payload, status in (
            ("/reservations", UserRole.PLANNER, dict(**a, length_mm=9999), 400),
            ("/issues", UserRole.STORE, dict(**a, stock_unit_id=world["unit_a"], length_mm=1), 400),   # nothing reserved
            ("/scrap", UserRole.STORE, dict(stock_unit_id=world["unit_a"], inward_id=world["inward_id"],
                                            length_mm=5000, reason="x", reference="y"), 400),
            ("/holds/release", UserRole.QA, dict(stock_unit_id=world["unit_a"], inward_id=world["inward_id"],
                                                 reason="x"), 400)):                                  # not on hold
        r = api.post(path, role, payload)
        assert r.status_code == status and api.last_commits == 0, (path, r.text)
    assert state(api.db) == before


def test_a_failure_inside_the_service_leaves_nothing_behind(api, world, monkeypatch):
    """The service owns the transaction: if its commit fails, everything rolls back and the error surfaces."""
    before = state(api.db)
    calls = {"n": 0}
    real_commit = api.db.commit

    def failing_commit():
        calls["n"] += 1
        raise RuntimeError("commit failed")

    monkeypatch.setattr(api.db, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        api.client.post(PREFIX + "/reservations", json=dict(routing_id=world["rid"], allocation_id=world["aid"],
                                                            length_mm=10), headers=api.headers(UserRole.PLANNER))
    monkeypatch.setattr(api.db, "commit", real_commit)
    assert calls["n"] == 1 and state(api.db) == before
    assert ok(api.post("/reservations", UserRole.PLANNER, dict(routing_id=world["rid"], allocation_id=world["aid"],
                                                               length_mm=10)))["success"]


def test_the_endpoints_pass_the_authenticated_user_to_the_service(api, world):
    r = ok(api.post("/reservations", UserRole.ADMIN, dict(routing_id=world["rid"], allocation_id=world["aid"],
                                                          length_mm=50)))
    row = api.db.query(Ledger).filter_by(transaction_number=r["ledger_transaction_number"]).one()
    admin = api.db.query(User).filter_by(role=UserRole.ADMIN).one()
    assert row.performed_by_id == admin.id and row.performed_by_name == admin.full_name
    mat = ok(api.post("/materials", UserRole.ENGINEERING,
                      dict(material_code="CC-API-2", grade="G", section="S", stock_dimension_a_mm=5)))
    assert mat["created_by"] == api.db.query(User).filter_by(role=UserRole.ENGINEERING).one().full_name


def test_oms_and_frontend_scope_is_untouched_by_the_router():
    from pathlib import Path
    root = Path(router_module.__file__).resolve().parents[3]
    changed = {p.name for p in (root / "app" / "api" / "v1").glob("*.py")}
    assert "continuous_casting.py" in changed
    source = Path(router_module.__file__).read_text(encoding="utf-8")
    for name in ("production_service", "oms_engine", "StageWIP", "WORoute"):
        assert name not in source
    # "work_order" appears in the approved Phase 11C endpoint names (traceability/work-orders), so the rule is
    # enforced where it matters: the router imports no OMS module at all.
    import ast
    imported = [n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and n.module]
    imported += [a.name for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Import) for a in n.names]
    for module in imported:
        assert not module.startswith(("app.models.work_order", "app.models.production", "app.oms_core",
                                      "app.services.production_service", "app.services.oms_integration_service",
                                      "app.services.operations_service")), module
