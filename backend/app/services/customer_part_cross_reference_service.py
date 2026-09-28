from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from app.models.order import Customer, Part
from app.models.customer_part_cross_reference import CustomerPartCrossReference
from app.models.user import User
from app.models.audit import AuditLog
from app.schemas.customer_part_cross_reference import (
    CustomerPartCrossReferenceCreate,
    CustomerPartCrossReferenceUpdate,
    CustomerPartCrossReferenceOut,
    CustomerPartCrossReferenceListResponse,
    PartLookupResponse,
)


class CustomerPartCrossReferenceService:

    @classmethod
    def lookup_part(
        cls,
        db: Session,
        customer_code: str,
        customer_part_no: str
    ) -> PartLookupResponse:
        """Customer-specific part lookup.

        Given a customer code and customer part number, resolves the authoritative
        internal Part record. If multiple conflicting active mappings exist for that
        customer, reports ambiguity and NEVER silently chooses a part.
        """
        if not customer_code or not customer_code.strip():
            return PartLookupResponse(
                customer_code="",
                customer_part_no=customer_part_no or "",
                is_matched=False,
                match_type="none",
                message="Customer code is required for customer-specific part lookup."
            )

        c_code = customer_code.strip()
        cp_no = (customer_part_no or "").strip()

        customer = db.query(Customer).filter(
            func.lower(Customer.customer_code) == func.lower(c_code)
        ).first()

        if not customer:
            return PartLookupResponse(
                customer_code=c_code,
                customer_part_no=cp_no,
                is_matched=False,
                match_type="none",
                message=f"Customer '{c_code}' not found in Customer Master."
            )

        if not cp_no:
            return PartLookupResponse(
                customer_code=customer.customer_code,
                customer_name=customer.name,
                customer_part_no="",
                is_matched=False,
                match_type="none",
                message="Customer part number is required."
            )

        # 1. Search active cross-reference mappings for this specific customer
        cross_refs = (
            db.query(CustomerPartCrossReference)
            .filter(
                CustomerPartCrossReference.customer_id == customer.id,
                func.lower(CustomerPartCrossReference.customer_part_no) == func.lower(cp_no),
                CustomerPartCrossReference.is_active == True,
            )
            .all()
        )

        if len(cross_refs) == 1:
            ref = cross_refs[0]
            part = db.query(Part).filter(Part.id == ref.part_id).first()
            if part:
                return PartLookupResponse(
                    customer_code=customer.customer_code,
                    customer_name=customer.name,
                    customer_part_no=cp_no,
                    part_id=part.id,
                    part_number=part.part_number,
                    grade=part.grade,
                    description=part.description,
                    is_matched=True,
                    match_type="cross_reference",
                    message=f"Resolved via Part Cross-Reference to internal part '{part.part_number}'"
                )

        if len(cross_refs) > 1:
            # Ambiguous mapping: NEVER silently pick one!
            candidate_part_ids = [r.part_id for r in cross_refs]
            candidate_parts = [
                p.part_number
                for p in db.query(Part).filter(Part.id.in_(candidate_part_ids)).all()
            ]
            return PartLookupResponse(
                customer_code=customer.customer_code,
                customer_name=customer.name,
                customer_part_no=cp_no,
                is_matched=False,
                match_type="ambiguous",
                candidate_parts=candidate_parts,
                message=(
                    f"Ambiguous mapping: Customer Part No '{cp_no}' has {len(candidate_parts)} "
                    f"conflicting internal parts mapped for customer '{customer.customer_code}'. "
                    f"Explicit selection required."
                )
            )

        # 2. Fallback: Direct match against Internal Part Master
        direct_part = db.query(Part).filter(
            func.lower(Part.part_number) == func.lower(cp_no)
        ).first()

        if direct_part:
            return PartLookupResponse(
                customer_code=customer.customer_code,
                customer_name=customer.name,
                customer_part_no=cp_no,
                part_id=direct_part.id,
                part_number=direct_part.part_number,
                grade=direct_part.grade,
                description=direct_part.description,
                is_matched=True,
                match_type="direct_internal",
                message=f"Direct internal part master match for '{direct_part.part_number}'"
            )

        return PartLookupResponse(
            customer_code=customer.customer_code,
            customer_name=customer.name,
            customer_part_no=cp_no,
            is_matched=False,
            match_type="none",
            message=f"No mapping found for '{cp_no}' under customer '{customer.customer_code}'"
        )

    @classmethod
    def list_cross_references(
        cls,
        db: Session,
        customer_code: Optional[str] = None,
        part_number: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> CustomerPartCrossReferenceListResponse:
        query = (
            db.query(
                CustomerPartCrossReference,
                Customer.customer_code.label("customer_code"),
                Customer.name.label("customer_name"),
                Part.part_number.label("internal_part_code"),
                Part.description.label("part_description"),
                Part.grade.label("part_grade"),
            )
            .join(Customer, CustomerPartCrossReference.customer_id == Customer.id)
            .join(Part, CustomerPartCrossReference.part_id == Part.id)
        )

        if customer_code:
            query = query.filter(func.lower(Customer.customer_code) == func.lower(customer_code.strip()))

        if part_number:
            query = query.filter(func.lower(Part.part_number) == func.lower(part_number.strip()))

        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    CustomerPartCrossReference.customer_part_no.ilike(s),
                    Customer.customer_code.ilike(s),
                    Customer.name.ilike(s),
                    Part.part_number.ilike(s),
                    Part.description.ilike(s),
                )
            )

        total = query.count()
        rows = query.order_by(Customer.customer_code, CustomerPartCrossReference.customer_part_no).offset(offset).limit(limit).all()

        results = []
        for ref, c_code, c_name, int_code, desc, gr in rows:
            results.append(
                CustomerPartCrossReferenceOut(
                    id=ref.id,
                    customer_id=ref.customer_id,
                    customer_code=c_code,
                    customer_name=c_name,
                    customer_part_no=ref.customer_part_no,
                    part_id=ref.part_id,
                    internal_part_code=int_code,
                    part_description=desc,
                    part_grade=gr,
                    source=ref.source,
                    is_active=ref.is_active,
                    created_at=ref.created_at,
                    updated_at=ref.updated_at,
                    created_by_name=ref.created_by_name,
                )
            )
        return CustomerPartCrossReferenceListResponse(
            items=results,
            total=total,
            limit=limit,
            offset=offset,
        )

    @classmethod
    def create_cross_reference(
        cls,
        db: Session,
        payload: CustomerPartCrossReferenceCreate,
        current_user: Optional[User] = None
    ) -> CustomerPartCrossReferenceOut:
        # Resolve customer
        customer = None
        if payload.customer_id:
            customer = db.query(Customer).filter(Customer.id == payload.customer_id).first()
        elif payload.customer_code:
            customer = db.query(Customer).filter(
                func.lower(Customer.customer_code) == func.lower(payload.customer_code.strip())
            ).first()

        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found."
            )

        # Resolve part
        part = None
        if payload.part_id:
            part = db.query(Part).filter(Part.id == payload.part_id).first()
        elif payload.internal_part_code:
            part = db.query(Part).filter(
                func.lower(Part.part_number) == func.lower(payload.internal_part_code.strip())
            ).first()

        if not part:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Internal Part not found in Part Master."
            )

        cp_no = payload.customer_part_no.strip()
        if not cp_no:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Customer part number cannot be empty."
            )

        # Check existing mapping for (customer_id, customer_part_no)
        existing = (
            db.query(CustomerPartCrossReference)
            .filter(
                CustomerPartCrossReference.customer_id == customer.id,
                func.lower(CustomerPartCrossReference.customer_part_no) == func.lower(cp_no),
            )
            .first()
        )

        if existing:
            if existing.part_id == part.id:
                # Identical duplicate -> return existing
                return CustomerPartCrossReferenceOut(
                    id=existing.id,
                    customer_id=customer.id,
                    customer_code=customer.customer_code,
                    customer_name=customer.name,
                    customer_part_no=existing.customer_part_no,
                    part_id=part.id,
                    internal_part_code=part.part_number,
                    part_description=part.description,
                    part_grade=part.grade,
                    source=existing.source,
                    is_active=existing.is_active,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                    created_by_name=existing.created_by_name,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Conflicting mapping: Customer Part No '{cp_no}' already exists for "
                        f"customer '{customer.customer_code}' mapped to another part. "
                        f"Update the existing mapping instead."
                    )
                )

        new_ref = CustomerPartCrossReference(
            customer_id=customer.id,
            customer_part_no=cp_no,
            part_id=part.id,
            source=payload.source or "Manual",
            is_active=payload.is_active,
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "system",
        )
        db.add(new_ref)
        db.flush()

        db.add(
            AuditLog(
                user_id=current_user.id if current_user else None,
                user_name=current_user.full_name if current_user else "system",
                action="CREATE_PART_CROSS_REFERENCE",
                entity="CustomerPartCrossReference",
                entity_id=str(new_ref.id),
                new_value=f"{customer.customer_code} + {cp_no} -> {part.part_number}",
                details=f"Created Part Cross-Reference: {customer.customer_code} | {cp_no} -> {part.part_number}",
            )
        )
        db.commit()

        return CustomerPartCrossReferenceOut(
            id=new_ref.id,
            customer_id=customer.id,
            customer_code=customer.customer_code,
            customer_name=customer.name,
            customer_part_no=new_ref.customer_part_no,
            part_id=part.id,
            internal_part_code=part.part_number,
            part_description=part.description,
            part_grade=part.grade,
            source=new_ref.source,
            is_active=new_ref.is_active,
            created_at=new_ref.created_at,
            updated_at=new_ref.updated_at,
            created_by_name=new_ref.created_by_name,
        )

    @classmethod
    def update_cross_reference(
        cls,
        db: Session,
        ref_id: UUID,
        payload: CustomerPartCrossReferenceUpdate,
        current_user: Optional[User] = None
    ) -> CustomerPartCrossReferenceOut:
        ref = db.query(CustomerPartCrossReference).filter(CustomerPartCrossReference.id == ref_id).first()
        if not ref:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Part Cross-Reference record not found."
            )

        if payload.part_id or payload.internal_part_code:
            part = None
            if payload.part_id:
                part = db.query(Part).filter(Part.id == payload.part_id).first()
            elif payload.internal_part_code:
                part = db.query(Part).filter(
                    func.lower(Part.part_number) == func.lower(payload.internal_part_code.strip())
                ).first()
            if not part:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Internal Part not found in Part Master."
                )
            ref.part_id = part.id

        if payload.source is not None:
            ref.source = payload.source

        if payload.is_active is not None:
            ref.is_active = payload.is_active

        customer = db.query(Customer).filter(Customer.id == ref.customer_id).first()
        part = db.query(Part).filter(Part.id == ref.part_id).first()

        db.add(
            AuditLog(
                user_id=current_user.id if current_user else None,
                user_name=current_user.full_name if current_user else "system",
                action="UPDATE_PART_CROSS_REFERENCE",
                entity="CustomerPartCrossReference",
                entity_id=str(ref.id),
                new_value=f"{customer.customer_code if customer else ''} + {ref.customer_part_no} -> {part.part_number if part else ''}",
                details=f"Updated Part Cross-Reference: id={ref.id}, is_active={ref.is_active}",
            )
        )
        db.commit()

        return CustomerPartCrossReferenceOut(
            id=ref.id,
            customer_id=ref.customer_id,
            customer_code=customer.customer_code if customer else "",
            customer_name=customer.name if customer else "",
            customer_part_no=ref.customer_part_no,
            part_id=ref.part_id,
            internal_part_code=part.part_number if part else "",
            part_description=part.description if part else None,
            part_grade=part.grade if part else None,
            source=ref.source,
            is_active=ref.is_active,
            created_at=ref.created_at,
            updated_at=ref.updated_at,
            created_by_name=ref.created_by_name,
        )
