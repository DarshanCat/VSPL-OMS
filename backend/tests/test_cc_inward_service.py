"""Continuous Casting inward/GRN service. Isolated in-memory SQLite only (own engine; the
app's configured database is never opened). SQLite does not enforce FKs by default."""
import re
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import *  # noqa: F401,F403  (registers every table)
from app.models import continuous_casting as cc
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.schemas.continuous_casting import CCInwardCreate
import app.services.continuous_casting_service as svc
from app.services.continuous_casting_service import ContinuousCastingInwardService as Svc

CC_TABLES = ["cc_materials", "cc_inwards", "cc_stock_units", "cc_routings", "cc_allocations",
             "cc_stock_ledger", "cc_cut_records"]
OMS_TABLES = ["orders", "work_orders", "wo_routes", "stage_wips", "production_movements",
              "production_updates", "nc_records", "conversions", "packing_records", "dispatches",
              "rejection_dispositions"]


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert engine.url.database == ":memory:"
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _user(db, role, name):
    u = User(full_name=name, email=f"{name.replace(' ', '.').lower()}@example.test",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


@pytest.fixture()
def store(db):
    return _user(db, UserRole.STORE, "Store Keeper")


@pytest.fixture()
def mat(db):
    m = cc.ContinuousCastingMaterial(material_code="M1", grade="SG450", section="ROUND", stock_dimension_a_mm=200)
    db.add(m)
    db.commit()
    return m


def count(db, table):
    return db.execute(select(func.count()).select_from(Base.metadata.tables[table])).scalar()


def snapshot(db):
    return {t: count(db, t) for t in CC_TABLES + OMS_TABLES + ["audit_logs"]}


def req(mat, lengths, **kw):
    return CCInwardCreate(material_id=mat.id, unit_lengths_mm=lengths, **kw)


def raw_req(mat, lengths, **kw):
    """Bypasses schema validation, to exercise the service's own checks."""
    return CCInwardCreate.model_construct(material_id=mat.id, unit_lengths_mm=lengths, **kw)


# ------------------------------------------------------------------ happy paths
def test_single_bar_inward(db, store, mat):
    r = Svc.create_inward(db, req(mat, [1000]), store)
    assert r.inward_number == "INW-000001"
    assert r.received_piece_count == 1 and r.received_total_length_mm == 1000
    assert [u.unit_number for u in r.units] == ["UNIT-000001"]
    assert r.units[0].ledger_transaction_number == "TXN-000001"
    assert r.reconciled is True


def test_multi_bar_inward_17_by_1000(db, store, mat):
    r = Svc.create_inward(db, req(mat, [1000] * 17), store)
    assert r.received_piece_count == 17            # physical quantity
    assert r.received_total_length_mm == 17000     # length -- never fractional pieces
    assert count(db, "cc_stock_units") == 17
    assert count(db, "cc_stock_ledger") == 17
    assert [u.unit_number for u in r.units] == [f"UNIT-{i:06d}" for i in range(1, 18)]
    assert [u.ledger_transaction_number for u in r.units] == [f"TXN-{i:06d}" for i in range(1, 18)]


def test_bars_of_different_lengths(db, store, mat):
    r = Svc.create_inward(db, req(mat, [1000, 1500, 999]), store)
    assert r.received_total_length_mm == 3499
    assert sorted(u.original_length_mm for u in r.units) == [999, 1000, 1500]
    assert r.units_original_length_mm == r.units_remaining_length_mm == r.ledger_inward_length_mm == 3499


def test_stored_rows(db, store, mat):
    r = Svc.create_inward(db, req(mat, [1000, 800], grn_reference="  GRN-77  ", location="Bay 3",
                                  remarks="first lot"), store)
    inward = db.query(cc.ContinuousCastingInward).one()
    assert inward.inward_number == r.inward_number and str(inward.id) == r.inward_id
    assert (inward.grade, inward.section, inward.stock_dimension_a_mm) == ("SG450", "ROUND", 200)
    assert inward.stock_dimension_b_mm is None
    assert inward.received_piece_count == 2 and inward.received_total_length_mm == 1800
    assert inward.grn_reference == "GRN-77" and inward.location == "Bay 3"
    assert inward.qa_status == "PENDING_QA" and inward.created_by == "Store Keeper"
    units = db.query(cc.ContinuousCastingStockUnit).order_by(cc.ContinuousCastingStockUnit.unit_number).all()
    for u, length in zip(units, [1000, 800]):
        assert u.inward_id == inward.id and u.parent_unit_id is None
        assert u.original_length_mm == u.remaining_length_mm == length
        assert (u.reserved_length_mm, u.issued_length_mm, u.consumed_length_mm) == (0, 0, 0)
        assert u.status == "IN_STOCK" and u.location == "Bay 3"
    rows = db.query(cc.ContinuousCastingStockLedger).order_by(cc.ContinuousCastingStockLedger.transaction_number).all()
    assert len(rows) == 2
    for row, u in zip(rows, units):
        assert row.movement_type == "INWARD" and row.piece_qty == 1
        assert row.stock_unit_id == u.id and row.inward_id == inward.id
        assert row.length_mm == u.original_length_mm == row.unit_remaining_after_mm
        assert row.reference == "GRN-77" and row.allocation_id is None
        assert row.performed_by_id == store.id and row.performed_by_name == "Store Keeper"
    audit = db.query(AuditLog).filter(AuditLog.action == "CC_INWARD").one()
    assert audit.entity_id == r.inward_number and audit.user_id == store.id


def test_ledger_reconciles_to_cached_balances_per_unit(db, store, mat):
    Svc.create_inward(db, req(mat, [1000, 1500, 700]), store)
    for u in db.query(cc.ContinuousCastingStockUnit).all():
        ledger_total = db.query(func.sum(cc.ContinuousCastingStockLedger.length_mm)).filter(
            cc.ContinuousCastingStockLedger.stock_unit_id == u.id,
            cc.ContinuousCastingStockLedger.movement_type == "INWARD").scalar()
        assert ledger_total == u.original_length_mm == u.remaining_length_mm
    # header, units and ledger agree in total as well
    inward = db.query(cc.ContinuousCastingInward).one()
    assert inward.received_total_length_mm == db.query(
        func.sum(cc.ContinuousCastingStockUnit.remaining_length_mm)).scalar() == 3200
    assert inward.received_piece_count == db.query(cc.ContinuousCastingStockUnit).count() == 3


def test_inward_creates_no_order_or_work_order_and_touches_no_oms_table(db, store, mat):
    before = snapshot(db)
    Svc.create_inward(db, req(mat, [1000] * 3), store)
    after = snapshot(db)
    changed = {t for t in before if before[t] != after[t]}
    assert changed == {"cc_inwards", "cc_stock_units", "cc_stock_ledger", "audit_logs"}
    assert after["orders"] == after["work_orders"] == after["wo_routes"] == after["stage_wips"] == 0


def test_second_inward_continues_numbering(db, store, mat):
    Svc.create_inward(db, req(mat, [1000] * 17), store)
    r2 = Svc.create_inward(db, req(mat, [500, 500]), store)
    assert r2.inward_number == "INW-000002"
    assert [u.unit_number for u in r2.units] == ["UNIT-000018", "UNIT-000019"]
    assert [u.ledger_transaction_number for u in r2.units] == ["TXN-000018", "TXN-000019"]


def test_declared_figures_that_match_are_accepted(db, store, mat):
    r = Svc.create_inward(db, req(mat, [1000, 1000], received_piece_count=2,
                                  received_total_length_mm=2000, stock_dimension_a_mm=200), store)
    assert r.received_piece_count == 2 and r.reconciled is True


def test_blank_grn_and_location_become_null(db, store, mat):
    Svc.create_inward(db, req(mat, [1000], grn_reference="   ", location=" "), store)
    inward = db.query(cc.ContinuousCastingInward).one()
    assert inward.grn_reference is None and inward.location is None


# ------------------------------------------------------------------ roles
@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.STORE])
def test_authorized_roles_can_inward(db, mat, role):
    assert Svc.create_inward(db, req(mat, [1000]), _user(db, role, role.value)).success


