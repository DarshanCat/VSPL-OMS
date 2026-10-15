from datetime import datetime
from typing import List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from app.models.order import Customer, Part, Order, next_internal_part_number
from app.models.master_data import POMaster, POLine, ScheduleMaster, POStatus, ScheduleStatus
from app.models.customer_part_mapping import CustomerPartMapping
from app.models.machine import Machine
from app.models.shift import Shift
from app.models.operator import Operator
from app.models.audit import AuditLog
from app.models.user import User
from app.services.work_order_service import compute_po_coverage_status, compute_wo_release_status
from app.schemas.master_data import (
    CustomerCreate, CustomerUpdate, CustomerOut,
    POMasterCreate, POMasterUpdate, POMasterOut, POLineOut, POLineUpdate,
    POLineOrderSummary, POLineWorkOrderSummary,
    ScheduleCreate, ScheduleOut,
    CustomerPartOut, ResolveCustomerPartResponse,
    PartMasterCreate, PartMasterUpdate, PartMasterOut,
    PartMasterKPIs, PartMasterListResponse,
    MachineCreate, MachineUpdate, MachineOut,
    ShiftCreate, ShiftUpdate, ShiftOut,
    OperatorCreate, OperatorUpdate, OperatorOut,
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


def _customer_out(c: Customer) -> CustomerOut:
    return CustomerOut(
        id=str(c.id), customer_code=c.customer_code, name=c.name,
        address=c.address, gst=c.gst, contact_person=c.contact_person,
        email=c.email, phone=c.phone, is_active=c.is_active,
    )


def _find_customer_part_mapping(db: Session, customer_id, customer_part_number: str) -> Optional[CustomerPartMapping]:
    norm = customer_part_number.strip()
    m = (
        db.query(CustomerPartMapping)
        .filter(
            CustomerPartMapping.customer_id == customer_id,
            func.upper(CustomerPartMapping.customer_part_number) == norm.upper(),
        )
        .first()
    )
    if m:
        return m

    # Also check CustomerPartCrossReference
    try:
        from app.models.customer_part_cross_reference import CustomerPartCrossReference
        xref = (
            db.query(CustomerPartCrossReference)
            .filter(
                CustomerPartCrossReference.customer_id == customer_id,
                func.upper(CustomerPartCrossReference.customer_part_no) == norm.upper(),
                CustomerPartCrossReference.is_active == True,
            )
            .first()
        )
        if xref:
            part = db.query(Part).filter(Part.id == xref.part_id).first()
            if part:
                mapping = db.query(CustomerPartMapping).filter(
                    CustomerPartMapping.customer_id == customer_id,
                    CustomerPartMapping.part_id == part.id,
                ).first()
                if not mapping:
                    mapping = CustomerPartMapping(
                        customer_id=customer_id,
                        part_id=part.id,
                        customer_part_number=norm,
                        status="Active",
                    )
                    db.add(mapping)
                    db.flush()
                return mapping
    except Exception:
        pass
    return None


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
      - matches existing Part code or desc  -> (existing part, False, created/existing mapping)
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

    # Check if a Part already exists whose part_number or description matches norm
    existing_part = db.query(Part).filter(
        or_(
            func.upper(Part.part_number) == norm.upper(),
            func.upper(Part.description) == norm.upper(),
        )
    ).first()
    if existing_part:
        if create_if_missing:
            mapping = CustomerPartMapping(
                customer_id=customer.id, part_id=existing_part.id, customer_part_number=norm, status="Active",
            )
            db.add(mapping)
            db.flush()
            return existing_part, False, mapping
        return existing_part, False, None

    if not create_if_missing:
        return None, True, None

    db.query(Customer).filter(Customer.id == customer.id).with_for_update().first()
    next_number = next_internal_part_number(db, customer.customer_code)
    part = Part(part_number=next_number, description=norm)
    db.add(part)
    db.flush()
    mapping = CustomerPartMapping(
        customer_id=customer.id, part_id=part.id, customer_part_number=norm, status="Active",
    )
    db.add(mapping)
    try:
        from app.models.customer_part_cross_reference import CustomerPartCrossReference
        xref = CustomerPartCrossReference(
            customer_id=customer.id,
            customer_part_no=norm,
            part_id=part.id,
            source="PO Creation",
            is_active=True,
        )
        db.add(xref)
    except Exception:
        pass
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
    if part is not None:
        return ResolveCustomerPartResponse(
            customer_part_number=customer_part_number.strip(),
            resolved=True,
            part_number=part.part_number,
            is_new=False,
            message=f"Matches existing part {part.part_number}",
        )
    return ResolveCustomerPartResponse(
        customer_part_number=customer_part_number.strip(),
        resolved=True,
        part_number=None,
        is_new=True,
        message=f"New part -- internal code will be auto-generated on PO save (e.g. {customer.customer_code}#)",
    )


def list_customer_parts(db: Session, customer_code: str) -> List[CustomerPartOut]:
    customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
    if not customer:
        return []
    rows = (
        db.query(CustomerPartMapping, Part)
        .join(Part, CustomerPartMapping.part_id == Part.id)
        .filter(
            CustomerPartMapping.customer_id == customer.id,
            CustomerPartMapping.status == "Active",
        )
        .order_by(CustomerPartMapping.customer_part_number)
        .all()
    )
    return [
        CustomerPartOut(
            customer_part_number=m.customer_part_number,
            part_number=p.part_number,
            description=p.description,
            grade=p.grade,
        )
        for m, p in rows
    ]


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
        orders_summary = [
            POLineOrderSummary(
                oar_id=str(o.id), oar_number=o.oar_number, order_status=o.status.value,
                po_coverage_status=compute_po_coverage_status(o),
                work_orders=[
                    POLineWorkOrderSummary(
                        wo_id=str(wo.id), wo_number=wo.wo_number, wo_status=wo.status.value,
                        release_status=compute_wo_release_status(wo),
                    )
                    for wo in o.work_orders
                ],
            )
            for o in line.orders
        ]
        return POLineOut(
            id=str(line.id), part_number=line.part.part_number,
            customer_part_number=line.customer_part_number if hasattr(line, "customer_part_number") else None,
            po_qty=line.po_qty, allocated_qty=allocated, available_qty=max(line.po_qty - allocated, 0),
            required_date=line.required_date, orders=orders_summary,
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
        # Auto-link any unlinked legacy orders where customer_po and part_id match open PO lines
        unlinked = (
            db.query(Order)
            .filter(Order.po_line_id.is_(None), Order.customer_po.isnot(None))
            .all()
        )
        if unlinked:
            for ord in unlinked:
                cand_line = (
                    db.query(POLine)
                    .join(POMaster, POLine.po_id == POMaster.id)
                    .filter(
                        POMaster.customer_id == ord.customer_id,
                        func.lower(POMaster.po_number) == func.lower(ord.customer_po.strip()),
                        POLine.part_id == ord.part_id,
                    )
                    .first()
                )
                if cand_line:
                    ord.po_line_id = cand_line.id
            try:
                db.flush()
            except Exception:
                pass

        query = db.query(POMaster).options(
            selectinload(POMaster.customer),
            selectinload(POMaster.lines).selectinload(POLine.part),
            selectinload(POMaster.lines).selectinload(POLine.orders).selectinload(Order.work_orders),
            selectinload(POMaster.lines).selectinload(POLine.orders).selectinload(Order.customer),
            selectinload(POMaster.lines).selectinload(POLine.orders).selectinload(Order.po_line).selectinload(POLine.po),
        )
        if customer_code:
            customer = db.query(Customer).filter(Customer.customer_code == customer_code.strip().upper()).first()
            if not customer:
                return []
            query = query.filter(POMaster.customer_id == customer.id)
        rows = query.order_by(POMaster.created_at.desc()).all()
        return [POMasterService._po_out(p) for p in rows]

    @staticmethod
    def create_po(db: Session, req: POMasterCreate, current_user: Optional[User] = None) -> POMasterOut:
        customer = db.query(Customer).filter(Customer.customer_code == req.customer_code.strip().upper()).first()
        if not customer:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Customer '{req.customer_code}' not found.")

        # Scoped uniqueness per customer
        if db.query(POMaster).filter(
            POMaster.po_number == req.po_number.strip(),
            POMaster.customer_id == customer.id
        ).first():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"PO number '{req.po_number}' already exists for this customer.")

        for attempt in range(_MAX_PO_CREATE_ATTEMPTS):
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
                cust_pn = (line_req.customer_part_number or "").strip()
                pn = (line_req.part_number or "").strip()
                if cust_pn:
                    part, _is_new, _mapping = resolve_customer_part(
                        db, customer, cust_pn, create_if_missing=True
                    )
                elif pn:
                    clean_pn = pn.upper()
                    existing_part = db.query(Part).filter(Part.part_number == clean_pn).first()
                    if existing_part:
                        part = existing_part
                        mapping = _find_customer_part_mapping(db, customer.id, pn)
                        if mapping:
                            cust_pn = mapping.customer_part_number
                    else:
                        # User entered customer part number in the part_number field
                        part, _is_new, _mapping = resolve_customer_part(
                            db, customer, pn, create_if_missing=True
                        )
                        cust_pn = pn
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Each PO line must supply either a Customer Part Number or an Internal Part Number.",
                    )
                db.add(POLine(
                    po_id=po.id,
                    part_id=part.id,
                    customer_part_number=cust_pn or None,
                    po_qty=line_req.po_qty,
                    required_date=line_req.required_date,
                ))

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
            return POMasterService._po_out(po)

    @staticmethod
    def get_po(db: Session, po_id: str) -> POMasterOut:
        po = db.query(POMaster).options(
            selectinload(POMaster.customer),
            selectinload(POMaster.lines).selectinload(POLine.part),
            selectinload(POMaster.lines).selectinload(POLine.orders).selectinload(Order.work_orders),
            selectinload(POMaster.lines).selectinload(POLine.orders).selectinload(Order.customer),
            selectinload(POMaster.lines).selectinload(POLine.orders).selectinload(Order.po_line).selectinload(POLine.po),
        ).filter(POMaster.id == po_id).first()
        if not po:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found.")
        return POMasterService._po_out(po)

    @staticmethod
    def update_po(db: Session, po_id: str, req: POMasterUpdate, current_user: Optional[User] = None) -> POMasterOut:
        po = db.query(POMaster).filter(POMaster.id == po_id).with_for_update().first()
        if not po:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PO not found.")

        # Lock all lines for this PO to prevent concurrent allocation races
        db.query(POLine).filter(POLine.po_id == po.id).with_for_update().all()

        # 1. Customer immutability check
        if req.customer_code is not None:
            req_cust = req.customer_code.strip().upper()
            if req_cust != po.customer.customer_code.strip().upper():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Customer association cannot be changed once a PO is created.",
                )

        changes = []

        # 2. PO number update (conditional on downstream references and scoped uniqueness)
        if req.po_number is not None:
            new_po_num = req.po_number.strip()
            if not new_po_num:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PO number cannot be empty.")
            if new_po_num != po.po_number:
                conflict = db.query(POMaster).filter(
                    POMaster.customer_id == po.customer_id,
                    POMaster.po_number == new_po_num,
                    POMaster.id != po.id,
                ).first()
                if conflict:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"PO number '{new_po_num}' already exists for this customer.",
                    )
                total_linked_orders = sum(len(line.orders) for line in po.lines)
                if total_linked_orders > 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"PO number cannot be changed because {total_linked_orders} order(s) (OARs) are already linked to this PO.",
                    )
                changes.append(f"po_number: {po.po_number} -> {new_po_num}")
                po.po_number = new_po_num

        # 3. Header dates
        if req.po_date is not None:
            if po.po_date != req.po_date:
                changes.append(f"po_date: {po.po_date} -> {req.po_date}")
                po.po_date = req.po_date

        if req.validity_date is not None:
            if po.validity_date != req.validity_date:
                changes.append(f"validity_date: {po.validity_date} -> {req.validity_date}")
                po.validity_date = req.validity_date

        # 4. Status
        if req.status is not None:
            new_status_str = req.status.strip().lower()
            try:
                new_status = POStatus(new_status_str)
            except ValueError:
                valid_statuses = ", ".join([s.value for s in POStatus])
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid PO status '{req.status}'. Valid statuses are: {valid_statuses}.",
                )
            if new_status == POStatus.CANCELLED:
                total_allocated = sum(sum(o.po_qty for o in line.orders) for line in po.lines)
                if total_allocated > 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot cancel PO because it has {total_allocated} allocated quantity across linked orders (OARs).",
                    )
            if po.status != new_status:
                changes.append(f"status: {po.status.value} -> {new_status.value}")
                po.status = new_status

        # 5. PO Lines
        if req.lines is not None:
            if len(req.lines) == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="PO must contain at least one line.",
                )

            existing_lines_by_id = {str(l.id): l for l in po.lines}
            payload_line_ids = set()

            for line_req in req.lines:
                if line_req.po_qty <= 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="PO quantity must be greater than zero.",
                    )

                if line_req.id:
                    line_id_str = str(line_req.id)
                    if line_id_str not in existing_lines_by_id:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"PO line '{line_id_str}' not found on this PO.",
                        )
                    line = existing_lines_by_id[line_id_str]
                    payload_line_ids.add(line_id_str)

                    allocated = sum(o.po_qty for o in line.orders)
                    if line_req.po_qty < allocated:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                f"PO line quantity ({line_req.po_qty}) for part '{line.part.part_number}' "
                                f"cannot be reduced below the already allocated quantity ({allocated})."
                            ),
                        )

                    # Part change check on existing line
                    if line_req.customer_part_number or line_req.part_number:
                        cust_pn = (line_req.customer_part_number or "").strip()
                        pn = (line_req.part_number or "").strip()
                        if cust_pn:
                            part, _, _ = resolve_customer_part(
                                db, po.customer, cust_pn, create_if_missing=True
                            )
                        else:
                            clean_pn = pn.upper()
                            existing_part = db.query(Part).filter(Part.part_number == clean_pn).first()
                            if existing_part:
                                part = existing_part
                                mapping = _find_customer_part_mapping(db, po.customer.id, pn)
                                if mapping:
                                    cust_pn = mapping.customer_part_number
                            else:
                                part, _, _ = resolve_customer_part(
                                    db, po.customer, pn, create_if_missing=True
                                )
                                cust_pn = pn

                        if part.id != line.part_id:
                            if allocated > 0 or len(line.orders) > 0:
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=f"Cannot change part on PO line '{line.part.part_number}' because it already has allocated orders.",
                                )
                            changes.append(f"line[{line.id}] part: {line.part.part_number} -> {part.part_number}")
                            line.part_id = part.id
                        if cust_pn:
                            line.customer_part_number = cust_pn

                    if line.po_qty != line_req.po_qty:
                        changes.append(f"line[{line.id}] po_qty: {line.po_qty} -> {line_req.po_qty}")
                        line.po_qty = line_req.po_qty

                    if line.required_date != line_req.required_date:
                        changes.append(f"line[{line.id}] required_date: {line.required_date} -> {line_req.required_date}")
                        line.required_date = line_req.required_date

                else:
                    # New line addition
                    cust_pn = (line_req.customer_part_number or "").strip()
                    pn = (line_req.part_number or "").strip()
                    if cust_pn:
                        part, _, _ = resolve_customer_part(
                            db, po.customer, cust_pn, create_if_missing=True
                        )
                    elif pn:
                        clean_pn = pn.upper()
                        existing_part = db.query(Part).filter(Part.part_number == clean_pn).first()
                        if existing_part:
                            part = existing_part
                            mapping = _find_customer_part_mapping(db, po.customer.id, pn)
                            if mapping:
                                cust_pn = mapping.customer_part_number
                        else:
                            part, _, _ = resolve_customer_part(
                                db, po.customer, pn, create_if_missing=True
                            )
                            cust_pn = pn
                    else:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Each PO line must supply either a Customer Part Number or an Internal Part Number.",
                        )

                    new_line = POLine(
                        po_id=po.id,
                        part_id=part.id,
                        customer_part_number=cust_pn or None,
                        po_qty=line_req.po_qty,
                        required_date=line_req.required_date,
                    )
                    db.add(new_line)
                    changes.append(f"added line: part={part.part_number}, po_qty={line_req.po_qty}")

            # Deleted lines check
            for line_id_str, line in existing_lines_by_id.items():
                if line_id_str not in payload_line_ids:
                    allocated = sum(o.po_qty for o in line.orders)
                    if allocated > 0 or len(line.orders) > 0:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                f"Cannot delete PO line for part '{line.part.part_number}' "
                                f"because it has {allocated} allocated quantity across {len(line.orders)} linked order(s)."
                            ),
                        )
                    changes.append(f"deleted line: part={line.part.part_number}, po_qty={line.po_qty}")
                    db.delete(line)

        details_str = "; ".join(changes) if changes else "No fields changed"
        _audit(db, current_user, "PO_UPDATED", "POMaster", str(po.id), details=details_str)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not update PO due to a database integrity or concurrency conflict.",
            )

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
        if status_filter and status_filter.upper() != "ALL":
            query = query.filter(func.lower(CustomerPartMapping.status) == status_filter.strip().lower())
        if search:
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
            db.query(Customer).filter(Customer.id == customer.id).with_for_update().first()

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

            next_code = next_internal_part_number(db, customer.customer_code)

            part = Part(
                part_number=next_code,
                description=req.description or raw_cpn,
            )
            db.add(part)
            db.flush()

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

        db.query(Customer).filter(Customer.id == customer.id).with_for_update().first()

        if req.customer_part_number is not None:
            new_cpn = req.customer_part_number.strip()
            if not new_cpn:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Customer Part Number cannot be blank.")
            if new_cpn != mapping.customer_part_number:
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
