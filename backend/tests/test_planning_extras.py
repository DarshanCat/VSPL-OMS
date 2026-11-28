"""Working calendar, gate capacity and split work orders (planning information only)."""
from datetime import timedelta

from tests.test_setup_planning import (  # noqa: F401
    T, d, env, full_plan, mksetup, mkwo, refused, _setup_with_two, SP, excel, WorkOrder,
)
from app.core.config import settings
from app.services import planning_extras_service as ex


def _next_weekday(wd, after=20):
    x = d(after)
    while x.weekday() != wd:
        x += timedelta(days=1)
    return x


# ---------------------------------------------------------------- calendar
def test_calendar_exceptions_and_weekly_off(env):
    env.mp.setattr(settings, "PLANNING_WEEKLY_OFF", "6")
    sun = _next_weekday(6)
    cal = ex.calendar_map(env.db, sun, sun)
    assert "weekly off" in ex.non_working_reason(sun, cal)
    ex.set_calendar_day(env.db, sun, "WORKING", "extra shift", env.ppc)
    env.db.commit()
    assert ex.non_working_reason(sun, ex.calendar_map(env.db, sun, sun)) is None
    mon = _next_weekday(0)
    ex.set_calendar_day(env.db, mon, "HOLIDAY", "Diwali", env.ppc)
    env.db.commit()
    assert ex.non_working_reason(mon, ex.calendar_map(env.db, mon, mon)) == "a holiday"
    assert ex.next_working_day(env.db, mon) == mon + timedelta(days=1)
    ex.delete_calendar_day(env.db, mon, env.ppc)
    env.db.commit()
    assert ex.non_working_reason(mon, ex.calendar_map(env.db, mon, mon)) is None
    with refused(400):
        ex.set_calendar_day(env.db, mon, "BOGUS", None, env.ppc)


def test_plan_edit_warns_on_holiday_but_still_saves(env):
    env.mp.setattr(settings, "PLANNING_WEEKLY_OFF", "6")
    s, a, b = _setup_with_two(env)
    sun = _next_weekday(6)
    res = SP.update_plan(env.db, "WO-B", [{"stage": "SP", "planned_end": sun}], None, "test", 0, env.ppc)
    # Calendar warnings were removed: a date on a weekly-off day saves without a holiday warning.
    assert not any("weekly off" in w["message"] for w in res["warnings"])
    assert "SP" in res["changed_gates"]


# ---------------------------------------------------------------- capacity
def test_capacity_warning_counts_other_work_orders_only(env):
    s, a, b = _setup_with_two(env)           # both 10 pcs
    day = _next_weekday(1)
    SP.update_plan(env.db, "WO-B", [{"stage": "FI", "planned_end": day}], None, "reason x", 0, env.ppc)
    env.db.commit()
    ex.set_capacity(env.db, "FI", 15, None, env.ppc)
    env.db.commit()
    res = SP.update_plan(env.db, "WO-A", [{"stage": "FI", "planned_end": day}], None, "reason y", 0, env.ppc)
    # Capacity warnings were removed: going over a stored capacity no longer warns.
    assert not any("capacity" in w["message"] for w in res["warnings"])
    res2 = SP.update_plan(env.db, "WO-B", [{"stage": "FI", "planned_end": day + timedelta(days=1)}], None, "reason z", 1, env.ppc)
    assert not any("capacity" in w["message"] for w in res2["warnings"])


def test_capacity_view_marks_over_and_non_working(env):
    env.mp.setattr(settings, "PLANNING_WEEKLY_OFF", "6")
    s, a, b = _setup_with_two(env)
    day = _next_weekday(1)
    for wo in ("WO-A", "WO-B"):
        SP.update_plan(env.db, wo, [{"stage": "FI", "planned_end": day}], None, "reason x", None, env.ppc)
    env.db.commit()
    ex.set_capacity(env.db, "FI", 15, None, env.ppc)
    env.db.commit()
    view = ex.capacity_view(env.db, T, 40)
    fi = next(r for r in view["stages"] if r["stage"] == "FI")
    cell = next(c for c in fi["cells"] if c["day"] == day.isoformat())
    assert cell["load"] == 20 and cell["over"] is True
    assert any(x["non_working"] for x in view["days"])
    with refused(400):
        ex.set_capacity(env.db, "FI", 0, None, env.ppc)


# ---------------------------------------------------------------- split
def test_split_shares_show_in_both_setups_and_stay_out_of_the_sheet(env):
    s1, a, b = _setup_with_two(env)
    mksetup(env, "S-Y", d(1))
    out = ex.set_splits(env.db, "WO-A", [{"setup_number": "S-Y", "qty": 4}], "second furnace day", env.ppc)
    env.db.commit()
    assert out["primary_qty"] == 6 and out["splits"][0]["qty"] == 4
    x = {r["wo_number"]: r for r in SP.setup_detail(env.db, "S-X")["work_orders"]}
    y = {r["wo_number"]: r for r in SP.setup_detail(env.db, "S-Y")["work_orders"]}
    assert x["WO-A"]["qty"] == 6 and not x["WO-A"]["is_split"]
    assert y["WO-A"]["qty"] == 4 and y["WO-A"]["is_split"] and y["WO-A"]["primary_setup"] == "S-X"
    # Excel: the split row is not in S-Y's sheet, the primary one is in S-X's
    import io
    from openpyxl import load_workbook
    sx = load_workbook(io.BytesIO(excel.export_setup(env.db, "S-X", env.ppc)[0]))["PLAN"]
    assert "WO-A" in [c.value for c in sx["B"]]
    all_sheet = load_workbook(io.BytesIO(excel.export_setups(env.db, "OPEN", env.ppc)[0]))["PLAN"]
    assert [c.value for c in all_sheet["B"]].count("WO-A") == 1
    # real quantities untouched
    assert env.db.query(WorkOrder).filter(WorkOrder.wo_number == "WO-A").one().physical_wo_qty == 10


def test_split_rules(env):
    s1, a, b = _setup_with_two(env)
    s2 = mksetup(env, "S-Y", d(1))
    with refused(400, "at least 1"):
        ex.set_splits(env.db, "WO-A", [{"setup_number": "S-Y", "qty": 10}], "all", env.ppc)
    with refused(400, "already the main"):
        ex.set_splits(env.db, "WO-A", [{"setup_number": "S-X", "qty": 2}], "same", env.ppc)
    with refused(400, "reason"):
        ex.set_splits(env.db, "WO-A", [{"setup_number": "S-Y", "qty": 2}], "", env.ppc)
    ex.set_splits(env.db, "WO-A", [{"setup_number": "S-Y", "qty": 3}], "okay fine", env.ppc)
    env.db.commit()
    with refused(400, "Remove the split"):
        SP.move_work_order(env.db, "WO-A", "S-Y", "swap", env.ppc)
    s2.status = "CLOSED"
    env.db.commit()
    with refused(409):
        ex.set_splits(env.db, "WO-B", [{"setup_number": "S-Y", "qty": 2}], "closed", env.ppc)