@pytest.mark.parametrize("role", [UserRole.PLANNER, UserRole.QA, UserRole.PRODUCTION_MANAGER,
                                  UserRole.DISPATCH, UserRole.CEO, UserRole.ENGINEERING,
                                  UserRole.MACHINE_OPERATOR, UserRole.DATA_ANALYST])
def test_unauthorized_roles_are_rejected_with_403(db, mat, role):
    user = _user(db, role, role.value)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1000]), user)
    assert e.value.status_code == 403
    assert snapshot(db) == before


def test_anonymous_is_rejected_with_403(db, mat):
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1000]), None)
    assert e.value.status_code == 403 and snapshot(db) == before


# ------------------------------------------------------------------ validation
@pytest.mark.parametrize("kwargs", [
    dict(unit_lengths_mm=[0]), dict(unit_lengths_mm=[-5]), dict(unit_lengths_mm=[]),
    dict(unit_lengths_mm=[1000, 0]), dict(unit_lengths_mm=[1000.5]),
    dict(unit_lengths_mm=[1000], received_piece_count=0),
    dict(unit_lengths_mm=[1000], received_piece_count=-1),
    dict(unit_lengths_mm=[1000], received_total_length_mm=0),
    dict(unit_lengths_mm=[1000], stock_dimension_a_mm=0),
    dict(unit_lengths_mm=[1000], stock_dimension_b_mm=-1),
    dict(unit_lengths_mm=[2_147_483_648]),            # beyond the 32-bit column, not a business cap
])
def test_schema_rejects_bad_numbers(mat, kwargs):
    with pytest.raises(ValidationError):
        CCInwardCreate(material_id=mat.id, **kwargs)


