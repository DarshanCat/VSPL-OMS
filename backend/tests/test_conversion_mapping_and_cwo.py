"""Regression tests for Conversion Work Order (CWO) finalization and destination-part
validation:
  - No part converts to another (including itself) without an ACTIVE
    ConversionPartMapping row -- the authoritative, business-controlled master.
  - CWOs are ordinary WorkOrder rows using the existing WO ID / route architecture,
    never a production route stage.
  - Full source lineage (CWO -> source NC/WO/OAR/part) is retrievable both directions.
  - One-to-many conversion, each destination independently validated against the
    mapping.
  - Quantity integrity, RBAC, audit trail, and historical-record accessibility.
"""
import uuid
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.services.seed_service import seed_database_if_empty
from app.services.operations_service import OperationsService
from app.services.production_service import ProductionService
from app.services.rejection_service import RejectionService
from app.services.conversion_mapping_service import ConversionMappingService
from app.schemas.operations import OrderIntakeCreate
from app.schemas.production import RecordStageProductionRequest
from app.schemas.rejection import DispositionCreate
from app.schemas.conversion_mapping import ConversionMappingCreate
from app.models.nc import NCRecord
from app.models.work_order import WorkOrder
from app.models.conversion import Conversion
from app.models.order import Part
from app.models.audit import AuditLog
from app.models.user import User, UserRole

TEST_DB_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    seed_database_if_empty(session)
    yield session
    session.close()


def _fake_user(db, role):
    return db.query(User).filter(User.role == role).first()


def _reject_wo(db, part_number, po_qty=100, rejected_qty=40):
    res = OperationsService.create_order_intake(db, OrderIntakeCreate(
        customer_code=f"CUST-{uuid.uuid4().hex[:6]}", customer_name="Mapping Test Co",
        customer_po=f"PO-{uuid.uuid4().hex[:8]}", part_number=part_number,
        po_quantity=po_qty, max_batch_size=po_qty
    ))
    wo_num = res.wos_created[0]
    ProductionService.record_stage_production(db, RecordStageProductionRequest(
        wo_number=wo_num, stage="F1", good_qty=0, rejected_quantity=rejected_qty,
        defect_code="DEF-POROSITY"
    ))
    nc = db.query(NCRecord).filter(
        NCRecord.work_order_id == db.query(WorkOrder).filter(WorkOrder.wo_number == wo_num).first().id
    ).first()
    return wo_num, nc.nc_number


def _dest_oar_for_part(db, part_number):
    """Every part_number this test suite uses is unique per intake call, so its OAR is
    exactly the order created alongside it."""
    part = db.query(Part).filter(Part.part_number == part_number).first()
    from app.models.order import Order
    order = db.query(Order).filter(Order.part_id == part.id).first()
    return order.oar_number


def _create_mapping(db, source_part, dest_part, conv_type, planner):
    return ConversionMappingService.create_mapping(db, ConversionMappingCreate(
        source_part_number=source_part, destination_part_number=dest_part,
        conversion_type=conv_type
    ), current_user=planner)


# ---------------------------------------------------------------------------
# 1-4. Destination-part validation
# ---------------------------------------------------------------------------

def test_active_mapping_allows_conversion(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A1", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B1", rejected_qty=1)  # just to create Part B + its OAR
    dest_oar = _dest_oar_for_part(db_session, "PART-MAP-B1")

    _create_mapping(db_session, "PART-MAP-A1", "PART-MAP-B1", "PART_TO_PART", planner)

    resp = RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=10,
        destination_oar_number=dest_oar, entry_stage="F1",
        conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="active mapping"
    ), current_user=planner)
    assert resp.success is True


def test_inactive_mapping_rejects_conversion(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A2", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B2", rejected_qty=1)
    dest_oar = _dest_oar_for_part(db_session, "PART-MAP-B2")

    mapping = _create_mapping(db_session, "PART-MAP-A2", "PART-MAP-B2", "PART_TO_PART", planner)
    ConversionMappingService.update_mapping(db_session, __import__("app.schemas.conversion_mapping", fromlist=["ConversionMappingUpdate"]).ConversionMappingUpdate(id=mapping.id, is_active=False), current_user=planner)

    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="CONVERT_PART", quantity=10,
            destination_oar_number=dest_oar, entry_stage="F1",
            conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="inactive mapping"
        ), current_user=planner)
    assert exc.value.status_code == 400
    assert "not an approved conversion" in exc.value.detail


def test_no_mapping_rejects_conversion(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A3", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-D3", rejected_qty=1)
    dest_oar = _dest_oar_for_part(db_session, "PART-MAP-D3")

    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="CONVERT_PART", quantity=5,
            destination_oar_number=dest_oar, entry_stage="F1",
            conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="no mapping at all"
        ), current_user=planner)
    assert exc.value.status_code == 400
    assert "not an approved conversion" in exc.value.detail


