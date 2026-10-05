"""Regression tests for Customer Part Number -> internal Part resolution
(app/services/master_data_service.py: resolve_customer_part, next_internal_part_number
in app/models/order.py, and CustomerPartMapping).

Runs against a throwaway temp-file SQLite database (never the shared local dev
database the HTTP-level PO tests use, and never production) so the concurrency
tests below can freely manipulate transaction timing without any risk to real data.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import Base
from app.models.order import Customer, Part, next_internal_part_number
from app.models.customer_part_mapping import CustomerPartMapping
from app.services.master_data_service import (
    resolve_customer_part, resolve_customer_part_preview, list_customer_parts,
    POMasterService,
)
from app.schemas.master_data import POMasterCreate, POLineCreate


@pytest.fixture
def db_pair():
    """Two independent Session objects bound to the SAME temp-file SQLite database
    (not :memory:, which can silently give each connection its own empty database)
    -- used to simulate two concurrent requests racing against each other."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db1, db2 = Session(), Session()
    yield db1, db2
    db1.close()
    db2.close()
    engine.dispose()
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def db(db_pair):
    return db_pair[0]


def _make_customer(db, code="PMC", name="PMC Hydraulics Pvt Ltd"):
    c = Customer(customer_code=code, name=name)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def test_next_internal_part_number_continues_existing_sequence(db):
    customer = _make_customer(db)
    db.add(Part(part_number="PMC1", description="first"))
    db.add(Part(part_number="PMC97", description="ninety-seventh"))
    db.commit()
    assert next_internal_part_number(db, "PMC") == "PMC98"


def test_next_internal_part_number_starts_at_one_for_brand_new_prefix(db):
    assert next_internal_part_number(db, "ZZZ-NEW-CUST") == "ZZZ-NEW-CUST1"


def test_next_internal_part_number_ignores_gaps_and_other_customers_parts(db):
    db.add(Part(part_number="PMC5", description="x"))
    db.add(Part(part_number="HQP999", description="unrelated customer"))  # different prefix, must not interfere
    db.commit()
    assert next_internal_part_number(db, "PMC") == "PMC6"


def test_resolve_existing_customer_part_returns_existing_internal_part(db):
    customer = _make_customer(db)
    part = Part(part_number="PMC1", description="RC47NN135000000092")
    db.add(part)
    db.flush()
    mapping = CustomerPartMapping(customer_id=customer.id, part_id=part.id, customer_part_number="RC47NN135000000092")
    db.add(mapping)
    db.commit()

    resolved_part, is_new, resolved_mapping = resolve_customer_part(
        db, customer, "RC47NN135000000092", create_if_missing=True,
    )
    assert resolved_part.part_number == "PMC1"
    assert is_new is False
    assert resolved_mapping.id == mapping.id
    # Resolving an EXISTING mapping must never create a second Part.
    assert db.query(Part).count() == 1


def test_resolve_genuinely_new_customer_part_generates_next_internal_id(db):
    customer = _make_customer(db)
    db.add(Part(part_number="PMC97", description="existing"))
    db.commit()

    part, is_new, mapping = resolve_customer_part(db, customer, "NEW-CUST-PART-001", create_if_missing=True)
    db.commit()

    assert is_new is True
    assert part.part_number == "PMC98"
    assert part.description == "NEW-CUST-PART-001"
    assert mapping.customer_part_number == "NEW-CUST-PART-001"
    assert mapping.part_id == part.id
    assert mapping.customer_id == customer.id


def test_resolve_preview_never_creates_anything(db):
    customer = _make_customer(db)
    db.add(Part(part_number="PMC97", description="existing"))
    db.commit()

    part, is_new, mapping = resolve_customer_part(db, customer, "NOT-YET-MAPPED", create_if_missing=False)
    assert part is None
    assert is_new is True
    assert mapping is None
    assert db.query(Part).count() == 1  # nothing created
    assert db.query(CustomerPartMapping).count() == 0


