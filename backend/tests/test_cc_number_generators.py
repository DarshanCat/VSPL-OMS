"""Continuous Casting business-number generators (parse-max-and-increment).

Isolated in-memory SQLite only. SQLite does not enforce foreign keys by default, so rows
here use random UUIDs for FK columns; the generators only read the number column.
"""
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import *  # noqa: F401,F403  (registers every table on Base.metadata)
from app.models import continuous_casting as cc


def _u():
    return uuid.uuid4()


def _inward(n):
    return cc.ContinuousCastingInward(
        inward_number=n, material_id=_u(), grade="G", section="S", stock_dimension_a_mm=1,
        received_piece_count=0, received_total_length_mm=0)


def _unit(n):
    return cc.ContinuousCastingStockUnit(
        unit_number=n, inward_id=_u(), original_length_mm=1, remaining_length_mm=1)


def _allocation(n):
    return cc.ContinuousCastingAllocation(allocation_number=n, routing_id=_u(), stock_unit_id=_u())


def _cut(n):
    return cc.ContinuousCastingCutRecord(
        cut_number=n, work_order_id=_u(), allocation_id=_u(), stock_unit_id=_u(), blank_length_mm=1)


def _ledger(n):
    return cc.ContinuousCastingStockLedger(
        transaction_number=n, movement_type="INWARD", inward_id=_u(), stock_unit_id=_u())


# (id, generator, row factory, prefix)
KINDS = [
    ("inward", cc.next_cc_inward_number, _inward, "INW"),
    ("unit", cc.next_cc_unit_number, _unit, "UNIT"),
    ("allocation", cc.next_cc_allocation_number, _allocation, "ALC"),
    ("cut", cc.next_cc_cut_number, _cut, "CUT"),
    ("ledger", cc.next_cc_ledger_transaction_number, _ledger, "TXN"),
]
kinds = pytest.mark.parametrize("gen,make,prefix", [k[1:] for k in KINDS], ids=[k[0] for k in KINDS])


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    assert engine.url.database == ":memory:"
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _seed(db, make, prefix, *suffixes):
    for s in suffixes:
        db.add(make(f"{prefix}-{s}"))
    db.commit()


def test_prefixes_and_width_are_the_declared_constants():
    assert (cc.CC_INWARD_PREFIX, cc.CC_UNIT_PREFIX, cc.CC_ALLOCATION_PREFIX,
            cc.CC_CUT_PREFIX, cc.CC_LEDGER_PREFIX) == ("INW", "UNIT", "ALC", "CUT", "TXN")
    assert cc.CC_NUMBER_WIDTH == 6


@kinds
def test_empty_table_gives_first_number(db, gen, make, prefix):
    assert gen(db) == f"{prefix}-000001"


@kinds
def test_sequential_numbers(db, gen, make, prefix):
    for expected in (1, 2, 3):
        n = gen(db)
        assert n == f"{prefix}-{expected:06d}"
        db.add(make(n))
        db.commit()


@kinds
def test_gaps_are_not_refilled(db, gen, make, prefix):
    _seed(db, make, prefix, "000001", "000002", "000005")
    assert gen(db) == f"{prefix}-000006"


@kinds
def test_highest_suffix_wins_regardless_of_insert_order(db, gen, make, prefix):
    _seed(db, make, prefix, "000010", "000002", "000007")
    assert gen(db) == f"{prefix}-000011"


@kinds
def test_numeric_not_lexicographic_when_width_overflows(db, gen, make, prefix):
    _seed(db, make, prefix, "999999", "1000000")
    assert gen(db) == f"{prefix}-1000001"


@kinds
def test_malformed_identifiers_are_ignored_safely(db, gen, make, prefix):
    for suffix in ["ABC", "12x", "-5", "٣", "000999 ", ""]:
        db.add(make(f"{prefix}-{suffix}"))
    db.add(make(f"{prefix.lower()}-000500"))      # wrong case
    db.add(make(f"OTHER-000700"))                 # wrong prefix
    db.add(make(f"{prefix}-000003"))              # the only valid one
    db.commit()
    assert gen(db) == f"{prefix}-000004"


@kinds
def test_duplicate_generation_is_caught_by_the_unique_constraint(db, gen, make, prefix):
    """Existing convention: no lock, no retry -- two callers can compute the same number,
    and the unique constraint rejects the second insert."""
    first = gen(db)
    second = gen(db)                 # nothing inserted yet, so a concurrent caller sees the same
    assert first == second
    db.add(make(first))
    db.commit()
    db.add(make(second))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert gen(db) == f"{prefix}-000002"   # regenerating after the collision moves on


@kinds
def test_pending_unflushed_rows_are_counted(db, gen, make, prefix):
    db.add(make(f"{prefix}-000001"))   # added, not flushed (sessions use autoflush=False)
    assert gen(db) == f"{prefix}-000002"


def test_each_kind_is_independent(db):
    for _, _, make, prefix in KINDS:
        n = {"INW": 4, "UNIT": 1, "ALC": 7, "CUT": 2, "TXN": 9}[prefix]
        for i in range(1, n + 1):
            db.add(make(f"{prefix}-{i:06d}"))
    db.commit()
    assert cc.next_cc_inward_number(db) == "INW-000005"
    assert cc.next_cc_unit_number(db) == "UNIT-000002"
    assert cc.next_cc_allocation_number(db) == "ALC-000008"
    assert cc.next_cc_cut_number(db) == "CUT-000003"
    assert cc.next_cc_ledger_transaction_number(db) == "TXN-000010"


def test_unit_numbers_batch(db):
    assert cc.next_cc_unit_numbers(db, 3) == ["UNIT-000001", "UNIT-000002", "UNIT-000003"]
    assert cc.next_cc_unit_numbers(db, 0) == []
    _seed(db, _unit, "UNIT", "000005")
    assert cc.next_cc_unit_numbers(db, 2) == ["UNIT-000006", "UNIT-000007"]
    with pytest.raises(ValueError):
        cc.next_cc_unit_numbers(db, -1)


def test_batch_numbers_can_be_added_in_one_unflushed_transaction(db):
    for n in cc.next_cc_unit_numbers(db, 4):
        db.add(_unit(n))
    db.commit()
    assert db.query(cc.ContinuousCastingStockUnit).count() == 4
    assert cc.next_cc_unit_number(db) == "UNIT-000005"