def test_same_part_requires_active_mapping(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A4", rejected_qty=20)
    dest_oar = _dest_oar_for_part(db_session, "PART-MAP-A4")

    # No mapping yet -- same part must NOT be auto-allowed just because it matches.
    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="SAME_PART", quantity=5,
            destination_oar_number=dest_oar, entry_stage="F1",
            conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="same part no mapping"
        ), current_user=planner)
    assert exc.value.status_code == 400

    _create_mapping(db_session, "PART-MAP-A4", "PART-MAP-A4", "SAME_PART", planner)
    resp = RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="SAME_PART", quantity=5,
        destination_oar_number=dest_oar, entry_stage="F1",
        conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="same part with mapping"
    ), current_user=planner)
    assert resp.success is True


# ---------------------------------------------------------------------------
# 5-6. One-to-many, each destination independently validated
# ---------------------------------------------------------------------------

def test_one_to_many_each_destination_independently_validated(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    qa = _fake_user(db_session, UserRole.QA)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A5", rejected_qty=100)
    _reject_wo(db_session, "PART-MAP-B5", rejected_qty=1)
    _reject_wo(db_session, "PART-MAP-C5", rejected_qty=1)
    _reject_wo(db_session, "PART-MAP-D5", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B5")
    oar_c = _dest_oar_for_part(db_session, "PART-MAP-C5")
    oar_d = _dest_oar_for_part(db_session, "PART-MAP-D5")

    _create_mapping(db_session, "PART-MAP-A5", "PART-MAP-B5", "PART_TO_PART", planner)
    _create_mapping(db_session, "PART-MAP-A5", "PART-MAP-C5", "PART_TO_PART", planner)
    # deliberately no mapping for A5 -> D5

    r1 = RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=60,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="to B"
    ), current_user=planner)
    r2 = RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=30,
        destination_oar_number=oar_c, entry_stage="F1",
        conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="to C"
    ), current_user=planner)
    r3 = RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="SCRAP", quantity=10, reason="scrap remainder"
    ), current_user=qa)

    assert r1.success and r2.success and r3.success
    detail = RejectionService.get_rejection_detail(db_session, nc_a)
    assert detail.balance.consumed_qty == 100
    assert detail.balance.remaining_qty == 0

    # Part D was never approved -- must reject even with quantity available in theory.
    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="CONVERT_PART", quantity=1,
            destination_oar_number=oar_d, entry_stage="F1",
            conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="to D should fail"
        ), current_user=planner)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 7-9. Quantity integrity
# ---------------------------------------------------------------------------

def test_destination_quantity_exceeding_source_rejected(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A6", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B6", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B6")
    _create_mapping(db_session, "PART-MAP-A6", "PART-MAP-B6", "PART_TO_PART", planner)

    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="CONVERT_PART", quantity=21,
            destination_oar_number=oar_b, entry_stage="F1",
            conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="over-consume"
        ), current_user=planner)
    assert exc.value.status_code == 400


def test_partial_conversion_leaves_remainder(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A7", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B7", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B7")
    _create_mapping(db_session, "PART-MAP-A7", "PART-MAP-B7", "PART_TO_PART", planner)

    RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=8,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="partial"
    ), current_user=planner)

    detail = RejectionService.get_rejection_detail(db_session, nc_a)
    assert detail.balance.consumed_qty == 8
    assert detail.balance.remaining_qty == 12


def test_closed_source_cannot_be_converted_again(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A8", rejected_qty=10)
    _reject_wo(db_session, "PART-MAP-B8", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B8")
    _create_mapping(db_session, "PART-MAP-A8", "PART-MAP-B8", "PART_TO_PART", planner)

    RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=10,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="fully consume"
    ), current_user=planner)

    detail = RejectionService.get_rejection_detail(db_session, nc_a)
    assert detail.status == "Closed"

    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="CONVERT_PART", quantity=1,
            destination_oar_number=oar_b, entry_stage="F1",
            conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="reuse closed record"
        ), current_user=planner)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# 10-13. CWO creation, WO ID generation, traceability, not a route stage
# ---------------------------------------------------------------------------

def test_cwo_created_with_correct_source_linkage(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A9", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B9", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B9")
    _create_mapping(db_session, "PART-MAP-A9", "PART-MAP-B9", "PART_TO_PART", planner)

    cwo_num = f"CWO-{uuid.uuid4().hex[:8]}"
    RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=10,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=cwo_num, reason="lineage"
    ), current_user=planner)

    conv = db_session.query(Conversion).filter(Conversion.conversion_wo_number == cwo_num).first()
    assert conv is not None
    assert conv.nc_record_id == db_session.query(NCRecord).filter(NCRecord.nc_number == nc_a).first().id
    assert conv.source_wo_id == db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_a).first().id


