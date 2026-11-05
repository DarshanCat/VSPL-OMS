import sys
sys.path.append("backend")
import os
import pytest
from app.core.database import SessionLocal
from app.models.order import Part, Customer
from app.models.master_data import ScheduleMaster
from app.services.master_data_service import ScheduleMasterService
from app.schemas.master_data import ScheduleCreate, ScheduleUpdate

def test_schedule_creation_with_internal_and_customer_parts():
    db = SessionLocal()
    try:
        # Ensure MIL customer exists
        cust = db.query(Customer).filter(Customer.customer_code == "MIL").first()
        if not cust:
            print("MIL not found in local db, skipping")
            return

        # 1. Test creation with internal part number alone
        req1 = ScheduleCreate(
            customer_code="MIL",
            part_number="MIL116",
            scheduled_qty=10,
            unit_price=500.0,
            required_date=None,
            customer_schedule_ref="TEST-INTERNAL"
        )
        res1 = ScheduleMasterService.create_schedule(db, req1)
        assert res1.schedule_number.startswith("SCH-")
        assert res1.part_number == "MIL116"

        # 2. Test creation with customer part number alone
        req2 = ScheduleCreate(
            customer_code="MIL",
            part_number=None,
            customer_part_number="12052165",
            scheduled_qty=15,
            unit_price=500.0,
            required_date=None,
            customer_schedule_ref="TEST-CUSTOMER"
        )
        res2 = ScheduleMasterService.create_schedule(db, req2)
        assert res2.schedule_number.startswith("SCH-")
        assert res2.part_number == "MIL116"
        assert res2.schedule_number != res1.schedule_number

        # 3. Test creation with both internal and customer parts
        req3 = ScheduleCreate(
            customer_code="MIL",
            part_number="MIL116",
            customer_part_number="12052165",
            scheduled_qty=20,
            unit_price=500.0,
            required_date=None,
            customer_schedule_ref="TEST-BOTH"
        )
        res3 = ScheduleMasterService.create_schedule(db, req3)
        assert res3.part_number == "MIL116"

        print("Schedule test passed successfully!")
    finally:
        db.rollback()
        db.close()

if __name__ == "__main__":
    test_schedule_creation_with_internal_and_customer_parts()
