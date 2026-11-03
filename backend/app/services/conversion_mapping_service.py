from typing import Optional, List
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.conversion_mapping import ConversionPartMapping
from app.models.customer_part_mapping import CustomerPartMapping
from app.models.order import Customer, Part
from app.models.user import User
from app.schemas.conversion_mapping import ConversionMappingCreate, ConversionMappingUpdate, ConversionMappingOut

VALID_CONVERSION_TYPES = ("PART_TO_PART", "SAME_PART")


def _get_part_customer_info(db: Optional[Session], part: Optional[Part]):
    if not db or not part:
        return None, None
    cpm = (
        db.query(CustomerPartMapping.customer_part_number, Customer.name)
        .outerjoin(Customer, CustomerPartMapping.customer_id == Customer.id)
        .filter(CustomerPartMapping.part_id == part.id)
        .first()
    )
    if cpm and cpm[0]:
        return cpm[0], cpm[1]
    return part.description or part.part_number, None


def _to_out(m: ConversionPartMapping, db: Optional[Session] = None) -> ConversionMappingOut:
    src_cust_part, src_cust_name = _get_part_customer_info(db, m.source_part)
    dst_cust_part, dst_cust_name = _get_part_customer_info(db, m.destination_part)
    return ConversionMappingOut(
        id=str(m.id),
        source_part_number=m.source_part.part_number if m.source_part else "N/A",
        destination_part_number=m.destination_part.part_number if m.destination_part else "N/A",
        conversion_type=m.conversion_type,
        conversion_factor=m.conversion_factor,
        is_active=m.is_active,
        created_by_name=m.created_by_name,
        created_at=m.created_at,
        updated_by_name=m.updated_by_name,
        updated_at=m.updated_at,
        source_customer_part_number=src_cust_part,
        source_customer_name=src_cust_name,
        destination_customer_part_number=dst_cust_part,
        destination_customer_name=dst_cust_name
    )


class ConversionMappingService:
    @staticmethod
    def _find_part(db: Session, term: str) -> Optional[Part]:
        if not term:
            return None
        cleaned = term.strip()
        # 1. Exact match by internal part_number
        part = db.query(Part).filter(Part.part_number.ilike(cleaned)).first()
        if part:
            return part
        # 2. Match by CustomerPartMapping.customer_part_number
        cpm = db.query(CustomerPartMapping).filter(CustomerPartMapping.customer_part_number.ilike(cleaned)).first()
        if cpm:
            part = db.query(Part).filter(Part.id == cpm.part_id).first()
            if part:
                return part
        # 3. Match by Part.description
        return db.query(Part).filter(Part.description.ilike(cleaned)).first()

    @staticmethod
    def list_mappings(db: Session, source_part_number: Optional[str] = None, active_only: bool = False) -> List[ConversionMappingOut]:
        query = db.query(ConversionPartMapping)
        if source_part_number:
            part = ConversionMappingService._find_part(db, source_part_number)
            if not part:
                return []
            query = query.filter(ConversionPartMapping.source_part_id == part.id)
        if active_only:
            query = query.filter(ConversionPartMapping.is_active.is_(True))
        rows = query.order_by(ConversionPartMapping.created_at.desc()).all()
        return [_to_out(m, db=db) for m in rows]

    @staticmethod
    def create_mapping(db: Session, req: ConversionMappingCreate, current_user: Optional[User] = None) -> ConversionMappingOut:
        conv_type = req.conversion_type.strip().upper()
        if conv_type not in VALID_CONVERSION_TYPES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"conversion_type must be one of {VALID_CONVERSION_TYPES}.")

        src_part = ConversionMappingService._find_part(db, req.source_part_number)
        if not src_part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Source part '{req.source_part_number}' not found.")
        dst_part = ConversionMappingService._find_part(db, req.destination_part_number)
        if not dst_part:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Destination part '{req.destination_part_number}' not found.")

        if conv_type == "SAME_PART" and src_part.id != dst_part.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="conversion_type SAME_PART requires source and destination part to be identical.")
        if conv_type == "PART_TO_PART" and src_part.id == dst_part.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="conversion_type PART_TO_PART requires source and destination part to differ; use SAME_PART for an identical part.")

        existing = db.query(ConversionPartMapping).filter(
            ConversionPartMapping.source_part_id == src_part.id,
            ConversionPartMapping.destination_part_id == dst_part.id
        ).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"A mapping for {src_part.part_number} -> {dst_part.part_number} already exists (id {existing.id}). Update it instead of creating a duplicate.")

        mapping = ConversionPartMapping(
            source_part_id=src_part.id,
            destination_part_id=dst_part.id,
            conversion_type=conv_type,
            conversion_factor=req.conversion_factor,
            is_active=req.is_active,
            created_by_id=current_user.id if current_user else None,
            created_by_name=current_user.full_name if current_user else "Planner"
        )
        db.add(mapping)
        db.commit()
        db.refresh(mapping)
        return _to_out(mapping, db=db)

    @staticmethod
    def update_mapping(db: Session, req: ConversionMappingUpdate, current_user: Optional[User] = None) -> ConversionMappingOut:
        mapping = db.query(ConversionPartMapping).filter(ConversionPartMapping.id == req.id).first()
        if not mapping:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Conversion mapping '{req.id}' not found.")
        if req.is_active is not None:
            mapping.is_active = req.is_active
        if req.conversion_factor is not None:
            mapping.conversion_factor = req.conversion_factor
        mapping.updated_by_id = current_user.id if current_user else None
        mapping.updated_by_name = current_user.full_name if current_user else "Planner"
        db.commit()
        db.refresh(mapping)
        return _to_out(mapping, db=db)

    @staticmethod
    def is_conversion_allowed(db: Session, source_part_id, destination_part_id, conversion_type: str) -> bool:
        mapping = db.query(ConversionPartMapping).filter(
            ConversionPartMapping.source_part_id == source_part_id,
            ConversionPartMapping.destination_part_id == destination_part_id,
            ConversionPartMapping.is_active.is_(True)
        ).first()
        return mapping is not None
