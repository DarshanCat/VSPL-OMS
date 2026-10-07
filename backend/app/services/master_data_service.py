from datetime import datetime
from typing import List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.order import Customer, Part, Order, next_internal_part_number
from app.models.master_data import POMaster, POLine, ScheduleMaster, POStatus, ScheduleStatus
from app.models.customer_part_mapping import CustomerPartMapping
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.master_data import (
    CustomerCreate, CustomerUpdate, CustomerOut,
    POMasterCreate, POMasterOut, POLineOut,
    ScheduleCreate, ScheduleOut,
    CustomerPartOut, ResolveCustomerPartResponse,
    PartMasterCreate, PartMasterUpdate, PartMasterOut,
    PartMasterKPIs, PartMasterListResponse,
)

_MAX_PO_CREATE_ATTEMPTS = 5


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


def _find_customer_part_mapping(db: Session, customer_id, customer_part_number: str) -> Optional[CustomerPartMapping]:
    norm = customer_part_number.strip()
    return (
        db.query(CustomerPartMapping)
        .filter(
            CustomerPartMapping.customer_id == customer_id,
            func.upper(CustomerPartMapping.customer_part_number) == norm.upper(),
        )
        .first()
    )


def resolve_customer_part(
    db: Session, customer: Customer, customer_part_number: str, create_if_missing: bool
) -> Tuple[Optional[Part], bool, Optional[CustomerPartMapping]]:
    """THE single place a Customer Part Number is ever resolved to -- or, for a
    genuinely new part, used to generate -- the authoritative internal Part.
    Both the live resolve-preview endpoint and PO creation call this exact
    function, so a PO can never land on a different outcome than what was
    already previewed to the operator.

    Returns (part, is_new, mapping):
      - an existing mapping is found        -> (existing part, False, existing mapping)
      - no mapping, create_if_missing=False  -> (None, True, None) -- "would be new"
      - no mapping, create_if_missing=True   -> generates the next internal Part
        number (next_internal_part_number) and creates it plus its mapping
    """
    norm = (customer_part_number or "").strip()
    if not norm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer Part Number is required.")

    existing = _find_customer_part_mapping(db, customer.id, norm)
    if existing:
        part = db.query(Part).filter(Part.id == existing.part_id).first()
        return part, False, existing

    if not create_if_missing:
        return None, True, None

    # Genuinely new -- lock the customer row so concurrent requests for the SAME
    # customer serialize here (the same with_for_update() technique already used
    # throughout this codebase, e.g. production_service.py/dispatch_service.py,
    # for WO/PO-line races). The real unique constraints on Part.part_number and
    # CustomerPartMapping remain the final safety net regardless -- see
    # POMasterService.create_po's retry-on-IntegrityError, which covers dialects
    # (SQLite, used in tests) where with_for_update() is a no-op.
    db.query(Customer).filter(Customer.id == customer.id).with_for_update().first()
    next_number = next_internal_part_number(db, customer.customer_code)
    part = Part(part_number=next_number, description=norm)
    db.add(part)
    db.flush()
    mapping = CustomerPartMapping(
        customer_id=customer.id, part_id=part.id, customer_part_number=norm, status="Active",
    )
    db.add(mapping)
    db.flush()
    return part, True, mapping


def resolve_customer_part_preview(db: Session, customer_code: str, customer_part_number: str) -> ResolveCustomerPartResponse:
    """Read-only preview for the PO UI -- never creates anything. Reuses
    resolve_customer_part() with create_if_missing=False so the preview can
    never diverge from what an actual PO submission would do."""
    customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
    if not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer '{customer_code}' not found.")

    part, is_new, _mapping = resolve_customer_part(db, customer, customer_part_number, create_if_missing=False)
    if part:
        return ResolveCustomerPartResponse(
            customer_part_number=customer_part_number.strip(), resolved=True, part_number=part.part_number,
            is_new=False, message=f"Resolves to existing internal Part {part.part_number}.",
        )
    return ResolveCustomerPartResponse(
        customer_part_number=customer_part_number.strip(), resolved=False, part_number=None,
        is_new=True, message="No existing mapping -- a new internal Part will be generated on submit.",
    )


