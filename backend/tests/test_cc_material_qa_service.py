"""Continuous Casting material master and inward QA decision (Phase 11A). In-memory SQLite only.

Material master: create / read / update, no delete; identity frozen once an inward or a routing references the
material. Inward QA: the only operation that can move an inward out of PENDING_QA (ACCEPTED / REJECTED /
ON_HOLD), audited, atomic, no ledger row, no change to any stock unit. Together they make Material -> Inward ->
QA -> allocation -> reservation possible. SQLite ignores FOR UPDATE: the lock REQUESTS and the post-lock re-read
are tested, PostgreSQL row-lock behaviour is not proven.
"""
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Query

from app.core.database import Base
from app.core import roles as roles_module
from app.models import *  # noqa: F401,F403
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.schemas.continuous_casting import (
    CCAllocationCreate, CCInwardCreate, CCInwardQADecisionCreate, CCMaterialCreate, CCMaterialUpdate,
)
from app.services.continuous_casting_material_service import ContinuousCastingMaterialService as Mats
from app.services.continuous_casting_qa_service import ContinuousCastingQAService as QA
from app.services.continuous_casting_routing_service import ContinuousCastingAllocationService as AllocSvc
from app.services.continuous_casting_service import ContinuousCastingInwardService as InwardSvc

from test_cc_reservation_service import (  # noqa: F401
    db, shared, Ledger, Alloc, Unit, Routing, Inward, _user, make_wo, new_routing, allocate, reserve,
    count, rows, oms_state, snapshot, fresh, _raising_listener, cc,
)

Material = cc.ContinuousCastingMaterial
ALL_ROLES = list(UserRole)


# ------------------------------------------------------------------ helpers
def create(db, user=None, **over):
    data = dict(material_code="CC-001", grade="SG450", section="ROUND", stock_dimension_a_mm=200)
    data.update(over)
    return Mats.create_material(db, CCMaterialCreate(**data), user or _user(db, UserRole.ENGINEERING))


def update(db, material_id, user=None, **fields):
    return Mats.update_material(db, CCMaterialUpdate(material_id=material_id, **fields),
                                user or _user(db, UserRole.ENGINEERING))


def receive(db, material_id, lengths=(1000,), **over):
    return InwardSvc.create_inward(db, CCInwardCreate(material_id=material_id, unit_lengths_mm=list(lengths), **over),
                                   _user(db, UserRole.STORE))


def decide(db, inward_id, decision, reason=None, user=None):
    return QA.decide(db, CCInwardQADecisionCreate(inward_id=inward_id, decision=decision, reason=reason),
                     user or _user(db, UserRole.QA))


def material_row(db, result):
    return db.get(Material, uuid.UUID(result.material_id))


def audit(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).all()


@pytest.fixture()
def world(db):
    """A material and one PENDING_QA inward with a 1000 mm bar."""
    m = create(db)
    inw = receive(db, uuid.UUID(m.material_id))
    return dict(db=db, material=m, inward=inw, inward_id=uuid.UUID(inw.inward_id),
                material_id=uuid.UUID(m.material_id))


# ================================================================== roles
def test_role_tuples_use_existing_roles_only():
    assert roles_module.CC_MATERIAL_MASTER_ROLES == (UserRole.ADMIN, UserRole.ENGINEERING)
    assert roles_module.CC_QA_ROLES == (UserRole.ADMIN, UserRole.QA)
    assert not hasattr(UserRole, "QUALITY_MANAGER")                      # never invented
    assert roles_module.QUALITY_APPROVAL_ROLES == (UserRole.ADMIN, UserRole.QA)     # the same existing quality role
    assert {r.name for r in UserRole} >= {"ADMIN", "ENGINEERING", "QA"}


