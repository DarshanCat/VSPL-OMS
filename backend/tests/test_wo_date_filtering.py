import uuid
from datetime import datetime, date, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.core.database import SessionLocal
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WOStatus
from app.services.work_order_service import WorkOrderService
from app.main import app

@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def _auth_headers(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/login", json={"email": "admin@vspl.com", "password": "admin123"})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_wo_date_filtering_and_sorting(client):
    headers = _auth_headers(client)
    db = SessionLocal()
    try:
        # Create test customer and part
        cust = Customer(name=f"Date Test Cust {uuid.uuid4().hex[:6]}", customer_code=f"DTC_{uuid.uuid4().hex[:4]}")
        part = Part(part_number=f"DTP_{uuid.uuid4().hex[:6]}", grade="Bronze")
        db.add_all([cust, part])
        db.commit()

        # Create orders and work orders on different dates
        order1 = Order(
            oar_number=f"OAR-DT-1-{uuid.uuid4().hex[:4]}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po="PO-DT-1",
            po_qty=100,
            max_batch_size=50,
            delivery_date=date(2026, 11, 10),
            status=OrderStatus.ACCEPT
        )
        order2 = Order(
            oar_number=f"OAR-DT-2-{uuid.uuid4().hex[:4]}",
            customer_id=cust.id,
            part_id=part.id,
            customer_po="PO-DT-2",
            po_qty=200,
            max_batch_size=50,
            delivery_date=date(2026, 12, 25),
            status=OrderStatus.ACCEPT
        )
        db.add_all([order1, order2])
        db.commit()

        wo1_num = f"WO-DATE-1-{uuid.uuid4().hex[:4]}"
        wo2_num = f"WO-DATE-2-{uuid.uuid4().hex[:4]}"

        # WO1 created 2026-10-01, released 2026-10-05
        wo1 = WorkOrder(
            wo_number=wo1_num,
            order_id=order1.id,
            physical_wo_qty=50,
            current_stage="F1",
            status=WOStatus.RELEASED,
            released_by="planner@vspl.com",
            release_date=datetime(2026, 10, 5, 10, 0, 0, tzinfo=timezone.utc),
            created_at=datetime(2026, 10, 1, 9, 0, 0, tzinfo=timezone.utc)
        )
        # WO2 created 2026-10-14, unreleased
        wo2 = WorkOrder(
            wo_number=wo2_num,
            order_id=order2.id,
            physical_wo_qty=60,
            current_stage="F1",
            status=WOStatus.OPEN,
            created_at=datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        )
        db.add_all([wo1, wo2])
        db.commit()

        # 1. Test filtering by wo_date range (Oct 1 to Oct 5 includes wo1, excludes wo2)
        resp = client.get("/api/v1/work-orders", headers=headers, params={
            "from_date": "2026-10-01",
            "to_date": "2026-10-05",
            "date_type": "wo_date"
        })
        assert resp.status_code == 200
        wos = resp.json()
        wo_nums = [w["wo_number"] for w in wos]
        assert wo1_num in wo_nums
        assert wo2_num not in wo_nums

        # 2. Test filtering by wo_date range (Oct 10 to Oct 15 includes wo2, excludes wo1)
        resp = client.get("/api/v1/work-orders", headers=headers, params={
            "from_date": "2026-10-10",
            "to_date": "2026-10-15",
            "date_type": "wo_date"
        })
        assert resp.status_code == 200
        wos = resp.json()
        wo_nums = [w["wo_number"] for w in wos]
        assert wo2_num in wo_nums
        assert wo1_num not in wo_nums

        # 3. Test filtering by release_date
        resp = client.get("/api/v1/work-orders", headers=headers, params={
            "from_date": "2026-10-01",
            "to_date": "2026-10-10",
            "date_type": "release_date"
        })
        assert resp.status_code == 200
        wos = resp.json()
        wo_nums = [w["wo_number"] for w in wos]
        assert wo1_num in wo_nums
        assert wo2_num not in wo_nums

        # 4. Test filtering by delivery_date
        resp = client.get("/api/v1/work-orders", headers=headers, params={
            "from_date": "2026-11-01",
            "to_date": "2026-11-30",
            "date_type": "delivery_date"
        })
        assert resp.status_code == 200
        wos = resp.json()
        wo_nums = [w["wo_number"] for w in wos]
        assert wo1_num in wo_nums
        assert wo2_num not in wo_nums

        # 5. Test search with date string "2026-10-14"
        resp = client.get("/api/v1/work-orders", headers=headers, params={
            "search": "2026-10-14"
        })
        assert resp.status_code == 200
        wos = resp.json()
        wo_nums = [w["wo_number"] for w in wos]
        assert wo2_num in wo_nums

        # 6. Test sorting by release_date_desc
        resp = client.get("/api/v1/work-orders", headers=headers, params={
            "sort_by": "release_date_desc"
        })
        assert resp.status_code == 200

    finally:
        db.close()
