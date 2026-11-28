"""PO Master dashboard: how many pieces have an OAR (done) and how many do not (not done)."""
import io
from datetime import date

from openpyxl import load_workbook

from tests.test_setup_planning import env  # noqa: F401
from tests.test_sales_order_status import _order, _po
from app.models.master_data import ScheduleMaster, ScheduleStatus
from app.models.order import OrderStatus
from app.services import sales_report_service as svc

TODAY = date(2026, 11, 26)


def _sched(env, number, qty, price=10.0, status=ScheduleStatus.AWAITING_PO, due=date(2026, 12, 20)):
    s = ScheduleMaster(schedule_number=number, customer_id=env.cust.id, part_id=env.part.id, scheduled_qty=qty,
                       unit_price=price, total_value=qty * price, required_date=due, po_status=status)
    env.db.add(s)
    env.db.commit()
    return s


def test_orders_report_splits_pending_pieces_by_oar(env):
    _po(env, "PO-A", 100, 50.0, date(2026, 12, 5))
    o = _order(env, "PO-A", 60, date(2026, 12, 10))                       # 60 of the 100 pieces are in an OAR
    _po(env, "PO-B", 40, 20.0, date(2026, 12, 7))                         # no OAR at all for this line
    _sched(env, "SCH-1", 25, price=4.0)                                    # a schedule with no OAR and no PO
    rep = svc.build_report(env.db, today=TODAY)
    oar = rep["oar"]
    assert oar["done"] == {"count": 1, "qty": 60, "value": 3000.0}
    assert oar["not_done"]["qty"] == 40 + 40 + 25 and oar["not_done"]["count"] == 3
    assert oar["not_done_split"]["PO_LINE"]["qty"] == 80 and oar["not_done_split"]["SCHEDULE"] == {"count": 1, "qty": 25, "value": 100.0}
    assert oar["done"]["qty"] + oar["not_done"]["qty"] == rep["total"]["qty"]                 # nothing counted twice or lost
    assert oar["done"]["value"] + oar["not_done"]["value"] == rep["total"]["value"]
    by = {(i["source"], i["ref"]): i for i in rep["items"]}
    assert by[("OAR", o.oar_number)]["oar_status"] == "Done"
    assert by[("PO_LINE", "PO-A")]["oar_status"] == "Partly (60 of 100 pcs)"
    assert by[("PO_LINE", "PO-B")]["oar_status"] == "Not done"
    assert by[("SCHEDULE", "SCH-1")]["oar_status"] == "Not done"
    assert rep["by_source"]["OAR"]["qty"] == 60                                                 # per-source pieces


def test_source_filter_changes_the_split_with_it(env):
    _po(env, "PO-A", 100, 50.0, date(2026, 12, 5))
    _order(env, "PO-A", 60, date(2026, 12, 10))
    rep = svc.build_report(env.db, include=["OAR"], today=TODAY)
    assert rep["oar"]["done"]["qty"] == 60 and rep["oar"]["not_done"]["qty"] == 0


def test_schedule_report_shows_oar_done_and_not_done(env):
    s1 = _sched(env, "SCH-1", 50, price=10.0)
    _sched(env, "SCH-2", 10, price=10.0)
    _sched(env, "SCH-3", 30, price=10.0, status=ScheduleStatus.MATCHED)                       # not an open schedule
    o = _order(env, "PO-S", 20, date(2026, 12, 10))
    o.schedule_id = s1.id
    rej = _order(env, "PO-S2", 15, date(2026, 12, 10), status=OrderStatus.REJECT, ref="OAR-REJ")
    rej.schedule_id = s1.id                                                                    # a rejected order is not an OAR
    env.db.commit()
    rep = svc.build_schedule_report(env.db, today=TODAY)
    by = {i["schedule"]: i for i in rep["items"]}
    assert (by["SCH-1"]["oar_qty"], by["SCH-1"]["not_oar_qty"]) == (20, 30)
    assert (by["SCH-2"]["oar_qty"], by["SCH-2"]["not_oar_qty"]) == (0, 10)
    assert "SCH-3" not in by
    assert rep["oar"]["done"] == {"count": 1, "qty": 20, "value": 200.0}
    assert rep["oar"]["not_done"] == {"count": 2, "qty": 40, "value": 400.0}
    assert rep["oar"]["done"]["qty"] + rep["oar"]["not_done"]["qty"] == rep["total"]["qty"]
    assert rep["total"]["count"] == 2 and rep["total"]["value"] == 600.0                     # the existing totals are unchanged


def test_excel_downloads_carry_the_oar_columns(env):
    _po(env, "PO-A", 100, 50.0, date(2026, 12, 5))
    _order(env, "PO-A", 60, date(2026, 12, 10))
    _sched(env, "SCH-1", 25)
    for blob, heads in ((svc.export_report(env.db, today=TODAY), ["OAR"]),
                        (svc.export_schedule_report(env.db, today=TODAY), ["OAR Done Qty", "Not OAR'd Qty"])):
        wb = load_workbook(io.BytesIO(blob))
        detail = wb.worksheets[-1]
        header = [c.value for c in detail[1]]
        for h in heads:
            assert h in header, (h, header)