# ================================================================== MATERIAL MASTER
def test_create_a_valid_material(db):
    oms_before = oms_state(db)
    ledger_before = count(db, "cc_stock_ledger")
    eng = _user(db, UserRole.ENGINEERING)
    r = create(db, user=eng, material_code="  SG450-R200  ", stock_dimension_b_mm=120, description="  bar stock ")
    assert r.success and r.material_code == "SG450-R200" and r.grade == "SG450" and r.section == "ROUND"
    assert (r.stock_dimension_a_mm, r.stock_dimension_b_mm, r.description, r.is_active) == (200, 120, "bar stock", True)
    assert (r.referenced, r.inward_count, r.routing_count) == (False, 0, 0)
    assert r.created_by == eng.full_name == r.updated_by
    row = material_row(db, r)
    assert row.material_code == "SG450-R200" and row.is_active is True and row.created_by == eng.full_name
    a = audit(db, "CC_MATERIAL_CREATED")
    assert len(a) == 1 and a[0].entity_id == "SG450-R200" and a[0].user_id == eng.id and "200 x 120" in a[0].new_value
    assert count(db, "cc_stock_ledger") == ledger_before == 0 and oms_state(db) == oms_before   # no stock, no OMS rows
    assert db.query(Inward).count() == 0 and db.query(Unit).count() == 0


def test_dimension_b_and_description_are_optional(db):
    r = create(db)
    assert r.stock_dimension_b_mm is None and r.description is None


@pytest.mark.parametrize("role,allowed", [(UserRole.ADMIN, True), (UserRole.ENGINEERING, True),
                                          (UserRole.STORE, False), (UserRole.PLANNER, False), (UserRole.QA, False),
                                          (UserRole.PRODUCTION_MANAGER, False), (UserRole.CEO, False),
                                          (UserRole.DISPATCH, False), (UserRole.MACHINE_OPERATOR, False),
                                          (UserRole.MANUFACTURING, False), (UserRole.SALES, False)])
def test_material_create_and_update_roles(db, role, allowed):
    who = _user(db, role)
    seed = create(db, material_code="SEED")                             # an existing material to update
    before = snapshot(db), rows(db, "cc_materials")
    calls = (lambda: create(db, user=who, material_code="NEW-" + role.value),
             lambda: update(db, uuid.UUID(seed.material_id), user=who, description="x"))
    for call in calls:
        if allowed:
            assert call().success
        else:
            with pytest.raises(HTTPException) as e:
                call()
            assert e.value.status_code == 403
    if not allowed:
        assert (snapshot(db), rows(db, "cc_materials")) == before


def test_anonymous_cannot_create_or_update_a_material(db):
    seed = create(db)
    before = rows(db, "cc_materials")
    with pytest.raises(HTTPException) as e:
        Mats.create_material(db, CCMaterialCreate(material_code="X", grade="G", section="S", stock_dimension_a_mm=1), None)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        Mats.update_material(db, CCMaterialUpdate(material_id=uuid.UUID(seed.material_id), description="x"), None)
    assert e.value.status_code == 403 and rows(db, "cc_materials") == before


@pytest.mark.parametrize("code", ["CC-001", "cc-001", "Cc-001", "  CC-001  "])
def test_duplicate_material_code_is_a_409_regardless_of_case(db, code):
    create(db)
    before = rows(db, "cc_materials")
    with pytest.raises(HTTPException) as e:
        create(db, material_code=code)
    assert e.value.status_code == 409 and "already exists" in e.value.detail
    assert rows(db, "cc_materials") == before and len(audit(db, "CC_MATERIAL_CREATED")) == 1


@pytest.mark.parametrize("field,bad", [("stock_dimension_a_mm", 0), ("stock_dimension_a_mm", -5),
                                       ("stock_dimension_a_mm", 1.5), ("stock_dimension_a_mm", None),
                                       ("stock_dimension_b_mm", 0), ("stock_dimension_b_mm", -1),
                                       ("stock_dimension_b_mm", 2.5), ("stock_dimension_a_mm", "abc")])
def test_invalid_dimensions_are_rejected(db, field, bad):
    with pytest.raises(ValidationError):
        CCMaterialCreate(**{**dict(material_code="C", grade="G", section="S", stock_dimension_a_mm=10), field: bad})
    if bad is None and field == "stock_dimension_b_mm":
        return
    raw = CCMaterialCreate.model_construct(**{**dict(material_code="C", grade="G", section="S",
                                                     stock_dimension_a_mm=10, stock_dimension_b_mm=None,
                                                     description=None), field: bad})
    before = rows(db, "cc_materials")
    with pytest.raises(HTTPException) as e:                              # the service is safe without the schema
        Mats.create_material(db, raw, _user(db, UserRole.ENGINEERING))
    assert e.value.status_code == 400 and rows(db, "cc_materials") == before


