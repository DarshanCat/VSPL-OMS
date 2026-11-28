"""Sales dashboards: Edit price. Changes one PO line's price (or one schedule's price) and nothing else."""
from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_current_user  # noqa: F401
from app.core.rate_limit import limiter
from app.core.roles import PO_MASTER_EDIT_ROLES
from app.main import app
from app.models.audit import AuditLog
from app.models.master_data import POLine, POMaster, POStatus, ScheduleMaster, ScheduleStatus
from app.models.order import Order, OrderStatus
from app.models.user import UserRole
from app.services import sales_report_service as svc
from app.services.master_data_service import POMasterService, ScheduleMasterService
from app.schemas.master_data import ScheduleUpdate
from tests.test_setup_planning import env  # noqa: F401
from tests.test_setup_planning_api import _auth, _login, _user  # noqa: F401


def _po_with_lines(env, number="PO-E1"):
    p = POMaster(po_number=number, customer_id=env.cust.id, total_value=0)
    env.db.add(p)
    env.db.flush()
    a = POLine(po_id=p.id, part_id=env.part.id, po_qty=10, unit_price=100.0, line_total=1000.0, required_date=date(2026, 12, 5))
    b = POLine(po_id=p.id, part_id=env.part.id, po_qty=4, unit_price=50.0, line_total=200.0, required_date=date(2027, 1, 9))
    env.db.add_all([a, b])
    env.db.flush()
    p.total_value = 1200.0
    env.db.commit()
    return p, a, b


def test_price_edit_changes_only_that_line(env):
    p, a, b = _po_with_lines(env)
    out = POMasterService.update_line_price(env.db, str(p.id), str(a.id), 120.5, current_user=env.admin)
    env.db.refresh(a)
    env.db.refresh(b)
    env.db.refresh(p)
    assert (a.unit_price, a.line_total) == (120.5, 1205.0)
    assert (a.po_qty, a.required_date) == (10, date(2026, 12, 5))             # nothing else on the line moved
    assert (b.unit_price, b.line_total, b.po_qty, b.required_date) == (50.0, 200.0, 4, date(2027, 1, 9))
    assert p.total_value == 1405.0 and out.total_value == 1405.0               # PO total follows its lines
    assert env.db.query(POLine).filter(POLine.po_id == p.id).count() == 2      # no line added or removed
    row = env.db.query(AuditLog).filter(AuditLog.action == "PO_LINE_PRICE_UPDATED").one()
    assert "100.0 -> 120.5" in row.details and "PO-E1" in row.details


def test_price_edit_refusals(env):
    p, a, b = _po_with_lines(env)
    _p2, a2, _b2 = _po_with_lines(env, "PO-E2")
    with pytest.raises(HTTPException) as e:
        POMasterService.update_line_price(env.db, str(p.id), str(a2.id), 10, current_user=env.admin)   # line of another PO
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        POMasterService.update_line_price(env.db, "00000000-0000-0000-0000-000000000000", str(a.id), 10, current_user=env.admin)
    assert e.value.status_code == 404
    p.status = POStatus.CANCELLED
    env.db.commit()
    with pytest.raises(HTTPException) as e:
        POMasterService.update_line_price(env.db, str(p.id), str(a.id), 10, current_user=env.admin)
    assert e.value.status_code == 400
    env.db.refresh(a)
    assert a.unit_price == 100.0                                                 # refused edits change nothing


def test_schedule_price_edit_only_changes_price_and_value(env):
    s = ScheduleMaster(schedule_number="SCH-E1", customer_id=env.cust.id, part_id=env.part.id, scheduled_qty=11,
                       unit_price=25686.0, total_value=282546.0, required_date=date(2025, 7, 31),
                       po_status=ScheduleStatus.AWAITING_PO, customer_schedule_ref="REF-1")
    env.db.add(s)
    env.db.commit()
    ScheduleMasterService.update_schedule(env.db, str(s.id), ScheduleUpdate(unit_price=26000), current_user=env.admin)
    env.db.refresh(s)
    assert s.unit_price == 26000.0 and s.total_value == 286000.0
    assert (s.scheduled_qty, s.required_date, s.po_status, s.customer_schedule_ref) == (11, date(2025, 7, 31), ScheduleStatus.AWAITING_PO, "REF-1")
    assert "unit_price: 25686.0 -> 26000.0" in env.db.query(AuditLog).filter(AuditLog.action == "SCHEDULE_UPDATED").one().details