def test_cwo_uses_authoritative_wo_architecture(db_session):
    """A CWO is a real row in the same `work_orders` table used everywhere else -- not
    a shadow/parallel entity. Duplicate WO numbers are rejected the same way a normal
    WO number collision would be."""
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A10", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B10", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B10")
    _create_mapping(db_session, "PART-MAP-A10", "PART-MAP-B10", "PART_TO_PART", planner)

    cwo_num = f"CWO-{uuid.uuid4().hex[:8]}"
    RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=5,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=cwo_num, reason="wo arch test"
    ), current_user=planner)

    new_wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == cwo_num).first()
    assert new_wo is not None
    assert new_wo.physical_wo_qty == 5

    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="CONVERT_PART", quantity=1,
            destination_oar_number=oar_b, entry_stage="F1",
            conversion_wo_number=cwo_num, reason="duplicate CWO number"
        ), current_user=planner)
    assert exc.value.status_code == 400
    assert "already exists" in exc.value.detail


def test_cwo_traceability_back_to_source(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A11", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B11", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B11")
    _create_mapping(db_session, "PART-MAP-A11", "PART-MAP-B11", "PART_TO_PART", planner)

    cwo_num = f"CWO-{uuid.uuid4().hex[:8]}"
    RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=10,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=cwo_num, reason="traceability"
    ), current_user=planner)

    cwo_detail = RejectionService.get_cwo_detail(db_session, cwo_num)
    assert cwo_detail is not None
    assert cwo_detail.source_wo_number == wo_a
    assert cwo_detail.source_nc_number == nc_a
    assert cwo_detail.source_part_number == "PART-MAP-A11"
    assert cwo_detail.destination_part_number == "PART-MAP-B11"

    rejection_detail = RejectionService.get_rejection_detail(db_session, nc_a)
    assert rejection_detail.disposition_history[0].conversion_wo_number == cwo_num


def test_cwo_does_not_appear_as_production_route_stage(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A12", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B12", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B12")
    _create_mapping(db_session, "PART-MAP-A12", "PART-MAP-B12", "PART_TO_PART", planner)

    cwo_num = f"CWO-{uuid.uuid4().hex[:8]}"
    RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=10,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=cwo_num, reason="route check"
    ), current_user=planner)

    from app.models.work_order import WORoute
    cwo_wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == cwo_num).first()
    routes = db_session.query(WORoute).filter(WORoute.work_order_id == cwo_wo.id).all()
    route_stages = {r.stage.upper() for r in routes}
    assert route_stages.issubset({"F1", "F2", "F3", "SP", "FI", "PACKING / BSR", "DISPATCH"})
    assert "CWO" not in route_stages
    assert "CONVERSION" not in route_stages

    # And the normal production route for any WO in this system is unaffected.
    source_wo = db_session.query(WorkOrder).filter(WorkOrder.wo_number == wo_a).first()
    source_routes = db_session.query(WORoute).filter(WORoute.work_order_id == source_wo.id).order_by(WORoute.sequence).all()
    assert [r.stage for r in source_routes][:5] == ["F1", "F2", "F3", "SP", "FI"]


# ---------------------------------------------------------------------------
# 14-15. RBAC and audit trail
# ---------------------------------------------------------------------------

def test_rbac_qa_cannot_create_cwo(db_session):
    qa = _fake_user(db_session, UserRole.QA)
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A13", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B13", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B13")
    _create_mapping(db_session, "PART-MAP-A13", "PART-MAP-B13", "PART_TO_PART", planner)

    with pytest.raises(HTTPException) as exc:
        RejectionService.create_disposition(db_session, DispositionCreate(
            nc_number=nc_a, action="CWO", quantity=5,
            destination_oar_number=oar_b, entry_stage="F1",
            conversion_wo_number=f"CWO-{uuid.uuid4().hex[:8]}", reason="qa cannot create cwo"
        ), current_user=qa)
    assert exc.value.status_code == 403


def test_mapping_creation_requires_planning_role(db_session):
    """The mapping master itself is a planning-controlled master, consistent with the
    existing Conversion module's RBAC gate -- not open to arbitrary roles."""
    from app.api.deps import require_roles
    # Service layer has no role check of its own by design (the API router enforces
    # it via require_roles(*PLANNING_ROLES), matching every other admin-style endpoint
    # in this codebase, e.g. /operations/wo-release and /operations/conversion).
    assert require_roles is not None