@pytest.mark.parametrize("field", ["material_code", "grade", "section"])
@pytest.mark.parametrize("bad", ["", "   ", None])
def test_required_text_fields(db, field, bad):
    base = dict(material_code="C", grade="G", section="S", stock_dimension_a_mm=10)
    with pytest.raises(ValidationError):
        CCMaterialCreate(**{**base, field: bad})
    with pytest.raises(ValidationError):
        CCMaterialCreate(**{k: v for k, v in base.items() if k != field})
    raw = CCMaterialCreate.model_construct(**{**base, "stock_dimension_b_mm": None, "description": None, field: bad})
    with pytest.raises(HTTPException) as e:
        Mats.create_material(db, raw, _user(db, UserRole.ADMIN))
    assert e.value.status_code == 400 and field in e.value.detail


def test_unknown_fields_and_over_long_values_are_refused(db):
    base = dict(material_code="C", grade="G", section="S", stock_dimension_a_mm=10)
    for extra in ({"is_active": False}, {"created_by": "x"}, {"id": str(uuid.uuid4())}, {"revision": 2}):
        with pytest.raises(ValidationError):
            CCMaterialCreate(**base, **extra)
    with pytest.raises(ValidationError):
        CCMaterialCreate(**{**base, "grade": "x" * 101})
    with pytest.raises(ValidationError):
        CCMaterialCreate(**base, description="x" * 501)


# ------------------------------------------------------------------ update
def test_an_unused_material_can_be_edited_freely(db):
    r = create(db, stock_dimension_b_mm=100, description="old")
    mid = uuid.UUID(r.material_id)
    eng = _user(db, UserRole.ENGINEERING)
    u = update(db, mid, user=eng, material_code="NEW-CODE", grade="SG500", section="SQUARE", stock_dimension_a_mm=250,
               stock_dimension_b_mm=150, description="new")
    assert (u.material_code, u.grade, u.section, u.stock_dimension_a_mm, u.stock_dimension_b_mm, u.description) == (
        "NEW-CODE", "SG500", "SQUARE", 250, 150, "new")
    assert u.updated_by == eng.full_name and u.referenced is False
    a = audit(db, "CC_MATERIAL_UPDATED")
    assert len(a) == 1 and a[0].entity_id == "NEW-CODE" and "grade=SG450" in a[0].old_value and "grade=SG500" in a[0].new_value
    cleared = update(db, mid, stock_dimension_b_mm=None, description=None)         # explicit null clears
    assert cleared.stock_dimension_b_mm is None and cleared.description is None


def test_update_records_who_changed_it_separately_from_who_created_it(db):
    eng = _user(db, UserRole.ENGINEERING)
    admin = _user(db, UserRole.ADMIN)
    r = create(db, user=eng)
    u = update(db, uuid.UUID(r.material_id), user=admin, description="admin edit")
    assert u.created_by == eng.full_name and u.updated_by == admin.full_name
    row = material_row(db, r)
    assert (row.created_by, row.updated_by) == (eng.full_name, admin.full_name)
    assert audit(db, "CC_MATERIAL_UPDATED")[0].user_id == admin.id


def test_a_unique_violation_that_slips_past_the_precheck_is_a_clean_409(db, monkeypatch):
    """A concurrent create of the same code can pass the pre-check; the database unique constraint then fires.
    The service must roll back, report 409, and leave the session usable and the data untouched."""
    import app.services.continuous_casting_material_service as module
    eng = _user(db, UserRole.ENGINEERING)
    create(db, user=eng, material_code="DUP-1")
    before = rows(db, "cc_materials"), len(audit(db, "CC_MATERIAL_CREATED"))
    monkeypatch.setattr(module, "_duplicate_code", lambda *a, **k: False)        # the race: the pre-check saw nothing
    with pytest.raises(HTTPException) as e:
        create(db, user=eng, material_code="DUP-1")
    assert e.value.status_code == 409
    monkeypatch.undo()
    assert (rows(db, "cc_materials"), len(audit(db, "CC_MATERIAL_CREATED"))) == before    # session still usable, no partial row
    assert db.query(Material).count() == 1
    assert create(db, user=eng, material_code="DUP-2").success


