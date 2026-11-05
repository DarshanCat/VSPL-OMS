import sys
sys.path.append("backend")
import os
import pytest
from app.core.database import SessionLocal
from app.models.order import Part, Customer, OrderStatus
from app.models.master_data import ScheduleMaster
from app.services.master_data_service import ScheduleMasterService
from app.services.operations_service import OperationsService
from app.schemas.master_data import ScheduleCreate
from app.schemas.operations import OrderIntakeCreate

def test_partial_schedule_oar_generation():
    db = SessionLocal()
    try:
        cust = db.query(Customer).filter(Customer.customer_code == "MIL").first()
        if not cust:
            print("MIL not found, skipping")
            return

        # 1. Create a schedule for 10 pcs
        req_sched = ScheduleCreate(
            customer_code="MIL",
            part_number="MIL116",
            scheduled_qty=10,
            unit_price=100.0,
            required_date=None,
            customer_schedule_ref="TEST-PARTIAL-SCHED"
        )
        sched_out = ScheduleMasterService.create_schedule(db, req_sched)
        assert sched_out.scheduled_qty == 10
        assert sched_out.allocated_qty == 0
        assert sched_out.available_qty == 10

        # 2. Create OAR 1 for 5 pcs
        oar_req_1 = OrderIntakeCreate(
            customer_code="MIL",
            customer_name=cust.name,
            part_number="MIL116",
            customer_po="SCHED-PARTIAL-1",
            po_quantity=5,
            delivery_date="2026-11-20",
            source_type="schedule",
            schedule_id=sched_out.id,
            create_wos=False
        )
        res_oar_1 = OperationsService.create_order_intake(db, oar_req_1)
        assert res_oar_1.oar_number is not None

        # Re-fetch schedule
        sched_refetch_1 = ScheduleMasterService._schedule_out(
            db.query(ScheduleMaster).filter(ScheduleMaster.id == sched_out.id).first(),
            db
        )
        assert sched_refetch_1.scheduled_qty == 10
        assert sched_refetch_1.allocated_qty == 5
        assert sched_refetch_1.available_qty == 5
        assert res_oar_1.oar_number in sched_refetch_1.linked_oar_numbers

        # 3. Create OAR 2 for remaining 5 pcs
        oar_req_2 = OrderIntakeCreate(
            customer_code="MIL",
            customer_name=cust.name,
            part_number="MIL116",
            customer_po="SCHED-PARTIAL-2",
            po_quantity=5,
            delivery_date="2026-11-20",
            source_type="schedule",
            schedule_id=sched_out.id,
            create_wos=False
        )
        res_oar_2 = OperationsService.create_order_intake(db, oar_req_2)
        assert res_oar_2.oar_number is not None

        # Re-fetch schedule: now fully allocated (0 available)
        sched_refetch_2 = ScheduleMasterService._schedule_out(
            db.query(ScheduleMaster).filter(ScheduleMaster.id == sched_out.id).first(),
            db
        )
        assert sched_refetch_2.scheduled_qty == 10
        assert sched_refetch_2.allocated_qty == 10
        assert sched_refetch_2.available_qty == 0
        assert res_oar_1.oar_number in sched_refetch_2.linked_oar_numbers
        assert res_oar_2.oar_number in sched_refetch_2.linked_oar_numbers

        # 4. Attempt to create OAR 3 for 1 pc: should fail with 400 Bad Request
        from fastapi import HTTPException
        try:
            oar_req_3 = OrderIntakeCreate(
                customer_code="MIL",
                customer_name=cust.name,
                part_number="MIL116",
                customer_po="SCHED-PARTIAL-OVERRUN",
                po_quantity=1,
                delivery_date="2026-11-20",
                source_type="schedule",
                schedule_id=sched_out.id,
                create_wos=False
            )
            OperationsService.create_order_intake(db, oar_req_3)
            assert False, "Should have raised HTTPException for exceeding available quantity"
        except HTTPException as he:
            assert he.status_code == 400
            assert "exceeds remaining available schedule quantity" in he.detail
            print("Overrun guard verified successfully:", he.detail)

        print("All partial schedule OAR tests PASSED successfully!")
    finally:
        db.rollback()
        db.close()

if __name__ == "__main__":
    test_partial_schedule_oar_generation()