def test_resolve_customer_part_preview_matches_actual_resolution(db):
    customer = _make_customer(db)
    part = Part(part_number="PMC1", description="desc")
    db.add(part)
    db.flush()
    db.add(CustomerPartMapping(customer_id=customer.id, part_id=part.id, customer_part_number="MAPPED-001"))
    db.commit()

    preview = resolve_customer_part_preview(db, "PMC", "MAPPED-001")
    assert preview.resolved is True
    assert preview.is_new is False
    assert preview.part_number == "PMC1"

    preview_new = resolve_customer_part_preview(db, "PMC", "SOMETHING-NEW")
    assert preview_new.resolved is False
    assert preview_new.is_new is True
    assert preview_new.part_number is None


def test_blank_customer_part_number_is_rejected_not_silently_created(db):
    customer = _make_customer(db)
    with pytest.raises(HTTPException) as exc_info:
        resolve_customer_part(db, customer, "   ", create_if_missing=True)
    assert exc_info.value.status_code == 400
    assert db.query(Part).count() == 0


def test_unknown_customer_code_preview_raises_404(db):
    with pytest.raises(HTTPException) as exc_info:
        resolve_customer_part_preview(db, "NO-SUCH-CUSTOMER-CODE", "ANYTHING")
    assert exc_info.value.status_code == 404


def test_list_customer_parts_returns_existing_mappings(db):
    customer = _make_customer(db)
    part = Part(part_number="PMC1", description="desc", grade="G1")
    db.add(part)
    db.flush()
    db.add(CustomerPartMapping(customer_id=customer.id, part_id=part.id, customer_part_number="CUST-001"))
    db.commit()

    rows = list_customer_parts(db, "PMC")
    assert len(rows) == 1
    assert rows[0].customer_part_number == "CUST-001"
    assert rows[0].part_number == "PMC1"
    assert rows[0].grade == "G1"


def test_list_customer_parts_unknown_customer_returns_empty(db):
    assert list_customer_parts(db, "NO-SUCH-CODE") == []


def test_concurrent_new_customer_part_creation_never_duplicates_internal_id(db_pair, monkeypatch):
    """The core concurrency guarantee: if a concurrent transaction (a second,
    wholly independent DB session) wins the race and commits the "next" internal
    Part Number first, this request's retry-on-IntegrityError must re-derive a
    fresh, non-colliding number rather than ever producing a duplicate.

    Forces the race deterministically: db1.commit() is patched so that, on its
    first call, a genuinely separate session (db2) inserts and commits the
    would-be-colliding Part first, then db1's commit raises IntegrityError --
    exactly what the real unique constraint on Part.part_number would do if two
    real concurrent requests both tried to insert "RACE1"."""
    db1, db2 = db_pair
    _make_customer(db1, code="RACE", name="Race Co")

    req = POMasterCreate(
        po_number="PO-RACE-1", customer_code="RACE",
        lines=[POLineCreate(customer_part_number="RACE-NEW-A", po_qty=1)],
    )

    real_commit = db1.commit
    call_count = {"n": 0}

    def fake_commit():
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Release db1's SQLite write lock first (a real concurrent Postgres
            # transaction wouldn't hold a whole-file lock, but this single-file
            # SQLite test DB does) so db2's "concurrent winner" write can proceed.
            db1.rollback()
            db2.expire_all()
            customer2 = db2.query(Customer).filter_by(customer_code="RACE").first()
            winner_part = Part(part_number="RACE1", description="winner, concurrent transaction")
            db2.add(winner_part)
            db2.flush()
            db2.add(CustomerPartMapping(
                customer_id=customer2.id, part_id=winner_part.id, customer_part_number="RACE-WINNER",
            ))
            db2.commit()
            raise IntegrityError("INSERT INTO parts ...", {}, Exception("UNIQUE constraint failed: parts.part_number"))
        return real_commit()

    monkeypatch.setattr(db1, "commit", fake_commit)

    result = POMasterService.create_po(db1, req)

    assert call_count["n"] == 2  # exactly one retry was needed
    assert result.lines[0].part_number == "RACE2"  # not "RACE1" -- that was already taken
    db1.expire_all()
    all_part_numbers = [p.part_number for p in db1.query(Part).all()]
    assert sorted(all_part_numbers) == ["RACE1", "RACE2"]  # no duplicate ever persisted