def test_update_needs_a_real_change(db):
    r = create(db, description="same")
    mid = uuid.UUID(r.material_id)
    before = rows(db, "cc_materials")
    with pytest.raises(HTTPException) as e:
        update(db, mid)                                                  # nothing sent
    assert e.value.status_code == 400 and "Nothing to update" in e.value.detail
    with pytest.raises(HTTPException) as e:
        update(db, mid, grade="SG450", description="same")               # nothing differs
    assert e.value.status_code == 400 and "No changes" in e.value.detail
    for field in ("material_code", "grade", "section", "stock_dimension_a_mm", "is_active"):
        with pytest.raises(HTTPException) as e:                          # required fields can never be cleared
            Mats.update_material(db, CCMaterialUpdate.model_construct(material_id=mid, **{field: None}),
                                 _user(db, UserRole.ADMIN))
        assert e.value.status_code == 400 and "cannot be cleared" in e.value.detail
    assert rows(db, "cc_materials") == before and len(audit(db, "CC_MATERIAL_UPDATED")) == 0


def test_update_unknown_material_is_404_and_bad_values_are_rejected(db):
    r = create(db)
    with pytest.raises(HTTPException) as e:
        update(db, uuid.uuid4(), description="x")
    assert e.value.status_code == 404
    mid = uuid.UUID(r.material_id)
    for bad in ({"stock_dimension_a_mm": 0}, {"grade": "  "}, {"stock_dimension_b_mm": -1}):
        with pytest.raises(ValidationError):
            CCMaterialUpdate(material_id=mid, **bad)
    for extra in ({"inward_count": 3}, {"referenced": False}):
        with pytest.raises(ValidationError):
            CCMaterialUpdate(material_id=mid, **extra)


def test_update_cannot_take_another_materials_code(db):
    create(db, material_code="A-1")
    b = create(db, material_code="B-1")
    with pytest.raises(HTTPException) as e:
        update(db, uuid.UUID(b.material_id), material_code="a-1")
    assert e.value.status_code == 409


IDENTITY_CHANGES = [("material_code", "NEW"), ("grade", "SG999"), ("section", "OVAL"),
                    ("stock_dimension_a_mm", 300), ("stock_dimension_b_mm", 80)]


@pytest.mark.parametrize("field,value", IDENTITY_CHANGES)
def test_identity_is_frozen_once_an_inward_references_the_material(world, field, value):
    db = world["db"]
    before = rows(db, "cc_materials")
    with pytest.raises(HTTPException) as e:
        update(db, world["material_id"], **{field: value})
    assert e.value.status_code == 400 and "referenced by 1 inward" in e.value.detail and field in e.value.detail
    assert rows(db, "cc_materials") == before


def test_description_and_active_status_stay_editable_when_referenced(world):
    db = world["db"]
    inward_row = rows(db, "cc_inwards")
    u = update(db, world["material_id"], description="renamed for the drawing")
    assert u.description == "renamed for the drawing" and u.referenced and u.inward_count == 1
    assert update(db, world["material_id"], is_active=False).is_active is False
    assert update(db, world["material_id"], is_active=True).is_active is True
    assert rows(db, "cc_inwards") == inward_row                          # the inward's snapshot is never touched


def test_identity_is_frozen_when_only_a_routing_references_the_material(db):
    m = create(db)
    make_wo(db, "WO-1001")
    new_routing(db, material_row(db, m), "WO-1001")                      # a routing validated against it, no inward
    assert db.query(Inward).count() == 0
    r = Mats.get_material(db, uuid.UUID(m.material_id))
    assert (r.referenced, r.inward_count, r.routing_count) == (True, 0, 1)
    with pytest.raises(HTTPException) as e:
        update(db, uuid.UUID(m.material_id), grade="SG999")
    assert e.value.status_code == 400 and "1 routing" in e.value.detail
    assert update(db, uuid.UUID(m.material_id), description="ok").description == "ok"


def test_there_is_no_delete_operation(db):
    public = {n for n in dir(Mats) if not n.startswith("_")}
    assert public == {"create_material", "update_material", "get_material"}
    assert not any("delete" in n or "remove" in n for n in public)
    import app.services.continuous_casting_material_service as module
    assert not any("delete" in n.lower() or "remove" in n.lower() for n in dir(module) if not n.startswith("__"))


def test_get_material(world):
    db = world["db"]
    r = Mats.get_material(db, world["material_id"])                      # no role needed for reading
    assert r.material_code == "CC-001" and r.referenced and r.inward_count == 1 and r.routing_count == 0
    with pytest.raises(HTTPException) as e:
        Mats.get_material(db, uuid.uuid4())
    assert e.value.status_code == 404