@pytest.mark.parametrize("lengths", [[0], [-5], [], [1000, 0], [True]])
def test_service_rejects_zero_negative_or_missing_bars(db, store, mat, lengths):
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, raw_req(mat, lengths), store)
    assert e.value.status_code == 400 and snapshot(db) == before


def test_service_rejects_total_beyond_32_bit(db, store, mat):
    """Each bar fits the column, but the posted total would not."""
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1_000_000_000] * 3), store)
    assert e.value.status_code == 400 and count(db, "cc_inwards") == 0


@pytest.mark.parametrize("kw,fragment", [
    (dict(received_piece_count=3), "piece count"),
    (dict(received_total_length_mm=2500), "total length"),
    (dict(stock_dimension_a_mm=250), "dimension A"),
    (dict(stock_dimension_a_mm=0), "stock_dimension_a_mm"),
    (dict(stock_dimension_b_mm=50), "dimension B"),
    (dict(stock_dimension_b_mm=-1), "stock_dimension_b_mm"),
])
def test_service_rejects_inconsistent_or_invalid_fields(db, store, mat, kw, fragment):
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, raw_req(mat, [1000, 1000], **kw), store)
    assert e.value.status_code == 400 and fragment in e.value.detail
    assert snapshot(db) == before


def test_unknown_material_is_404(db, store, mat):
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, CCInwardCreate(material_id=uuid.uuid4(), unit_lengths_mm=[1000]), store)
    assert e.value.status_code == 404 and count(db, "cc_inwards") == 0


def test_inactive_material_is_rejected(db, store, mat):
    mat.is_active = False
    db.commit()
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1000]), store)
    assert e.value.status_code == 400 and count(db, "cc_inwards") == 0


def test_failed_requests_do_not_burn_numbers(db, store, mat):
    with pytest.raises(HTTPException):
        Svc.create_inward(db, raw_req(mat, [0]), store)
    assert Svc.create_inward(db, req(mat, [1000]), store).inward_number == "INW-000001"


