from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.master_data import POMaster, POLine, POStatus
from app.schemas.master_data import POMergeRequest
from app.services.master_data_service import POMasterService


def _make_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def test_merge_pos_moves_lines_and_updates_linked_oars():
    db = _make_db()
    cust = Customer(customer_code="PMC", name="PMC Hydraulics Pvt Ltd")
    p1 = Part(part_number="PMC242", description="Part 1", grade="SG 450")
    p2 = Part(part_number="PMC217", description="Part 2", grade="SG 450")
    db.add_all([cust, p1, p2])
    db.flush()

    target_po = POMaster(
        customer_id=cust.id,
        po_number="31PO0007932-1",
        po_date=date(2026, 7, 16),
        status=POStatus.OPEN,
        total_value=308.0,
    )
    source_po = POMaster(
        customer_id=cust.id,
        po_number="1241709 (74 x 78 x 88) 0.5",
        po_date=date(2026, 11, 7),
        validity_date=date(2027, 3, 1),
        status=POStatus.OPEN,
        total_value=9320.0,
    )
    db.add_all([target_po, source_po])
    db.flush()

    target_line = POLine(
        po_id=target_po.id,
        part_id=p1.id,
        po_qty=1,
        unit_price=308.0,
        line_total=308.0,
    )
    source_line = POLine(
        po_id=source_po.id,
        part_id=p2.id,
        po_qty=20,
        unit_price=466.0,
        line_total=9320.0,
    )
    db.add_all([target_line, source_line])
    db.flush()

    oar1 = Order(
        oar_number="OAR-8622",
        customer_id=cust.id,
        part_id=p1.id,
        customer_po="31PO0007932-1",
        po_line_id=target_line.id,
        po_qty=1,
        status=OrderStatus.ACCEPT,
    )
    oar2 = Order(
        oar_number="OAR-8627",
        customer_id=cust.id,
        part_id=p2.id,
        customer_po="1241709 (74 x 78 x 88) 0.5",
        po_line_id=source_line.id,
        po_qty=20,
        status=OrderStatus.ACCEPT,
    )
    db.add_all([oar1, oar2])
    db.commit()

    out = POMasterService.merge_pos(
        db,
        POMergeRequest(source_po_id=str(source_po.id), target_po_id=str(target_po.id)),
    )

    assert out.id == str(target_po.id)
    assert out.po_number == "31PO0007932-1"
    assert len(out.lines) == 2
    assert out.total_value == 9628.0
    assert out.validity_date == date(2027, 3, 1)

    db.refresh(oar2)
    assert oar2.po_line_id == source_line.id
    assert oar2.customer_po == "31PO0007932-1"
    assert db.query(POMaster).filter(POMaster.id == source_po.id).first() is None