def test_material_rolls_back_atomically(db, monkeypatch):
    eng = _user(db, UserRole.ENGINEERING)
    seed = create(db, user=eng)
    mid = uuid.UUID(seed.material_id)
    before = snapshot(db), rows(db, "cc_materials")
    for model, event_name in ((AuditLog, "before_insert"), (Material, "before_insert")):
        off = _raising_listener(model, event_name)
        try:
            with pytest.raises(RuntimeError):
                create(db, user=eng, material_code="NEW")
        finally:
            off()
        assert (snapshot(db), rows(db, "cc_materials")) == before
    for model, event_name in ((AuditLog, "before_insert"), (Material, "after_update")):
        off = _raising_listener(model, event_name)
        try:
            with pytest.raises(RuntimeError):
                update(db, mid, user=eng, description="changed")
        finally:
            off()
        assert (snapshot(db), rows(db, "cc_materials")) == before

    def failing():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", failing)
    with pytest.raises(RuntimeError):
        create(db, user=eng, material_code="NEW2")
    monkeypatch.undo()
    assert (snapshot(db), rows(db, "cc_materials")) == before
    assert create(db, user=eng, material_code="NEW").success             # a clean retry works


def test_material_update_locks_the_material_row(db, monkeypatch):
    r = create(db)
    order, real = [], Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    update(db, uuid.UUID(r.material_id), description="x")
    assert order == [Material]


def test_deactivating_a_material_blocks_new_inwards_but_not_existing_stock(world):
    db = world["db"]
    update(db, world["material_id"], is_active=False)
    units_before = rows(db, "cc_stock_units")
    with pytest.raises(HTTPException) as e:                              # the existing inward rule still holds
        receive(db, world["material_id"])
    assert e.value.status_code == 400 and "inactive" in e.value.detail
    assert rows(db, "cc_stock_units") == units_before and db.query(Inward).count() == 1
    update(db, world["material_id"], is_active=True)
    assert receive(db, world["material_id"], lengths=(500,)).success


def test_inward_validation_is_unchanged_for_service_created_materials(db):
    m = create(db, stock_dimension_a_mm=200, stock_dimension_b_mm=120)
    mid = uuid.UUID(m.material_id)
    assert receive(db, mid, lengths=(1000, 1200)).received_total_length_mm == 2200
    before = rows(db, "cc_inwards"), rows(db, "cc_stock_units")
    for over, fragment in (({"stock_dimension_a_mm": 201}, "does not match material"),
                           ({"stock_dimension_b_mm": 121}, "does not match material"),
                           ({"received_piece_count": 5}, "Declared piece count"),
                           ({"received_total_length_mm": 1}, "Declared total length")):
        with pytest.raises(HTTPException) as e:
            receive(db, mid, **over)
        assert e.value.status_code == 400 and fragment in e.value.detail
    with pytest.raises(ValidationError):
        CCInwardCreate(material_id=mid, unit_lengths_mm=[0])
    with pytest.raises(HTTPException) as e:
        receive(db, uuid.uuid4())
    assert e.value.status_code == 404
    assert (rows(db, "cc_inwards"), rows(db, "cc_stock_units")) == before


# ================================================================== INWARD QA DECISION
@pytest.mark.parametrize("decision,reason", [("ACCEPTED", None), ("ACCEPTED", "certificates match"),
                                             ("REJECTED", "out of tolerance"), ("ON_HOLD", "awaiting lab report")])
def test_pending_qa_inward_takes_each_decision(world, decision, reason):
    db, iid = world["db"], world["inward_id"]
    units_before, ledger_before = rows(db, "cc_stock_units"), rows(db, "cc_stock_ledger")
    oms_before = oms_state(db)
    qa_user = _user(db, UserRole.QA)
    assert fresh(db, Inward, iid).qa_status == "PENDING_QA"
    r = decide(db, iid, decision, reason, user=qa_user)
    assert r.success and (r.previous_qa_status, r.qa_status, r.reason) == ("PENDING_QA", decision, reason)
    assert r.decided_by == qa_user.full_name and r.qa_allows_allocation is (decision == "ACCEPTED")
    assert (r.qa_block_reason is None) is (decision == "ACCEPTED")
    inward = fresh(db, Inward, iid)
    assert inward.qa_status == decision and inward.updated_by == qa_user.full_name
    a = audit(db, "CC_INWARD_QA_DECISION")
    assert len(a) == 1 and (a[0].old_value, a[0].new_value, a[0].details) == ("PENDING_QA", decision, reason)
    assert a[0].user_id == qa_user.id and a[0].entity_id == inward.inward_number
    assert rows(db, "cc_stock_units") == units_before                   # no stock unit touched
    assert rows(db, "cc_stock_ledger") == ledger_before                 # QA is not a stock movement
    assert oms_state(db) == oms_before and count(db, "nc_records") == 0  # the OMS NC / quality flow is untouched
    assert inward.received_total_length_mm == 1000 and inward.received_piece_count == 1