# ------------------------------------------------------------------ QA vs allocation eligibility
def test_new_inward_is_in_stock_but_not_allocatable_until_qa_accepts(db, store, mat):
    r = Svc.create_inward(db, req(mat, [1000, 1000]), store)
    assert r.qa_status == "PENDING_QA" and r.physical_stock_status == "IN_STOCK"
    assert r.allocation_eligible is False
    assert "ACCEPTED" in r.allocation_ineligible_reason
    # Physically received stock is neither deleted nor hidden just because it is pending QA.
    assert count(db, "cc_stock_units") == 2 and count(db, "cc_stock_ledger") == 2
    units = db.query(cc.ContinuousCastingStockUnit).all()
    assert all(u.status == "IN_STOCK" and u.remaining_length_mm == u.original_length_mm for u in units)
    assert not any(cc.is_allocation_eligible(u) for u in units)
    assert all("PENDING_QA" in cc.allocation_ineligibility_reason(u) for u in units)


def test_unit_status_is_never_the_string_available(db, store, mat):
    """'AVAILABLE' read as 'allocatable' was the ambiguity; physical status is IN_STOCK."""
    Svc.create_inward(db, req(mat, [1000]), store)
    assert "AVAILABLE" not in cc.STOCK_UNIT_STATUSES
    assert db.query(cc.ContinuousCastingStockUnit).one().status == "IN_STOCK"


def test_unit_becomes_eligible_once_the_existing_qa_process_accepts_the_inward(db, store, mat):
    Svc.create_inward(db, req(mat, [1000]), store)
    db.query(cc.ContinuousCastingInward).one().qa_status = "ACCEPTED"   # existing quality process
    db.commit()
    unit = db.query(cc.ContinuousCastingStockUnit).one()
    assert cc.allocation_ineligibility_reason(unit) is None and cc.is_allocation_eligible(unit)


@pytest.mark.parametrize("qa", ["PENDING_QA", "REJECTED", "ON_HOLD"])
def test_only_accepted_qa_status_is_allocatable(db, store, mat, qa):
    Svc.create_inward(db, req(mat, [1000]), store)
    db.query(cc.ContinuousCastingInward).one().qa_status = qa
    db.commit()
    unit = db.query(cc.ContinuousCastingStockUnit).one()
    assert not cc.is_allocation_eligible(unit) and qa in cc.allocation_ineligibility_reason(unit)


@pytest.mark.parametrize("qa,expect_block", [("ACCEPTED", False), ("PENDING_QA", True), ("REJECTED", True),
                                             ("ON_HOLD", True), ("", True), (None, True), ("accepted", True)])
def test_qa_block_reason_helper(qa, expect_block):
    assert (cc.qa_allocation_block_reason(qa) is not None) is expect_block


@pytest.mark.parametrize("change,fragment", [
    (dict(status="ON_HOLD"), "ON_HOLD"),
    (dict(status="SCRAPPED"), "SCRAPPED"),
    (dict(reserved_length_mm=1000), "no free length"),
    (dict(issued_length_mm=1000), "no free length"),
    (dict(remaining_length_mm=0), "no free length"),
])
def test_accepted_stock_is_still_ineligible_when_the_unit_itself_cannot_be_allocated(db, store, mat, change, fragment):
    Svc.create_inward(db, req(mat, [1000]), store)
    db.query(cc.ContinuousCastingInward).one().qa_status = "ACCEPTED"
    unit = db.query(cc.ContinuousCastingStockUnit).one()
    for k, v in change.items():
        setattr(unit, k, v)
    db.commit()
    assert fragment in cc.allocation_ineligibility_reason(unit)


def test_free_length_is_what_counts_not_remaining_alone(db, store, mat):
    Svc.create_inward(db, req(mat, [1000]), store)
    db.query(cc.ContinuousCastingInward).one().qa_status = "ACCEPTED"
    unit = db.query(cc.ContinuousCastingStockUnit).one()
    unit.reserved_length_mm, unit.issued_length_mm = 600, 300     # 100 mm still free
    db.commit()
    assert cc.is_allocation_eligible(unit)


def test_posting_an_inward_cannot_self_certify_qa(db, store, mat):
    with pytest.raises(ValidationError):                         # unknown field is refused, not ignored
        CCInwardCreate(material_id=mat.id, unit_lengths_mm=[1000], qa_status="ACCEPTED")
    assert "qa_status" not in CCInwardCreate.model_fields
    assert count(db, "cc_inwards") == 0