def list_customer_parts(db: Session, customer_code: str) -> List[CustomerPartOut]:
    """Existing Customer Part Number -> internal Part mappings for one customer,
    used to populate the PO UI's autocomplete suggestions."""
    customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
    if not customer:
        return []
    rows = (
        db.query(CustomerPartMapping, Part)
        .join(Part, CustomerPartMapping.part_id == Part.id)
        .filter(CustomerPartMapping.customer_id == customer.id)
        .order_by(CustomerPartMapping.customer_part_number)
        .all()
    )
    return [
        CustomerPartOut(
            customer_part_number=mapping.customer_part_number, part_number=part.part_number,
            description=part.description, grade=part.grade,
        )
        for mapping, part in rows
    ]


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
    def _line_out(db: Session, line: POLine, customer_id) -> POLineOut:
        allocated = sum(o.po_qty for o in line.orders)
        # Informational only -- POLine's own authoritative FK is part_id; this just
        # surfaces which Customer Part Number (if any) resolved to it, for display.
        mapping = (
            db.query(CustomerPartMapping)
            .filter(CustomerPartMapping.customer_id == customer_id, CustomerPartMapping.part_id == line.part_id)
            .first()
        )
        return POLineOut(
            id=str(line.id), part_number=line.part.part_number,
            customer_part_number=mapping.customer_part_number if mapping else None,
            po_qty=line.po_qty,
            allocated_qty=allocated, available_qty=max(line.po_qty - allocated, 0),
            required_date=line.required_date,
        )

    @staticmethod
    def _po_out(db: Session, po: POMaster) -> POMasterOut:
        return POMasterOut(
            id=str(po.id), po_number=po.po_number, customer_code=po.customer.customer_code,
            customer_name=po.customer.name, po_date=po.po_date, validity_date=po.validity_date,
            status=po.status.value,
            lines=[POMasterService._line_out(db, l, po.customer_id) for l in po.lines],
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
        return [POMasterService._po_out(db, p) for p in rows]

    @staticmethod
    def create_po(db: Session, req: POMasterCreate, current_user: Optional[User] = None) -> POMasterOut:
        # Retries the WHOLE operation from scratch on a concurrent-insert collision
        # (e.g. two requests for the same customer both generating the same "next"
        # internal Part Number) -- never a partial/half-applied PO. Each attempt
        # starts from a clean rollback, so the retry's next_internal_part_number()
        # call sees the winning attempt's committed row and correctly moves past it.
        for attempt in range(_MAX_PO_CREATE_ATTEMPTS):
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
                if not line_req.customer_part_number and not line_req.part_number:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Either customer_part_number or part_number is required for each PO line.",
                    )
                if line_req.customer_part_number:
                    # The authoritative path -- the operator never supplies the
                    # internal Part Number; it is resolved or (for a genuinely new
                    # part) generated here, via the one shared resolution function.
                    part, _is_new, _mapping = resolve_customer_part(
                        db, customer, line_req.customer_part_number, create_if_missing=True,
                    )
                else:
                    # Legacy/direct-API path -- an existing caller supplying the
                    # literal internal part_number still works exactly as before.
                    part = _get_part(db, line_req.part_number)
                db.add(POLine(po_id=po.id, part_id=part.id, po_qty=line_req.po_qty, required_date=line_req.required_date))

            _audit(db, current_user, "PO_CREATED", "POMaster", str(po.id), details=f"po_number={req.po_number}, lines={len(req.lines)}")

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if attempt == _MAX_PO_CREATE_ATTEMPTS - 1:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Could not create PO due to a concurrent update -- please retry.",
                    )
                continue

            db.refresh(po)
            return POMasterService._po_out(db, po)


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