@pytest.mark.parametrize("decision", ["REJECTED", "ON_HOLD"])
@pytest.mark.parametrize("bad", [None, "", "   "])
def test_rejected_and_hold_need_a_reason(world, decision, bad):
    db, iid = world["db"], world["inward_id"]
    with pytest.raises(ValidationError):
        CCInwardQADecisionCreate(inward_id=iid, decision=decision, reason=bad)
    raw = CCInwardQADecisionCreate.model_construct(inward_id=iid, decision=decision, reason=bad)
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:                              # the service is safe without the schema
        QA.decide(db, raw, _user(db, UserRole.QA))
    assert e.value.status_code == 400 and "reason is required" in e.value.detail
    assert snapshot(db) == before and fresh(db, Inward, iid).qa_status == "PENDING_QA"


def test_accepted_reason_is_optional_and_trimmed(world):
    r = decide(world["db"], world["inward_id"], "ACCEPTED", reason="  all good  ")
    assert r.reason == "all good"


@pytest.mark.parametrize("bad", ["PENDING_QA", "BOGUS", "accepted", "", None])
def test_only_the_three_decisions_exist(world, bad):
    db, iid = world["db"], world["inward_id"]
    with pytest.raises(ValidationError):
        CCInwardQADecisionCreate(inward_id=iid, decision=bad)
    if bad is None:
        return
    raw = CCInwardQADecisionCreate.model_construct(inward_id=iid, decision=bad, reason="x")
    with pytest.raises(HTTPException) as e:
        QA.decide(db, raw, _user(db, UserRole.QA))
    assert e.value.status_code == 400 and fresh(db, Inward, iid).qa_status == "PENDING_QA"


def test_unknown_fields_and_unknown_inward(world):
    db, iid = world["db"], world["inward_id"]
    for extra in ({"qa_status": "ACCEPTED"}, {"unit_status": "ON_HOLD"}, {"client_request_id": "k"}):
        with pytest.raises(ValidationError):
            CCInwardQADecisionCreate(inward_id=iid, decision="ACCEPTED", **extra)
    with pytest.raises(HTTPException) as e:
        decide(db, uuid.uuid4(), "ACCEPTED")
    assert e.value.status_code == 404


@pytest.mark.parametrize("role,allowed", [(UserRole.ADMIN, True), (UserRole.QA, True), (UserRole.STORE, False),
                                          (UserRole.ENGINEERING, False), (UserRole.PLANNER, False),
                                          (UserRole.PRODUCTION_MANAGER, False), (UserRole.CEO, False),
                                          (UserRole.DISPATCH, False), (UserRole.MACHINE_OPERATOR, False),
                                          (UserRole.MANUFACTURING, False)])
def test_qa_decision_roles(world, role, allowed):
    db, iid = world["db"], world["inward_id"]
    who = _user(db, role)
    before = snapshot(db)
    if allowed:
        assert decide(db, iid, "ACCEPTED", user=who).success
    else:
        with pytest.raises(HTTPException) as e:
            decide(db, iid, "ACCEPTED", user=who)
        assert e.value.status_code == 403
        assert snapshot(db) == before and fresh(db, Inward, iid).qa_status == "PENDING_QA"


def test_anonymous_cannot_decide(world):
    with pytest.raises(HTTPException) as e:
        QA.decide(world["db"], CCInwardQADecisionCreate(inward_id=world["inward_id"], decision="ACCEPTED"), None)
    assert e.value.status_code == 403


FIRST = ["ACCEPTED", "REJECTED", "ON_HOLD"]