@pytest.mark.parametrize("role", [UserRole.STORE, UserRole.ADMIN])
def test_every_inward_header_starts_pending_qa_whoever_posts_it(db, mat, role):
    Svc.create_inward(db, req(mat, [1000]), _user(db, role, role.value))
    assert db.query(cc.ContinuousCastingInward).one().qa_status == "PENDING_QA"


# ------------------------------------------------------------------ no invented business caps
def test_no_per_bar_length_cap(db, store, mat):
    r = Svc.create_inward(db, req(mat, [5_000_000, 12_345_678]), store)
    assert r.received_total_length_mm == 17_345_678 and r.reconciled is True


def test_a_single_bar_may_use_the_whole_32_bit_range(db, store, mat):
    r = Svc.create_inward(db, req(mat, [2_147_483_647]), store)
    assert r.received_total_length_mm == 2_147_483_647


def test_no_bars_per_inward_cap(db, store, mat):
    n = 10_001
    r = Svc.create_inward(db, req(mat, [1000] * n), store)
    assert r.received_piece_count == n and r.reconciled is True
    assert count(db, "cc_stock_units") == n and count(db, "cc_stock_ledger") == n
    assert r.units[-1].unit_number == "UNIT-010001"


# ------------------------------------------------------------------ numbers / collisions
def _flaky(monkeypatch, name, first_values):
    """Make a generator return `first_values` on its first calls, then behave normally."""
    real = getattr(svc, name)
    calls = []

    def fake(db, *a):
        calls.append(1)
        if len(calls) <= len(first_values):
            return first_values[len(calls) - 1]
        return real(db, *a)

    monkeypatch.setattr(svc, name, fake)
    return calls


@pytest.mark.parametrize("name,first", [
    ("next_cc_inward_number", "INW-000001"),
    ("next_cc_unit_numbers", ["UNIT-000001"]),
    ("next_cc_ledger_transaction_numbers", ["TXN-000001"]),
])
def test_number_collision_is_retried_and_recovers(db, store, mat, monkeypatch, name, first):
    Svc.create_inward(db, req(mat, [1000]), store)            # takes INW/UNIT/TXN -000001
    calls = _flaky(monkeypatch, name, [first])
    r = Svc.create_inward(db, req(mat, [700]), store)
    assert len(calls) == 2                                    # collided once, then succeeded
    assert r.inward_number == "INW-000002" and r.units[0].unit_number == "UNIT-000002"
    assert count(db, "cc_inwards") == 2 and count(db, "cc_stock_units") == 2
    assert count(db, "cc_stock_ledger") == 2                  # no half-posted leftovers


@pytest.mark.parametrize("name,first", [
    ("next_cc_inward_number", "INW-000001"),
    ("next_cc_unit_numbers", ["UNIT-000001"]),
    ("next_cc_ledger_transaction_numbers", ["TXN-000001"]),
])
def test_persistent_collision_ends_in_409_with_nothing_posted(db, store, mat, monkeypatch, name, first):
    Svc.create_inward(db, req(mat, [1000]), store)
    before = snapshot(db)
    calls = _flaky(monkeypatch, name, [first] * 10)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [700]), store)
    assert e.value.status_code == 409
    assert len(calls) == svc.CC_NUMBER_MAX_ATTEMPTS           # bounded, not infinite
    assert snapshot(db) == before


def test_no_client_request_id_is_needed_anywhere_on_the_collision_path(db, store, mat, monkeypatch):
    """The inward has no idempotency key, so the known `.strip()`-on-None bug cannot occur."""
    assert "client_request_id" not in CCInwardCreate.model_fields
    Svc.create_inward(db, req(mat, [1000]), store)
    _flaky(monkeypatch, "next_cc_inward_number", ["INW-000001"] * 10)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1000]), store)
    assert e.value.status_code == 409                          # controlled, never AttributeError