def test_dashboard_rows_say_what_a_price_edit_changes(env):
    p, a, b = _po_with_lines(env, "PO-E3")
    env.db.add(Order(oar_number="OAR-E3", customer_id=env.cust.id, part_id=env.part.id, customer_po="PO-E3", po_qty=10,
                     po_line_id=a.id, delivery_date=date(2026, 12, 10), status=OrderStatus.ACCEPT))
    s = ScheduleMaster(schedule_number="SCH-E3", customer_id=env.cust.id, part_id=env.part.id, scheduled_qty=5, unit_price=9.0,
                       total_value=45.0, required_date=date(2026, 12, 20), po_status=ScheduleStatus.AWAITING_PO)
    env.db.add(s)
    env.db.commit()
    rep = svc.build_report(env.db, today=date(2026, 11, 26))
    by = {(i["source"], i["ref"]): i for i in rep["items"]}
    line_target = {"type": "PO_LINE", "po_id": str(p.id), "line_id": str(a.id)}
    assert by[("OAR", "OAR-E3")]["price_target"] == line_target                 # an order's price comes from its PO line
    assert by[("PO_LINE", "PO-E3")]["price_target"] == {"type": "PO_LINE", "po_id": str(p.id), "line_id": str(b.id)}
    assert by[("SCHEDULE", "SCH-E3")]["price_target"] == {"type": "SCHEDULE", "id": str(s.id)}
    sched = svc.build_schedule_report(env.db, today=date(2026, 11, 26))
    assert sched["items"][0]["price_target"] == {"type": "SCHEDULE", "id": str(s.id)}
    # the edit shows up on the dashboard
    POMasterService.update_line_price(env.db, str(p.id), str(a.id), 200, current_user=env.admin)
    rep2 = svc.build_report(env.db, today=date(2026, 11, 26))
    assert {(i["source"], i["ref"]): i for i in rep2["items"]}[("OAR", "OAR-E3")]["unit_price"] == 200.0


@pytest.fixture
def client():
    limiter.reset()
    with TestClient(app) as c:
        yield c
    limiter.reset()


def test_price_edit_endpoint_access(client):
    path = "/api/v1/masters/pos/00000000-0000-0000-0000-000000000000/lines/00000000-0000-0000-0000-000000000000/price"
    body = {"unit_price": 10}
    assert client.put(path, json=body).status_code == 401
    for role in (UserRole.OPERATOR, UserRole.STORE, UserRole.ACCOUNTS, UserRole.F1_SUPERVISOR, UserRole.SCM):
        assert client.put(path, json=body, headers=_auth(_user(client, role))).status_code == 403, role
    for role in (UserRole.SALES, UserRole.PLANNER):
        assert role in PO_MASTER_EDIT_ROLES
        assert client.put(path, json=body, headers=_auth(_user(client, role))).status_code == 404, role   # allowed, PO not found
    sales = _auth(_user(client, UserRole.SALES))
    assert client.put(path, json={"unit_price": -1}, headers=sales).status_code == 422                   # negative price refused


# ---------------------------------------------------------------- orders that have no PO line and no schedule
def _bare_order(env, oar, po, qty=600, delivery=date(2026, 11, 22), part=None, status=OrderStatus.ACCEPT):
    o = Order(oar_number=oar, customer_id=env.cust.id, part_id=(part or env.part).id, customer_po=po, po_qty=qty,
              delivery_date=delivery, status=status)
    env.db.add(o)
    env.db.commit()
    return o


def test_unpriced_order_row_points_at_the_order(env):
    o = _bare_order(env, "OAR-0003", "PO-2026-903")
    row = {(i["source"], i["ref"]): i for i in svc.build_report(env.db, today=date(2026, 11, 26))["items"]}[("OAR", "OAR-0003")]
    assert row["unit_price"] is None and row["price_target"] == {"type": "ORDER", "order_id": str(o.id)}


def test_pricing_a_bare_order_records_its_po_line(env):
    o = _bare_order(env, "OAR-0003", "PO-2026-903", qty=600)
    other = _bare_order(env, "OAR-0009", "PO-OTHER", qty=5)
    out = POMasterService.price_order_without_po_line(env.db, str(o.id), 1500.0, current_user=env.admin)
    env.db.refresh(o)
    env.db.refresh(other)
    po = env.db.query(POMaster).filter(POMaster.po_number == "PO-2026-903").one()
    line = env.db.query(POLine).filter(POLine.po_id == po.id).one()
    assert (line.po_qty, line.unit_price, line.line_total, line.required_date) == (600, 1500.0, 900000.0, date(2026, 11, 22))
    assert po.total_value == 900000.0 and out.total_value == 900000.0 and po.status == POStatus.OPEN
    assert o.po_line_id == line.id and o.po_qty == 600                              # the order is linked, nothing else about it moved
    assert other.po_line_id is None                                                  # an unrelated order is untouched
    assert env.db.query(AuditLog).filter(AuditLog.action == "ORDER_PRICE_SET").one().details.count("OAR-0003") == 1
    # the dashboard now prices it, and a second edit goes to the PO line
    row = {(i["source"], i["ref"]): i for i in svc.build_report(env.db, today=date(2026, 11, 26))["items"]}[("OAR", "OAR-0003")]
    assert row["unit_price"] == 1500.0 and row["value"] == 900000.0
    assert row["price_target"] == {"type": "PO_LINE", "po_id": str(po.id), "line_id": str(line.id)}