class PartMasterService:
    @staticmethod
    def _part_out(part: Part, mapping: CustomerPartMapping, customer: Customer) -> PartMasterOut:
        return PartMasterOut(
            id=str(part.id),
            part_number=part.part_number,
            customer_id=str(customer.id),
            customer_code=customer.customer_code,
            customer_name=customer.name,
            customer_part_number=mapping.customer_part_number,
            status=mapping.status,
            description=part.description,
            created_at=mapping.created_at,
        )

    @staticmethod
    def list_parts(
        db: Session,
        customer_code: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 50,
    ) -> PartMasterListResponse:
        query = (
            db.query(CustomerPartMapping, Part, Customer)
            .join(Part, CustomerPartMapping.part_id == Part.id)
            .join(Customer, CustomerPartMapping.customer_id == Customer.id)
        )
        if customer_code:
            query = query.filter(Customer.customer_code == customer_code.strip().upper())
        if status_filter and status_filter.strip().upper() != "ALL":
            query = query.filter(func.lower(CustomerPartMapping.status) == status_filter.strip().lower())
        if search and search.strip():
            term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    CustomerPartMapping.customer_part_number.ilike(term),
                    Part.part_number.ilike(term),
                    Customer.name.ilike(term),
                    Customer.customer_code.ilike(term),
                )
            )
        total = query.count()
        page = max(page, 1)
        limit = max(min(limit, 500), 1)
        offset = (page - 1) * limit
        rows = query.order_by(Customer.customer_code, Part.part_number).offset(offset).limit(limit).all()
        items = [PartMasterService._part_out(part, mapping, cust) for mapping, part, cust in rows]
        return PartMasterListResponse(items=items, total=total, page=page, limit=limit)

    @staticmethod
    def get_kpis(db: Session) -> PartMasterKPIs:
        total_parts = db.query(CustomerPartMapping).count()
        active_parts = (
            db.query(CustomerPartMapping)
            .filter(func.lower(CustomerPartMapping.status) == "active")
            .count()
        )
        total_customers = db.query(CustomerPartMapping.customer_id).distinct().count()

        now = datetime.now()
        first_day_of_month = datetime(now.year, now.month, 1)
        new_this_month = (
            db.query(CustomerPartMapping)
            .filter(CustomerPartMapping.created_at >= first_day_of_month)
            .count()
        )
        return PartMasterKPIs(
            total_parts=total_parts,
            active_parts=active_parts,
            total_customers=total_customers,
            new_parts_this_month=new_this_month,
        )

    @staticmethod
    def get_part(db: Session, part_id: str) -> PartMasterOut:
        row = (
            db.query(CustomerPartMapping, Part, Customer)
            .join(Part, CustomerPartMapping.part_id == Part.id)
            .join(Customer, CustomerPartMapping.customer_id == Customer.id)
            .filter(Part.id == part_id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found in the Part Master.")
        mapping, part, cust = row
        return PartMasterService._part_out(part, mapping, cust)

    @staticmethod
    def create_part(
        db: Session, req: PartMasterCreate, current_user: Optional[User] = None
    ) -> PartMasterOut:
        raw_cpn = (req.customer_part_number or "").strip()
        if not raw_cpn:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer Part Number is required.")

        cust_code = (req.customer_code or "").strip().upper()
        if not cust_code:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer code is required.")

        customer = db.query(Customer).filter(Customer.customer_code == cust_code).first()
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer '{req.customer_code}' not found. Please create the customer first before adding parts.",
            )

        for attempt in range(_MAX_PO_CREATE_ATTEMPTS):
            # 1. Lock the Customer row to serialize concurrent part creations for the same customer
            db.query(Customer).filter(Customer.id == customer.id).with_for_update().first()

            # 2. Check exact (customer_id, customer_part_number)
            existing_mapping = (
                db.query(CustomerPartMapping)
                .filter(
                    CustomerPartMapping.customer_id == customer.id,
                    CustomerPartMapping.customer_part_number == raw_cpn,
                )
                .first()
            )
            if existing_mapping:
                existing_part = db.query(Part).filter(Part.id == existing_mapping.part_id).first()
                part_num = existing_part.part_number if existing_part else "existing part"
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Customer Part Number '{raw_cpn}' already exists for customer '{customer.customer_code}' (mapped to {part_num}).",
                )

            # 3. Generate the next internal code using authoritative next_internal_part_number()
            next_code = next_internal_part_number(db, customer.customer_code)

            # 4. Create Part
            part = Part(
                part_number=next_code,
                description=req.description or raw_cpn,
            )
            db.add(part)
            db.flush()

            # 5. Create CustomerPartMapping
            mapping = CustomerPartMapping(
                customer_id=customer.id,
                part_id=part.id,
                customer_part_number=raw_cpn,
                status=req.status if req.status else "Active",
            )
            db.add(mapping)
            db.flush()

            _audit(
                db, current_user, "PART_CREATED", "Part", str(part.id),
                details=f"part_number={part.part_number}, customer={customer.customer_code}, customer_part_number={raw_cpn}"
            )

            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                if attempt == _MAX_PO_CREATE_ATTEMPTS - 1:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Could not create part due to a concurrent update -- please retry.",
                    )
                continue

            db.refresh(part)
            db.refresh(mapping)
            return PartMasterService._part_out(part, mapping, customer)

    @staticmethod
    def update_part(
        db: Session, part_id: str, req: PartMasterUpdate, current_user: Optional[User] = None
    ) -> PartMasterOut:
        row = (
            db.query(CustomerPartMapping, Part, Customer)
            .join(Part, CustomerPartMapping.part_id == Part.id)
            .join(Customer, CustomerPartMapping.customer_id == Customer.id)
            .filter(Part.id == part_id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Part not found in the Part Master.")
        mapping, part, customer = row

        # Lock customer row
        db.query(Customer).filter(Customer.id == customer.id).with_for_update().first()

        if req.customer_part_number is not None:
            new_cpn = req.customer_part_number.strip()
            if not new_cpn:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer Part Number cannot be blank.")
            if new_cpn != mapping.customer_part_number:
                # Check uniqueness under this customer
                existing = (
                    db.query(CustomerPartMapping)
                    .filter(
                        CustomerPartMapping.customer_id == customer.id,
                        CustomerPartMapping.customer_part_number == new_cpn,
                        CustomerPartMapping.id != mapping.id,
                    )
                    .first()
                )
                if existing:
                    existing_part = db.query(Part).filter(Part.id == existing.part_id).first()
                    part_num = existing_part.part_number if existing_part else "existing part"
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Customer Part Number '{new_cpn}' already exists for customer '{customer.customer_code}' (mapped to {part_num}).",
                    )
                mapping.customer_part_number = new_cpn

        if req.status is not None:
            clean_status = req.status.strip()
            if clean_status:
                mapping.status = clean_status

        if req.description is not None:
            part.description = req.description

        _audit(
            db, current_user, "PART_UPDATED", "Part", str(part.id),
            details=f"part_number={part.part_number}, customer={customer.customer_code}"
        )
        db.commit()
        db.refresh(part)
        db.refresh(mapping)
        return PartMasterService._part_out(part, mapping, customer)

