from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.order import Customer, Part, Order
from app.models.master_data import POMaster, POLine, ScheduleMaster, POStatus, ScheduleStatus
from app.models.machine import Machine
from app.models.shift import Shift
from app.models.operator import Operator
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.master_data import (
    CustomerCreate, CustomerUpdate, CustomerOut,
    POMasterCreate, POMasterOut, POLineOut,
    ScheduleCreate, ScheduleOut,
    MachineCreate, MachineUpdate, MachineOut,
    ShiftCreate, ShiftUpdate, ShiftOut,
    OperatorCreate, OperatorUpdate, OperatorOut,
)


def _audit(db: Session, actor: Optional[User], action: str, entity: str, entity_id: str, details: str = "") -> None:
    db.add(AuditLog(
        user_id=actor.id if actor else None,
        user_name=actor.full_name if actor else "System",
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details,
    ))


def _get_or_create_customer(db: Session, customer_code: str, customer_name: Optional[str] = None) -> Customer:
    customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
    if not customer:
        if not customer_name:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer '{customer_code}' not found.")
        customer = Customer(customer_code=customer_code.strip().upper(), name=customer_name.strip())
        db.add(customer)
        db.flush()
    return customer


def _get_part(db: Session, part_number: str) -> Part:
    part = db.query(Part).filter(Part.part_number == part_number.strip().upper()).first()
    if not part:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part '{part_number}' not found in the Part Master.")
    return part


def _customer_out(c: Customer) -> CustomerOut:
    return CustomerOut(
        id=str(c.id), customer_code=c.customer_code, name=c.name,
        address=c.address, gst=c.gst, contact_person=c.contact_person,
        email=c.email, phone=c.phone, is_active=c.is_active,
    )


class CustomerMasterService:
    @staticmethod
    def list_customers(db: Session) -> List[CustomerOut]:
        rows = db.query(Customer).order_by(Customer.customer_code).all()
        return [_customer_out(c) for c in rows]

    @staticmethod
    def create_customer(db: Session, req: CustomerCreate, current_user: Optional[User] = None) -> CustomerOut:
        existing = db.query(Customer).filter(Customer.customer_code == req.customer_code.strip().upper()).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Customer code '{req.customer_code}' already exists.")
        customer = Customer(
            customer_code=req.customer_code.strip().upper(),
            name=req.name.strip(),
            address=req.address, gst=req.gst, contact_person=req.contact_person,
            email=req.email, phone=req.phone, is_active=req.is_active,
        )
        db.add(customer)
        db.flush()
        _audit(db, current_user, "CUSTOMER_CREATED", "Customer", str(customer.id), details=req.customer_code)
        db.commit()
        db.refresh(customer)
        return _customer_out(customer)

    @staticmethod
    def update_customer(db: Session, req: CustomerUpdate, current_user: Optional[User] = None) -> CustomerOut:
        customer = db.query(Customer).filter(Customer.id == req.id).first()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found.")
        for field in ("address", "gst", "contact_person", "email", "phone", "is_active"):
            value = getattr(req, field)
            if value is not None:
                setattr(customer, field, value)
        _audit(db, current_user, "CUSTOMER_UPDATED", "Customer", str(customer.id))
        db.commit()
        db.refresh(customer)
        return _customer_out(customer)


class POMasterService:
    @staticmethod
    def _line_out(line: POLine) -> POLineOut:
        allocated = sum(o.po_qty for o in line.orders)
        return POLineOut(
            id=str(line.id), part_number=line.part.part_number, po_qty=line.po_qty,
            allocated_qty=allocated, available_qty=max(line.po_qty - allocated, 0),
            required_date=line.required_date,
        )

    @staticmethod
    def _po_out(po: POMaster) -> POMasterOut:
        return POMasterOut(
            id=str(po.id), po_number=po.po_number, customer_code=po.customer.customer_code,
            customer_name=po.customer.name, po_date=po.po_date, validity_date=po.validity_date,
            status=po.status.value, lines=[POMasterService._line_out(l) for l in po.lines],
        )

    @staticmethod
    def list_pos(db: Session, customer_code: Optional[str] = None) -> List[POMasterOut]:
        query = db.query(POMaster)
        if customer_code:
            customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
            if not customer:
                return []
            query = query.filter(POMaster.customer_id == customer.id)
        rows = query.order_by(POMaster.created_at.desc()).all()
        return [POMasterService._po_out(p) for p in rows]

    @staticmethod
    def create_po(db: Session, req: POMasterCreate, current_user: Optional[User] = None) -> POMasterOut:
        if db.query(POMaster).filter(POMaster.po_number == req.po_number.strip()).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"PO number '{req.po_number}' already exists.")

        customer = db.query(Customer).filter(Customer.customer_code == req.customer_code.strip().upper()).first()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer '{req.customer_code}' not found.")

        po = POMaster(
            po_number=req.po_number.strip(), customer_id=customer.id,
            po_date=req.po_date, validity_date=req.validity_date,
            status=POStatus.OPEN,
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "System",
        )
        db.add(po)
        db.flush()

        for line_req in req.lines:
            part = _get_part(db, line_req.part_number)
            db.add(POLine(po_id=po.id, part_id=part.id, po_qty=line_req.po_qty, required_date=line_req.required_date))

        _audit(db, current_user, "PO_CREATED", "POMaster", str(po.id), details=f"po_number={req.po_number}, lines={len(req.lines)}")
        db.commit()
        db.refresh(po)
        return POMasterService._po_out(po)