def test_orders_of_the_same_po_and_part_share_one_new_line(env):
    a = _bare_order(env, "OAR-A", "po-x1", qty=100, delivery=date(2026, 12, 20))
    b = _bare_order(env, "OAR-B", "PO-X1", qty=50, delivery=date(2026, 12, 10))      # same PO, different letter case
    POMasterService.price_order_without_po_line(env.db, str(a.id), 10.0, current_user=env.admin)
    env.db.refresh(a)
    env.db.refresh(b)
    line = env.db.query(POLine).one()
    assert line.po_qty == 150 and line.required_date == date(2026, 12, 10)
    assert a.po_line_id == line.id and b.po_line_id == line.id


def test_line_is_added_to_a_po_that_already_exists(env):
    p, a, b = _po_with_lines(env, "PO-E9")                                          # lines for env.part
    other_part = __import__("app.models.order", fromlist=["Part"]).Part(part_number="P-2", description="Sleeve")
    env.db.add(other_part)
    env.db.commit()
    o = _bare_order(env, "OAR-E9", "PO-E9", qty=7, part=other_part)
    POMasterService.price_order_without_po_line(env.db, str(o.id), 20.0, current_user=env.admin)
    env.db.refresh(p)
    assert env.db.query(POLine).filter(POLine.po_id == p.id).count() == 3
    env.db.refresh(a)
    assert (a.unit_price, a.po_qty) == (100.0, 10)                                   # existing lines untouched
    assert p.total_value == 1200.0 + 140.0


def test_pricing_a_bare_order_refusals(env):
    o = _bare_order(env, "OAR-R1", "PO-R1")
    for bad, code in ((0, 400), (-5, 400)):
        with pytest.raises(HTTPException) as e:
            POMasterService.price_order_without_po_line(env.db, str(o.id), bad, current_user=env.admin)
        assert e.value.status_code == code
    with pytest.raises(HTTPException) as e:
        POMasterService.price_order_without_po_line(env.db, "00000000-0000-0000-0000-000000000000", 5, current_user=env.admin)
    assert e.value.status_code == 404
    rejected = _bare_order(env, "OAR-R2", "PO-R2", status=OrderStatus.REJECT)
    with pytest.raises(HTTPException) as e:
        POMasterService.price_order_without_po_line(env.db, str(rejected.id), 5, current_user=env.admin)
    assert e.value.status_code == 400
    p, a, b = _po_with_lines(env, "PO-R3")
    linked = _bare_order(env, "OAR-R3", "PO-R3")
    linked.po_line_id = a.id
    env.db.commit()
    with pytest.raises(HTTPException) as e:                                          # already has a PO line: edit that instead
        POMasterService.price_order_without_po_line(env.db, str(linked.id), 5, current_user=env.admin)
    assert e.value.status_code == 400
    p4, a4, b4 = _po_with_lines(env, "PO-R4")
    p4.status = POStatus.CANCELLED
    env.db.commit()
    other = __import__("app.models.order", fromlist=["Part"]).Part(part_number="P-3", description="x")
    env.db.add(other)
    env.db.commit()
    cancelled = _bare_order(env, "OAR-R4", "PO-R4", part=other)
    with pytest.raises(HTTPException) as e:
        POMasterService.price_order_without_po_line(env.db, str(cancelled.id), 5, current_user=env.admin)
    assert e.value.status_code == 400
    assert env.db.query(POMaster).filter(POMaster.po_number == "PO-R1").count() == 0   # refusals created nothing


def test_order_price_endpoint_access(client):
    path = "/api/v1/masters/orders/00000000-0000-0000-0000-000000000000/price"
    assert client.put(path, json={"unit_price": 10}).status_code == 401
    for role in (UserRole.OPERATOR, UserRole.STORE, UserRole.ACCOUNTS, UserRole.F1_SUPERVISOR, UserRole.SCM):
        assert client.put(path, json={"unit_price": 10}, headers=_auth(_user(client, role))).status_code == 403, role
    assert client.put(path, json={"unit_price": 10}, headers=_auth(_user(client, UserRole.SALES))).status_code == 404