@pytest.mark.parametrize("first", FIRST)
@pytest.mark.parametrize("second", FIRST)
def test_a_recorded_decision_is_never_rewritten(world, first, second):
    """Repeats and every other transition (REJECTED -> ACCEPTED, ON_HOLD -> ACCEPTED, ACCEPTED -> REJECTED ...)."""
    db, iid = world["db"], world["inward_id"]
    decide(db, iid, first, reason="r1")
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        decide(db, iid, second, reason="r2")
    assert e.value.status_code == 400 and f"already {first}" in e.value.detail
    assert ("same decision cannot be recorded again" in e.value.detail) is (first == second)
    assert snapshot(db) == before and fresh(db, Inward, iid).qa_status == first
    assert len(audit(db, "CC_INWARD_QA_DECISION")) == 1


@pytest.mark.parametrize("decision", ["REJECTED", "ON_HOLD"])
def test_an_inward_decision_never_cascades_to_stock_units(db, decision):
    m = create(db)
    inw = receive(db, uuid.UUID(m.material_id), lengths=(1000, 700))
    before = rows(db, "cc_stock_units")
    decide(db, uuid.UUID(inw.inward_id), decision, reason="quarantined")
    assert rows(db, "cc_stock_units") == before
    assert {u.status for u in db.query(Unit).all()} == {"IN_STOCK"}      # the inward's QA is separate from unit status
    assert all(u.remaining_length_mm == u.original_length_mm for u in db.query(Unit).all())


def test_qa_decision_rolls_back_atomically(world, monkeypatch):
    db, iid = world["db"], world["inward_id"]
    qa_user = _user(db, UserRole.QA)
    before = snapshot(db), rows(db, "cc_inwards")
    for model, event_name in ((AuditLog, "before_insert"), (Inward, "after_update")):
        off = _raising_listener(model, event_name)
        try:
            with pytest.raises(RuntimeError):
                decide(db, iid, "ACCEPTED", user=qa_user)
        finally:
            off()
        assert (snapshot(db), rows(db, "cc_inwards")) == before and fresh(db, Inward, iid).qa_status == "PENDING_QA"

    def failing():
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db, "commit", failing)
    with pytest.raises(RuntimeError):
        decide(db, iid, "ACCEPTED", user=qa_user)
    monkeypatch.undo()
    assert (snapshot(db), rows(db, "cc_inwards")) == before
    assert decide(db, iid, "ACCEPTED", user=qa_user).qa_status == "ACCEPTED"


def test_qa_decision_locks_only_the_inward(world, monkeypatch):
    qa_user = _user(world["db"], UserRole.QA)
    order, real = [], Query.with_for_update

    def spy(self, *a, **k):
        order.append(self.column_descriptions[0]["entity"])
        return real(self, *a, **k)

    monkeypatch.setattr(Query, "with_for_update", spy)
    decide(world["db"], world["inward_id"], "ACCEPTED", user=qa_user)
    assert order == [Inward]


def test_two_connections_cannot_both_decide(shared):
    s1, s2 = shared
    m = create(s1)
    inw = receive(s1, uuid.UUID(m.material_id))
    iid = uuid.UUID(inw.inward_id)
    qa1 = _user(s1, UserRole.QA)
    qa2 = s2.get(User, qa1.id)
    stale = s2.get(Inward, iid)                                          # connection B caches PENDING_QA
    assert stale.qa_status == "PENDING_QA"
    decide(s1, iid, "ACCEPTED", user=qa1)
    assert stale.qa_status == "PENDING_QA"                               # stale in B; truth is ACCEPTED
    with pytest.raises(HTTPException) as e:
        decide(s2, iid, "REJECTED", reason="late", user=qa2)
    assert e.value.status_code == 400 and "already ACCEPTED" in e.value.detail
    s1.expire_all()
    assert s1.get(Inward, iid).qa_status == "ACCEPTED" and len(audit(s1, "CC_INWARD_QA_DECISION")) == 1


# ================================================================== ALLOCATION ELIGIBILITY (existing logic)
def _allocate_raw(db, routing_id, unit, planned=500):
    return AllocSvc.create_allocation(
        db, CCAllocationCreate(routing_id=routing_id, stock_unit_id=unit.id, planned_length_mm=planned),
        _user(db, UserRole.PLANNER))


@pytest.fixture()
def planning(db):
    m = create(db)
    make_wo(db, "WO-1001")
    return dict(db=db, material=m, routing_id=new_routing(db, material_row(db, m), "WO-1001"),
                material_id=uuid.UUID(m.material_id))