def test_non_unique_integrity_error_is_not_retried(db, store, mat, monkeypatch):
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise IntegrityError("stmt", {}, Exception("CHECK constraint failed: ck_cc_unit_original_positive"))

    monkeypatch.setattr(svc, "_post_inward", boom)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1000]), store)
    assert e.value.status_code == 400 and len(calls) == 1


# ------------------------------------------------------------------ atomicity
def test_rollback_when_a_later_ledger_insert_fails(db, store, mat, monkeypatch):
    """Duplicate ledger numbers inside one batch: the inward and unit rows are already
    staged/flushed when the ledger insert fails -- everything must roll back."""
    before = snapshot(db)
    _flaky(monkeypatch, "next_cc_ledger_transaction_numbers", [["TXN-000001", "TXN-000001"]] * 10)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1000, 1000]), store)
    assert e.value.status_code == 409
    assert snapshot(db) == before
    monkeypatch.undo()                       # fault injection off: the same request now succeeds
    assert Svc.create_inward(db, req(mat, [1000, 1000]), store).inward_number == "INW-000001"


def test_rollback_when_a_unit_insert_fails(db, store, mat, monkeypatch):
    before = snapshot(db)
    _flaky(monkeypatch, "next_cc_unit_numbers", [["UNIT-000001", "UNIT-000001"]] * 10)
    with pytest.raises(HTTPException) as e:
        Svc.create_inward(db, req(mat, [1000, 1000]), store)
    assert e.value.status_code == 409 and snapshot(db) == before


def test_rollback_after_everything_is_flushed(db, store, mat, monkeypatch):
    """Fail after inward+units+ledger+audit are all flushed into the open transaction."""
    before = snapshot(db)

    def explode(*a, **k):
        raise RuntimeError("late failure")

    monkeypatch.setattr(svc, "CCInwardResult", explode)
    with pytest.raises(RuntimeError):
        Svc.create_inward(db, req(mat, [1000, 1000, 1000]), store)
    assert snapshot(db) == before


def test_rollback_when_failure_happens_while_staging(db, store, mat, monkeypatch):
    before = snapshot(db)

    def explode(*a, **k):
        raise RuntimeError("staging failure")

    monkeypatch.setattr(svc, "AuditLog", explode)
    with pytest.raises(RuntimeError):
        Svc.create_inward(db, req(mat, [1000, 1000]), store)
    assert snapshot(db) == before


def test_reconciliation_failure_rolls_everything_back(db, store, mat):
    """If the INWARD ledger ever disagrees with the units it explains, nothing is posted."""
    before = snapshot(db)

    def skew_ledger_length(mapper, connection, target):
        target.length_mm = target.length_mm + 1

    event.listen(cc.ContinuousCastingStockLedger, "before_insert", skew_ledger_length)
    try:
        with pytest.raises(HTTPException) as e:
            Svc.create_inward(db, req(mat, [1000, 1000]), store)
    finally:
        event.remove(cc.ContinuousCastingStockLedger, "before_insert", skew_ledger_length)
    assert e.value.status_code == 500 and "reconciliation" in e.value.detail
    assert snapshot(db) == before
    assert Svc.create_inward(db, req(mat, [1000, 1000]), store).reconciled is True


# ------------------------------------------------------------------ batch generator + scope
def test_ledger_batch_numbers(db):
    assert cc.next_cc_ledger_transaction_numbers(db, 3) == ["TXN-000001", "TXN-000002", "TXN-000003"]
    assert cc.next_cc_ledger_transaction_numbers(db, 0) == []
    with pytest.raises(ValueError):
        cc.next_cc_ledger_transaction_numbers(db, -1)


def test_service_imports_no_oms_production_or_work_order_code():
    src = Path(svc.__file__).read_text(encoding="utf-8")
    imported = " ".join(re.findall(r"^\s*(?:from|import)\s+(\S+)", src, flags=re.M))
    for forbidden in ("production_service", "work_order_service", "oms_integration_service",
                      "operations_service", "rejection_service", "oms_engine", "app.models.work_order",
                      "app.models.production", "app.models.order"):
        assert forbidden not in imported, forbidden
