import os
import sys
import dotenv
from typing import Optional, List
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, distinct

from app.models.order import Customer, Part
from app.models.customer_part_cross_reference import CustomerPartCrossReference
from app.models.user import User
from app.models.audit import AuditLog
from app.schemas.part_master import (
    PartMasterItemOut,
    PartMasterListResponse,
    PartMasterStats,
    CustomerMappingBrief,
    PartCreate,
    PartUpdate,
)


class PartMasterService:

    @classmethod
    def get_stats(cls, db: Session) -> PartMasterStats:
        total_parts = db.query(func.count(Part.id)).scalar() or 0
        mapped_parts = db.query(func.count(distinct(CustomerPartCrossReference.part_id))).filter(
            CustomerPartCrossReference.is_active == True
        ).scalar() or 0
        unmapped_parts = max(0, total_parts - mapped_parts)
        total_mappings = db.query(func.count(CustomerPartCrossReference.id)).filter(
            CustomerPartCrossReference.is_active == True
        ).scalar() or 0
        total_customers = db.query(func.count(distinct(CustomerPartCrossReference.customer_id))).filter(
            CustomerPartCrossReference.is_active == True
        ).scalar() or 0

        return PartMasterStats(
            total_parts=total_parts,
            mapped_parts=mapped_parts,
            unmapped_parts=unmapped_parts,
            total_mappings=total_mappings,
            total_customers=total_customers,
        )

    @classmethod
    def list_parts(
        cls,
        db: Session,
        search: Optional[str] = None,
        customer_code: Optional[str] = None,
        mapping_status: Optional[str] = None,  # 'all' | 'mapped' | 'unmapped'
        limit: int = 50,
        offset: int = 0,
        include_stats: bool = True,
    ) -> PartMasterListResponse:
        query = db.query(Part)

        # 1. Customer code filter (shows only Internal Parts mapped to that customer)
        if customer_code and customer_code.strip():
            c_code = customer_code.strip()
            subq = (
                db.query(CustomerPartCrossReference.part_id)
                .join(Customer, CustomerPartCrossReference.customer_id == Customer.id)
                .filter(
                    func.lower(Customer.customer_code) == func.lower(c_code),
                    CustomerPartCrossReference.is_active == True,
                )
            )
            query = query.filter(Part.id.in_(subq))

        # 2. Mapping status filter ('mapped' vs 'unmapped')
        if mapping_status:
            ms = mapping_status.strip().lower()
            if ms == "mapped":
                subq_mapped = (
                    db.query(CustomerPartCrossReference.part_id)
                    .filter(CustomerPartCrossReference.is_active == True)
                    .distinct()
                )
                query = query.filter(Part.id.in_(subq_mapped))
            elif ms == "unmapped":
                subq_mapped = (
                    db.query(CustomerPartCrossReference.part_id)
                    .filter(CustomerPartCrossReference.is_active == True)
                    .distinct()
                )
                query = query.filter(~Part.id.in_(subq_mapped))

        # 3. Search query: Searches Internal Part No, Description, Grade, Customer Part No, Customer Code/Name
        if search and search.strip():
            s = f"%{search.strip()}%"
            # Matching in Part table
            part_match = or_(
                Part.part_number.ilike(s),
                Part.description.ilike(s),
                Part.grade.ilike(s),
            )
            # Matching via Customer Cross-References
            cross_ref_match_subq = (
                db.query(CustomerPartCrossReference.part_id)
                .join(Customer, CustomerPartCrossReference.customer_id == Customer.id)
                .filter(
                    or_(
                        CustomerPartCrossReference.customer_part_no.ilike(s),
                        Customer.customer_code.ilike(s),
                        Customer.name.ilike(s),
                    )
                )
            )
            query = query.filter(or_(part_match, Part.id.in_(cross_ref_match_subq)))

        total = query.count()
        parts = query.order_by(Part.part_number).offset(offset).limit(limit).all()

        # Batch-load customer mappings for the selected page of parts
        part_ids = [p.id for p in parts]
        mappings_by_part = {p_id: [] for p_id in part_ids}

        if part_ids:
            ref_rows = (
                db.query(
                    CustomerPartCrossReference,
                    Customer.customer_code,
                    Customer.name.label("customer_name"),
                )
                .join(Customer, CustomerPartCrossReference.customer_id == Customer.id)
                .filter(CustomerPartCrossReference.part_id.in_(part_ids))
                .order_by(Customer.customer_code, CustomerPartCrossReference.customer_part_no)
                .all()
            )
            for ref, c_code, c_name in ref_rows:
                mappings_by_part[ref.part_id].append(
                    CustomerMappingBrief(
                        id=str(ref.id),
                        customer_id=str(ref.customer_id),
                        customer_code=c_code,
                        customer_name=c_name,
                        customer_part_no=ref.customer_part_no,
                        source=ref.source,
                        is_active=ref.is_active,
                    )
                )

        items = []
        for p in parts:
            p_mappings = mappings_by_part.get(p.id, [])
            distinct_custs = {m.customer_id for m in p_mappings if m.is_active}
            items.append(
                PartMasterItemOut(
                    id=str(p.id),
                    part_number=p.part_number,
                    description=p.description,
                    grade=p.grade,
                    is_active=True,
                    customer_count=len(distinct_custs),
                    mapping_count=len(p_mappings),
                    customer_mappings=p_mappings,
                )
            )

        stats = cls.get_stats(db) if include_stats else None

        return PartMasterListResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            stats=stats,
        )

    @classmethod
    def get_part(cls, db: Session, part_id: UUID) -> PartMasterItemOut:
        part = db.query(Part).filter(Part.id == part_id).first()
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part '{part_id}' not found.")

        ref_rows = (
            db.query(
                CustomerPartCrossReference,
                Customer.customer_code,
                Customer.name.label("customer_name"),
            )
            .join(Customer, CustomerPartCrossReference.customer_id == Customer.id)
            .filter(CustomerPartCrossReference.part_id == part.id)
            .order_by(Customer.customer_code, CustomerPartCrossReference.customer_part_no)
            .all()
        )
        mappings = [
            CustomerMappingBrief(
                id=str(ref.id),
                customer_id=str(ref.customer_id),
                customer_code=c_code,
                customer_name=c_name,
                customer_part_no=ref.customer_part_no,
                source=ref.source,
                is_active=ref.is_active,
            )
            for ref, c_code, c_name in ref_rows
        ]
        distinct_custs = {m.customer_id for m in mappings if m.is_active}

        return PartMasterItemOut(
            id=str(part.id),
            part_number=part.part_number,
            description=part.description,
            grade=part.grade,
            is_active=True,
            customer_count=len(distinct_custs),
            mapping_count=len(mappings),
            customer_mappings=mappings,
        )

    @classmethod
    def create_part(cls, db: Session, payload: PartCreate, current_user: Optional[User] = None) -> PartMasterItemOut:
        p_num = payload.part_number.strip()
        existing = db.query(Part).filter(func.lower(Part.part_number) == func.lower(p_num)).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Part number '{p_num}' already exists in Part Master (ID: {existing.id}).",
            )

        new_part = Part(
            part_number=p_num,
            description=payload.description.strip() if payload.description else None,
            grade=payload.grade.strip() if payload.grade else None,
        )
        db.add(new_part)
        db.flush()

        db.add(
            AuditLog(
                user_name=current_user.email if current_user else "system",
                action="PART_MASTER_CREATE",
                entity="Part",
                entity_id=str(new_part.id),
                new_value=f"part_number={new_part.part_number}, grade={new_part.grade}, desc={new_part.description}",
            )
        )
        db.commit()
        db.refresh(new_part)

        return PartMasterItemOut(
            id=str(new_part.id),
            part_number=new_part.part_number,
            description=new_part.description,
            grade=new_part.grade,
            is_active=True,
            customer_count=0,
            mapping_count=0,
            customer_mappings=[],
        )

    @classmethod
    def update_part(cls, db: Session, part_id: UUID, payload: PartUpdate, current_user: Optional[User] = None) -> PartMasterItemOut:
        part = db.query(Part).filter(Part.id == part_id).first()
        if not part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Part '{part_id}' not found.")

        old_val = f"grade={part.grade}, desc={part.description}"
        if payload.description is not None:
            part.description = payload.description.strip() if payload.description else None
        if payload.grade is not None:
            part.grade = payload.grade.strip() if payload.grade else None

        new_val = f"grade={part.grade}, desc={part.description}"
        db.add(
            AuditLog(
                user_name=current_user.email if current_user else "system",
                action="PART_MASTER_UPDATE",
                entity="Part",
                entity_id=str(part.id),
                old_value=old_val,
                new_value=new_val,
            )
        )
        db.commit()
        db.refresh(part)

        return cls.get_part(db, part.id)