@pytest.mark.parametrize("decision,reason", [("REJECTED", "bad grade"), ("ON_HOLD", "lab pending")])
def test_non_accepted_inward_stock_cannot_be_allocated(planning, decision, reason):
    db = planning["db"]
    inw = receive(db, planning["material_id"])
    (unit,) = db.query(Unit).filter_by(inward_id=uuid.UUID(inw.inward_id)).all()
    expected = cc.allocation_ineligibility_reason(unit)
    assert "PENDING_QA" in expected and cc.is_allocation_eligible(unit) is False   # PENDING_QA blocked
    before = snapshot(db)
    with pytest.raises(HTTPException) as e:
        _allocate_raw(db, planning["routing_id"], unit)
    assert e.value.status_code == 400 and "PENDING_QA" in e.value.detail
    decide(db, uuid.UUID(inw.inward_id), decision, reason)
    unit = fresh(db, Unit, unit.id)
    assert decision in cc.allocation_ineligibility_reason(unit) and cc.is_allocation_eligible(unit) is False
    with pytest.raises(HTTPException) as e:
        _allocate_raw(db, planning["routing_id"], unit)
    assert e.value.status_code == 400 and decision in e.value.detail
    assert db.query(Alloc).count() == 0 and snapshot(db)["cc_allocations"] == before["cc_allocations"]


def test_accepted_inward_stock_becomes_allocatable(planning):
    db = planning["db"]
    inw = receive(db, planning["material_id"])
    (unit,) = db.query(Unit).filter_by(inward_id=uuid.UUID(inw.inward_id)).all()
    assert cc.is_allocation_eligible(unit) is False
    decide(db, uuid.UUID(inw.inward_id), "ACCEPTED")
    unit = fresh(db, Unit, unit.id)
    assert cc.allocation_ineligibility_reason(unit) is None and cc.is_allocation_eligible(unit) is True
    a = _allocate_raw(db, planning["routing_id"], unit)
    assert a.success and a.planned_length_mm == 500


def test_the_other_frozen_conditions_still_apply_after_acceptance(planning):
    db = planning["db"]
    inw = receive(db, planning["material_id"])
    decide(db, uuid.UUID(inw.inward_id), "ACCEPTED")
    (unit,) = db.query(Unit).filter_by(inward_id=uuid.UUID(inw.inward_id)).all()
    unit.status = "ON_HOLD"                                              # the unit-level conditions are unchanged
    db.commit()
    assert "unit status is ON_HOLD" in cc.allocation_ineligibility_reason(fresh(db, Unit, unit.id))
    unit = fresh(db, Unit, unit.id)
    unit.status, unit.remaining_length_mm = "IN_STOCK", 1000
    db.commit()
    assert cc.is_allocation_eligible(fresh(db, Unit, unit.id)) is True


# ================================================================== END TO END through the real services
def test_material_to_reservation_is_possible_only_after_qa_acceptance(db):
    m = create(db, material_code="SG450-R200")                           # Engineering creates the material
    mid = uuid.UUID(m.material_id)
    inw = receive(db, mid, lengths=(1000,))                              # Stores receive the bar
    iid = uuid.UUID(inw.inward_id)
    assert inw.qa_status == "PENDING_QA" and inw.allocation_eligible is False
    make_wo(db, "WO-1001")
    rid = new_routing(db, material_row(db, m), "WO-1001")                # Engineering validates the routing
    (unit,) = db.query(Unit).filter_by(inward_id=iid).all()
    with pytest.raises(HTTPException):                                   # before QA: nothing can be planned
        _allocate_raw(db, rid, unit)
    decide(db, iid, "ACCEPTED", reason="mill certificate verified")      # Quality accepts
    alloc = allocate(db, rid, fresh(db, Unit, unit.id), 600)             # Planning allocates
    r = reserve(db, rid, alloc, 400)                                     # ... and reserves, through the real services
    assert r.success and r.unit_reserved_length_mm == 400 and r.unit_free_length_mm == 600
    assert count(db, "cc_stock_ledger") == 2                             # INWARD + RESERVE; the QA decision added none
    assert [a.action for a in db.query(AuditLog).order_by(AuditLog.created_at).all()
            if a.action.startswith("CC_")][:3] == ["CC_MATERIAL_CREATED", "CC_INWARD", "CC_ROUTING_CREATED"]