class ScheduleMasterService:
    @staticmethod
    def _schedule_out(s: ScheduleMaster) -> ScheduleOut:
        linked_order = s.orders[0] if s.orders else None
        return ScheduleOut(
            id=str(s.id), schedule_number=s.schedule_number, customer_code=s.customer.customer_code,
            customer_name=s.customer.name, part_number=s.part.part_number, scheduled_qty=s.scheduled_qty,
            required_date=s.required_date, customer_schedule_ref=s.customer_schedule_ref,
            po_status=s.po_status.value, linked_oar_number=linked_order.oar_number if linked_order else None,
        )

    @staticmethod
    def list_schedules(db: Session, customer_code: Optional[str] = None) -> List[ScheduleOut]:
        query = db.query(ScheduleMaster)
        if customer_code:
            customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
            if not customer:
                return []
            query = query.filter(ScheduleMaster.customer_id == customer.id)
        rows = query.order_by(ScheduleMaster.created_at.desc()).all()
        return [ScheduleMasterService._schedule_out(s) for s in rows]

    @staticmethod
    def create_schedule(db: Session, req: ScheduleCreate, current_user: Optional[User] = None) -> ScheduleOut:
        customer = db.query(Customer).filter(Customer.customer_code == req.customer_code.strip().upper()).first()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer '{req.customer_code}' not found.")
        part = _get_part(db, req.part_number)

        count = db.query(ScheduleMaster).count()
        schedule_number = f"SCH-{count + 1:05d}"

        schedule = ScheduleMaster(
            schedule_number=schedule_number, customer_id=customer.id, part_id=part.id,
            scheduled_qty=req.scheduled_qty, required_date=req.required_date,
            customer_schedule_ref=req.customer_schedule_ref, po_status=ScheduleStatus.SCHEDULED,
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "System",
        )
        db.add(schedule)
        _audit(db, current_user, "SCHEDULE_CREATED", "ScheduleMaster", schedule_number, details=f"qty={req.scheduled_qty}")
        db.commit()
        db.refresh(schedule)
        return ScheduleMasterService._schedule_out(schedule)


def _machine_out(m: Machine) -> MachineOut:
    return MachineOut(id=str(m.id), machine_code=m.machine_code, machine_name=m.machine_name,
                       department=m.department, is_active=m.is_active)


class MachineMasterService:
    @staticmethod
    def list_machines(db: Session) -> List[MachineOut]:
        rows = db.query(Machine).order_by(Machine.machine_code).all()
        return [_machine_out(m) for m in rows]

    @staticmethod
    def create_machine(db: Session, req: MachineCreate, current_user: Optional[User] = None) -> MachineOut:
        code = req.machine_code.strip().upper()
        if db.query(Machine).filter(Machine.machine_code == code).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Machine code '{code}' already exists.")
        machine = Machine(
            machine_code=code, machine_name=req.machine_name.strip(), department=req.department,
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "System",
        )
        db.add(machine)
        db.flush()
        _audit(db, current_user, "MACHINE_CREATED", "Machine", str(machine.id), details=code)
        db.commit()
        db.refresh(machine)
        return _machine_out(machine)

    @staticmethod
    def update_machine(db: Session, req: MachineUpdate, current_user: Optional[User] = None) -> MachineOut:
        machine = db.query(Machine).filter(Machine.id == req.id).first()
        if not machine:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Machine not found.")
        if req.machine_name is not None:
            machine.machine_name = req.machine_name.strip()
        if req.department is not None:
            machine.department = req.department
        if req.is_active is not None:
            # Never physically deleted -- historical production/movement transactions
            # keep resolving by machine_code regardless of active status.
            machine.is_active = req.is_active
        _audit(db, current_user, "MACHINE_UPDATED", "Machine", str(machine.id))
        db.commit()
        db.refresh(machine)
        return _machine_out(machine)