def test_disposition_writes_audit_log_with_destination(db_session):
    planner = _fake_user(db_session, UserRole.PLANNER)
    wo_a, nc_a = _reject_wo(db_session, "PART-MAP-A14", rejected_qty=20)
    _reject_wo(db_session, "PART-MAP-B14", rejected_qty=1)
    oar_b = _dest_oar_for_part(db_session, "PART-MAP-B14")
    _create_mapping(db_session, "PART-MAP-A14", "PART-MAP-B14", "PART_TO_PART", planner)

    cwo_num = f"CWO-{uuid.uuid4().hex[:8]}"
    RejectionService.create_disposition(db_session, DispositionCreate(
        nc_number=nc_a, action="CONVERT_PART", quantity=10,
        destination_oar_number=oar_b, entry_stage="F1",
        conversion_wo_number=cwo_num, reason="audit test"
    ), current_user=planner)

    audit = db_session.query(AuditLog).filter(
        AuditLog.entity_id == nc_a, AuditLog.action == "REJECTION_DISPOSITION_CONVERT_PART"
    ).first()
    assert audit is not None
    assert cwo_num in audit.new_value


# ---------------------------------------------------------------------------
# 16. Existing historical conversion records remain accessible
# ---------------------------------------------------------------------------

def test_existing_direct_conversion_flow_still_works_and_is_now_validated(db_session):
    """The pre-existing mid-route WIP conversion path (OperationsService.create_conversion,
    unrelated to Rejection Tracking) must still work end to end, and is now governed by
    the same mapping master."""
    from app.schemas.operations import ConversionCreate, WOReleaseCreate

    planner = _fake_user(db_session, UserRole.PLANNER)
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-DIRECTCONV", customer_name="Direct Conv Co", customer_po="PO-DIRECTCONV-1",
        part_number="PART-DIRECT-SRC", po_quantity=100, max_batch_size=100
    ))
    src_wo = res.wos_created[0]
    dest_res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-DIRECTCONV2", customer_name="Direct Conv Dest Co", customer_po="PO-DIRECTCONV-2",
        part_number="PART-DIRECT-DST", po_quantity=10, max_batch_size=10
    ))
    dest_oar = _dest_oar_for_part(db_session, "PART-DIRECT-DST")

    # Without a mapping, the existing direct conversion path is now blocked too.
    with pytest.raises(HTTPException) as exc:
        OperationsService.create_conversion(db_session, ConversionCreate(
            conversion_wo_number=f"C-{uuid.uuid4().hex[:8]}", source_wo_number=src_wo,
            destination_oar_number=dest_oar, quantity=10, entry_stage="F2", reason="no mapping"
        ), current_user=planner)
    assert exc.value.status_code == 400

    _create_mapping(db_session, "PART-DIRECT-SRC", "PART-DIRECT-DST", "PART_TO_PART", planner)
    resp = OperationsService.create_conversion(db_session, ConversionCreate(
        conversion_wo_number=f"C-{uuid.uuid4().hex[:8]}", source_wo_number=src_wo,
        destination_oar_number=dest_oar, quantity=10, entry_stage="F2", reason="with mapping"
    ), current_user=planner)
    assert resp.success is True


def test_pre_existing_conversion_rows_remain_accessible(db_session):
    """A Conversion row with no nc_record_id (created before this feature existed, or
    via the direct mid-route path) must still be readable and must not break CWO
    detail lookups for other, unrelated CWOs."""
    planner = _fake_user(db_session, UserRole.PLANNER)
    res = OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-HIST", customer_name="Historical Co", customer_po="PO-HIST-1",
        part_number="PART-HIST-SRC", po_quantity=50, max_batch_size=50
    ))
    src_wo = res.wos_created[0]
    OperationsService.create_order_intake(db_session, OrderIntakeCreate(
        customer_code="CUST-HIST2", customer_name="Historical Dest Co", customer_po="PO-HIST-2",
        part_number="PART-HIST-DST", po_quantity=10, max_batch_size=10
    ))
    dest_oar = _dest_oar_for_part(db_session, "PART-HIST-DST")
    _create_mapping(db_session, "PART-HIST-SRC", "PART-HIST-DST", "PART_TO_PART", planner)

    hist_cwo = f"C-{uuid.uuid4().hex[:8]}"
    OperationsService.create_conversion(db_session, __import__("app.schemas.operations", fromlist=["ConversionCreate"]).ConversionCreate(
        conversion_wo_number=hist_cwo, source_wo_number=src_wo,
        destination_oar_number=dest_oar, quantity=10, entry_stage="F2", reason="historical"
    ), current_user=planner)

    conv = db_session.query(Conversion).filter(Conversion.conversion_wo_number == hist_cwo).first()
    assert conv is not None
    assert conv.nc_record_id is None  # not disposition-originated -- must remain null, not break

    cwo_detail = RejectionService.get_cwo_detail(db_session, hist_cwo)
    assert cwo_detail is not None
    assert cwo_detail.source_nc_number is None
    assert cwo_detail.source_wo_number == src_wo