def _shift_out(s: Shift) -> ShiftOut:
    return ShiftOut(id=str(s.id), shift_code=s.shift_code, shift_name=s.shift_name,
                     start_time=s.start_time, end_time=s.end_time, is_active=s.is_active)


class ShiftMasterService:
    @staticmethod
    def list_shifts(db: Session) -> List[ShiftOut]:
        rows = db.query(Shift).order_by(Shift.shift_code).all()
        return [_shift_out(s) for s in rows]

    @staticmethod
    def create_shift(db: Session, req: ShiftCreate, current_user: Optional[User] = None) -> ShiftOut:
        code = req.shift_code.strip().upper()
        if db.query(Shift).filter(Shift.shift_code == code).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Shift code '{code}' already exists.")
        shift = Shift(
            shift_code=code, shift_name=req.shift_name.strip(),
            start_time=req.start_time, end_time=req.end_time,
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "System",
        )
        db.add(shift)
        db.flush()
        _audit(db, current_user, "SHIFT_CREATED", "Shift", str(shift.id), details=code)
        db.commit()
        db.refresh(shift)
        return _shift_out(shift)

    @staticmethod
    def update_shift(db: Session, req: ShiftUpdate, current_user: Optional[User] = None) -> ShiftOut:
        shift = db.query(Shift).filter(Shift.id == req.id).first()
        if not shift:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found.")
        if req.shift_name is not None:
            shift.shift_name = req.shift_name.strip()
        if req.start_time is not None:
            shift.start_time = req.start_time
        if req.end_time is not None:
            shift.end_time = req.end_time
        if req.is_active is not None:
            shift.is_active = req.is_active
        _audit(db, current_user, "SHIFT_UPDATED", "Shift", str(shift.id))
        db.commit()
        db.refresh(shift)
        return _shift_out(shift)


def _operator_out(o: Operator) -> OperatorOut:
    return OperatorOut(id=str(o.id), user_id=str(o.user_id) if o.user_id else None,
                        employee_code=o.employee_code, display_name=o.display_name, is_active=o.is_active)


class OperatorMasterService:
    @staticmethod
    def list_operators(db: Session) -> List[OperatorOut]:
        rows = db.query(Operator).order_by(Operator.display_name).all()
        return [_operator_out(o) for o in rows]

    @staticmethod
    def create_operator(db: Session, req: OperatorCreate, current_user: Optional[User] = None) -> OperatorOut:
        # Never create a duplicate employee identity if the authenticated User system
        # already contains this person -- link to it instead of copying.
        user_ref = None
        if req.user_id:
            user_ref = db.query(User).filter(User.id == req.user_id).first()
            if not user_ref:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{req.user_id}' not found.")
        code = req.employee_code.strip().upper() if req.employee_code else None
        if code and db.query(Operator).filter(Operator.employee_code == code).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Operator employee code '{code}' already exists.")

        operator = Operator(
            user_id=user_ref.id if user_ref else None, employee_code=code,
            display_name=req.display_name.strip(),
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "System",
        )
        db.add(operator)
        db.flush()
        _audit(db, current_user, "OPERATOR_CREATED", "Operator", str(operator.id),
               details=f"user_id={req.user_id or 'None'}")
        db.commit()
        db.refresh(operator)
        return _operator_out(operator)

    @staticmethod
    def update_operator(db: Session, req: OperatorUpdate, current_user: Optional[User] = None) -> OperatorOut:
        operator = db.query(Operator).filter(Operator.id == req.id).first()
        if not operator:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found.")
        if req.employee_code is not None:
            code = req.employee_code.strip().upper() if req.employee_code else None
            if code and db.query(Operator).filter(Operator.employee_code == code, Operator.id != operator.id).first():
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Operator employee code '{code}' already exists.")
            operator.employee_code = code
        if req.display_name is not None:
            operator.display_name = req.display_name.strip()
        if req.is_active is not None:
            operator.is_active = req.is_active
        _audit(db, current_user, "OPERATOR_UPDATED", "Operator", str(operator.id))
        db.commit()
        db.refresh(operator)
        return _operator_out(operator)
