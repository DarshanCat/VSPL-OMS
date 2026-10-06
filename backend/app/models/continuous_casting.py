"""Continuous Casting (China) raw-material inventory module.

Stock only -- never a second OMS. The customer-production identity stays the existing
Order/WorkOrder; these tables only record physical raw-material stock and which WO's
routing it was allocated to. Nothing here touches WorkOrder/WORoute/StageWIP.

Conventions:
  * Every length/dimension is an INTEGER number of millimetres (never Numeric/float);
    piece counts are separate Integer columns. A length is never stored as a count.
  * The stock ledger is authoritative. The cached balances on a stock unit and on an
    allocation must be changed in the same transaction as the ledger row that explains
    them, with the stock unit row locked (with_for_update()).
  * Status/type columns are plain String (not SQLAlchemy Enum), matching the rest of
    the schema; the allowed values are the module-level tuples below.
"""
import re
import uuid
from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey,
    CheckConstraint, UniqueConstraint, Index, event, text,
)
from sqlalchemy.orm import Session, relationship
from sqlalchemy.sql import func
from app.core.database import Base, GUID

MATERIAL_SOURCE_CONTINUOUS_CASTING = "CONTINUOUS_CASTING"
MATERIAL_SOURCE_F1_PRODUCTION = "F1_PRODUCTION"
MATERIAL_SOURCES = (MATERIAL_SOURCE_CONTINUOUS_CASTING, MATERIAL_SOURCE_F1_PRODUCTION)

INWARD_QA_STATUSES = ("PENDING_QA", "ACCEPTED", "REJECTED", "ON_HOLD")
# Physical lifecycle of a unit. IN_STOCK means "physically present"; it does NOT mean
# "allocatable" -- allocation also needs the inward's QA status to be ACCEPTED (see
# allocation_ineligibility_reason). QA stays authoritative on the inward; it is never
# copied onto the unit, so there is one source of truth.
STOCK_UNIT_STATUSES = ("IN_STOCK", "ON_HOLD", "CONSUMED", "SCRAPPED")
UNIT_STATUS_IN_STOCK = "IN_STOCK"
INWARD_INITIAL_QA_STATUS = "PENDING_QA"
ALLOCATABLE_QA_STATUS = "ACCEPTED"
ROUTING_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")
ALLOCATION_STATUSES = (
    "PLANNED", "RESERVED", "ISSUED", "PARTIALLY_CONSUMED", "CONSUMED", "RELEASED", "CANCELLED",
)
LEDGER_MOVEMENT_TYPES = (
    "INWARD", "RESERVE", "RELEASE", "ISSUE", "CUT_CONSUME",
    "RETURN", "HOLD", "HOLD_RELEASE", "SCRAP", "ADJUSTMENT_IN", "ADJUSTMENT_OUT",
    "SPLIT_OUT", "SPLIT_IN",
)
# Row shapes enforced by ck_cc_ledger_shape (see the ledger model).
SPLIT_MOVEMENTS = ("SPLIT_OUT", "SPLIT_IN")
HOLD_MOVEMENTS = ("HOLD", "HOLD_RELEASE")
DISPOSAL_MOVEMENTS = ("SCRAP", "ADJUSTMENT_IN", "ADJUSTMENT_OUT")
CUT_RECONCILIATION_STATUSES = ("PENDING", "RECONCILED", "VARIANCE")

# Business-number conventions -- FROZEN, approved for the China module. These prefixes and
# the 6-digit zero padding are NEW to this module (INW-000001, UNIT-000001, ALC-000001,
# CUT-000001, TXN-000001); they are not inherited from any existing VSPL number format.
# Only the generation algorithm (parse-max-and-increment, see the next_cc_* functions at
# the bottom) follows the existing next_nc_number / packing-unit-code approach.
CC_NUMBER_WIDTH = 6
CC_INWARD_PREFIX = "INW"
CC_UNIT_PREFIX = "UNIT"
CC_ALLOCATION_PREFIX = "ALC"
CC_CUT_PREFIX = "CUT"
CC_LEDGER_PREFIX = "TXN"


class ContinuousCastingMaterial(Base):
    """Material master: grade, stock section/shape and stock dimensions."""
    __tablename__ = "cc_materials"
    __table_args__ = (
        CheckConstraint("stock_dimension_a_mm > 0", name="ck_cc_material_dim_a_positive"),
        CheckConstraint(
            "stock_dimension_b_mm IS NULL OR stock_dimension_b_mm > 0",
            name="ck_cc_material_dim_b_positive",
        ),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    material_code = Column(String, unique=True, nullable=False, index=True)
    grade = Column(String, nullable=False)
    section = Column(String, nullable=False)
    # Primary / secondary stock dimension (e.g. outer / inner diameter, or width / height).
    stock_dimension_a_mm = Column(Integer, nullable=False)
    stock_dimension_b_mm = Column(Integer, nullable=True)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    inwards = relationship("ContinuousCastingInward", back_populates="material")


class ContinuousCastingInward(Base):
    """One receipt of continuous-casting material. Exists without any order or WO.
    Grade/section/dimensions are an immutable snapshot taken at receipt."""
    __tablename__ = "cc_inwards"
    __table_args__ = (
        CheckConstraint("received_piece_count >= 0", name="ck_cc_inward_pieces_nonneg"),
        CheckConstraint("received_total_length_mm >= 0", name="ck_cc_inward_length_nonneg"),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    inward_number = Column(String, unique=True, nullable=False, index=True)
    material_id = Column(GUID, ForeignKey("cc_materials.id"), nullable=False)
    grade = Column(String, nullable=False)
    section = Column(String, nullable=False)
    stock_dimension_a_mm = Column(Integer, nullable=False)
    stock_dimension_b_mm = Column(Integer, nullable=True)
    received_piece_count = Column(Integer, nullable=False)
    received_total_length_mm = Column(Integer, nullable=False)
    grn_reference = Column(String, nullable=True)
    qa_status = Column(String, nullable=False, default="PENDING_QA")
    location = Column(String, nullable=True)
    remarks = Column(String, nullable=True)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    material = relationship("ContinuousCastingMaterial", back_populates="inwards")
    stock_units = relationship("ContinuousCastingStockUnit", back_populates="inward")


class ContinuousCastingStockUnit(Base):
    """One physical bar/piece. A remnant left after cutting is a new child unit
    (parent_unit_id) created by a SPLIT; the parent's original identity is never rewritten.
    A child's original_length_mm is the length it was split off with.
    Status CONSUMED is terminal and means remaining = 0 AND consumed > 0 (enforced by the
    service reconciliation, not a CHECK): a bar exhausted by cutting and/or by moving its
    remnant to a child. It is never reached by remaining = 0 alone.

    Cached balances (all mm):
      remaining  = physical length still present on this unit
      reserved   = remaining length promised to allocations, not yet issued
      issued     = remaining length handed to production, not yet cut
      consumed   = cumulative length actually cut away
    """
    __tablename__ = "cc_stock_units"
    __table_args__ = (
        CheckConstraint("original_length_mm > 0", name="ck_cc_unit_original_positive"),
        CheckConstraint("remaining_length_mm >= 0", name="ck_cc_unit_remaining_nonneg"),
        CheckConstraint("reserved_length_mm >= 0", name="ck_cc_unit_reserved_nonneg"),
        CheckConstraint("issued_length_mm >= 0", name="ck_cc_unit_issued_nonneg"),
        CheckConstraint("consumed_length_mm >= 0", name="ck_cc_unit_consumed_nonneg"),
        CheckConstraint(
            "reserved_length_mm + issued_length_mm <= remaining_length_mm",
            name="ck_cc_unit_committed_within_remaining",
        ),
        CheckConstraint(
            "remaining_length_mm + consumed_length_mm <= original_length_mm",
            name="ck_cc_unit_no_length_created",
        ),
        CheckConstraint("parent_unit_id IS NULL OR parent_unit_id <> id", name="ck_cc_unit_not_own_parent"),
        CheckConstraint("scrapped_length_mm >= 0", name="ck_cc_unit_scrapped_nonneg"),
        CheckConstraint(
            "remaining_length_mm + consumed_length_mm + scrapped_length_mm <= original_length_mm",
            name="ck_cc_unit_no_length_created_incl_scrap",
        ),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    unit_number = Column(String, unique=True, nullable=False, index=True)
    inward_id = Column(GUID, ForeignKey("cc_inwards.id"), nullable=False, index=True)
    parent_unit_id = Column(GUID, ForeignKey("cc_stock_units.id"), nullable=True)
    original_length_mm = Column(Integer, nullable=False)
    remaining_length_mm = Column(Integer, nullable=False)
    reserved_length_mm = Column(Integer, nullable=False, default=0)
    issued_length_mm = Column(Integer, nullable=False, default=0)
    consumed_length_mm = Column(Integer, nullable=False, default=0)
    # Cached, ledger-reconciled: cumulative length removed by SCRAP (a physical disposal, not a cut).
    scrapped_length_mm = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default=UNIT_STATUS_IN_STOCK)
    location = Column(String, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    inward = relationship("ContinuousCastingInward", back_populates="stock_units")
    parent = relationship("ContinuousCastingStockUnit", remote_side=[id], foreign_keys=[parent_unit_id])


class ContinuousCastingRouting(Base):
    """Versioned material-source snapshot attached to an existing OMS WorkOrder.
    OMS has no route revision of its own (release rebuilds WORoute), so the version
    lives here. At most one ACTIVE routing per WO. The WO itself is never modified."""
    __tablename__ = "cc_routings"
    __table_args__ = (
        UniqueConstraint("work_order_id", "version", name="ux_cc_routing_wo_version"),
        Index(
            "ux_cc_routing_one_active_per_wo", "work_order_id", unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
        CheckConstraint("version >= 1", name="ck_cc_routing_version_positive"),
        CheckConstraint(
            "material_source IN ('CONTINUOUS_CASTING', 'F1_PRODUCTION')",
            name="ck_cc_routing_source_valid",
        ),
        CheckConstraint(
            "material_source <> 'CONTINUOUS_CASTING' OR ("
            "required_grade IS NOT NULL AND required_section IS NOT NULL "
            "AND blank_length_mm IS NOT NULL AND planned_blanks IS NOT NULL "
            "AND gross_required_length_mm IS NOT NULL)",
            name="ck_cc_routing_cc_fields_present",
        ),
        CheckConstraint("blank_length_mm IS NULL OR blank_length_mm > 0", name="ck_cc_routing_blank_positive"),
        CheckConstraint("planned_blanks IS NULL OR planned_blanks > 0", name="ck_cc_routing_blanks_positive"),
        CheckConstraint("planned_cuts IS NULL OR planned_cuts >= 0", name="ck_cc_routing_cuts_nonneg"),
        CheckConstraint(
            "finished_axial_length_mm IS NULL OR finished_axial_length_mm > 0",
            name="ck_cc_routing_axial_positive",
        ),
        CheckConstraint("kerf_mm IS NULL OR kerf_mm >= 0", name="ck_cc_routing_kerf_nonneg"),
        CheckConstraint("end_trim_mm IS NULL OR end_trim_mm >= 0", name="ck_cc_routing_trim_nonneg"),
        CheckConstraint(
            "gross_required_length_mm IS NULL OR gross_required_length_mm > 0",
            name="ck_cc_routing_gross_positive",
        ),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    material_source = Column(String, nullable=False)
    status = Column(String, nullable=False, default="DRAFT")

    required_grade = Column(String, nullable=True)
    required_section = Column(String, nullable=True)
    finished_dimension_a_mm = Column(Integer, nullable=True)
    finished_dimension_b_mm = Column(Integer, nullable=True)
    # Input to blank_length_mm = finished_axial_length_mm + machining_stock_a_mm + machining_stock_b_mm
    finished_axial_length_mm = Column(Integer, nullable=True)
    planned_blanks = Column(Integer, nullable=True)
    blank_length_mm = Column(Integer, nullable=True)
    machining_stock_a_mm = Column(Integer, nullable=True)
    machining_stock_b_mm = Column(Integer, nullable=True)
    kerf_mm = Column(Integer, nullable=True)
    planned_cuts = Column(Integer, nullable=True)
    end_trim_mm = Column(Integer, nullable=True)
    gross_required_length_mm = Column(Integer, nullable=True)

    # Engineering's validated compatibility decision (never inferred by comparing grade strings).
    validated_material_id = Column(GUID, ForeignKey("cc_materials.id"), nullable=True)
    validated_by = Column(String, nullable=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)

    superseded_at = Column(DateTime(timezone=True), nullable=True)
    superseded_by = Column(String, nullable=True)
    supersede_reason = Column(String, nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder", foreign_keys=[work_order_id])
    validated_material = relationship("ContinuousCastingMaterial", foreign_keys=[validated_material_id])
    allocations = relationship("ContinuousCastingAllocation", back_populates="routing")


class ContinuousCastingAllocation(Base):
    """Bridge between a routing (hence an existing WO) and a physical stock unit. One
    WO can draw from many units and one unit can supply many WOs; within one routing a
    unit has a single allocation row that accumulates.

    reserved/issued are current (not cumulative) like the stock unit's; consumed is
    cumulative. Summed over a unit's allocations they must reconcile to the unit."""
    __tablename__ = "cc_allocations"
    __table_args__ = (
        UniqueConstraint("routing_id", "stock_unit_id", name="ux_cc_allocation_routing_unit"),
        CheckConstraint("planned_length_mm >= 0", name="ck_cc_alloc_planned_nonneg"),
        CheckConstraint("reserved_length_mm >= 0", name="ck_cc_alloc_reserved_nonneg"),
        CheckConstraint("issued_length_mm >= 0", name="ck_cc_alloc_issued_nonneg"),
        CheckConstraint("consumed_length_mm >= 0", name="ck_cc_alloc_consumed_nonneg"),
        CheckConstraint(
            "reserved_length_mm + issued_length_mm <= planned_length_mm",
            name="ck_cc_alloc_committed_within_plan",
        ),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    allocation_number = Column(String, unique=True, nullable=False, index=True)
    routing_id = Column(GUID, ForeignKey("cc_routings.id"), nullable=False, index=True)
    stock_unit_id = Column(GUID, ForeignKey("cc_stock_units.id"), nullable=False, index=True)
    planned_length_mm = Column(Integer, nullable=False, default=0)
    reserved_length_mm = Column(Integer, nullable=False, default=0)
    issued_length_mm = Column(Integer, nullable=False, default=0)
    consumed_length_mm = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="PLANNED")
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    routing = relationship("ContinuousCastingRouting", back_populates="allocations")
    stock_unit = relationship("ContinuousCastingStockUnit")


class ContinuousCastingStockLedger(Base):
    """Append-only physical stock ledger. length_mm is a non-negative magnitude; the
    movement_type gives the direction (see LEDGER_MOVEMENT_TYPES):
      RESERVE  -> reserved += x           (free stock down, nothing consumed)
      RELEASE  -> reserved -= x
      ISSUE    -> reserved -= x, issued += x   (raw length unchanged)
      RETURN   -> issued -= x
      CUT_CONSUME -> issued -= x, consumed += x, remaining -= x   (the only real deduction)
      SPLIT_OUT -> parent unit: remaining -= x   (remnant length handed to a child unit)
      SPLIT_IN  -> child unit: remaining += x    (the same length arriving on the remnant)
    A SPLIT_OUT/SPLIT_IN pair carries equal length, so the remnant is never counted twice.
    Each split row names the OTHER unit in related_stock_unit_id (SPLIT_OUT -> the child,
    SPLIT_IN -> the parent); no other movement type may set it. A split moves length between
    units, it does not receive a piece, so split rows carry no piece_qty.
      HOLD / HOLD_RELEASE -> status only (IN_STOCK <-> ON_HOLD); zero length, no balance changes
      SCRAP     -> remaining -= x, scrapped += x   (physical disposal of FREE length)
      ADJUSTMENT_OUT -> remaining -= x  (recorded length corrected down; never exhausts a unit)
      ADJUSTMENT_IN  -> remaining += x  (restores earlier ADJUSTMENT_OUT only)
    Direction always comes from the movement type; length_mm is a non-negative magnitude.
    Per unit: remaining = INWARD + SPLIT_IN + ADJUSTMENT_IN - SPLIT_OUT - CUT_CONSUME - SCRAP
                          - ADJUSTMENT_OUT.
    Rows are never updated or deleted."""
    __tablename__ = "cc_stock_ledger"
    __table_args__ = (
        Index(
            "ux_cc_ledger_client_request_id", "client_request_id", unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
            sqlite_where=text("client_request_id IS NOT NULL"),
        ),
        # A child unit is created by exactly one split.
        Index(
            "ux_cc_ledger_one_split_in_per_unit", "stock_unit_id", unique=True,
            postgresql_where=text("movement_type = 'SPLIT_IN'"),
            sqlite_where=text("movement_type = 'SPLIT_IN'"),
        ),
        # Row shapes. SPLIT_*: names the other unit, positive length. HOLD/HOLD_RELEASE: zero length,
        # a reason. SCRAP/ADJUSTMENT_*: positive length, a reason AND a reference. None of these three
        # groups has an allocation, a piece count or (except a split) a related unit. Every other
        # movement may not name a related unit.
        CheckConstraint(
            "(movement_type IN ('SPLIT_OUT','SPLIT_IN') AND related_stock_unit_id IS NOT NULL "
            "AND related_stock_unit_id <> stock_unit_id AND piece_qty IS NULL AND allocation_id IS NULL "
            "AND length_mm > 0) "
            "OR (movement_type IN ('HOLD','HOLD_RELEASE') AND related_stock_unit_id IS NULL "
            "AND piece_qty IS NULL AND allocation_id IS NULL AND length_mm = 0 AND reason IS NOT NULL) "
            "OR (movement_type IN ('SCRAP','ADJUSTMENT_IN','ADJUSTMENT_OUT') AND related_stock_unit_id IS NULL "
            "AND piece_qty IS NULL AND allocation_id IS NULL AND length_mm > 0 "
            "AND reason IS NOT NULL AND reference IS NOT NULL) "
            "OR (movement_type NOT IN ('SPLIT_OUT','SPLIT_IN','HOLD','HOLD_RELEASE','SCRAP',"
            "'ADJUSTMENT_IN','ADJUSTMENT_OUT') AND related_stock_unit_id IS NULL)",
            name="ck_cc_ledger_shape",
        ),
        CheckConstraint("length_mm >= 0", name="ck_cc_ledger_length_nonneg"),
        CheckConstraint("piece_qty IS NULL OR piece_qty >= 0", name="ck_cc_ledger_pieces_nonneg"),
        CheckConstraint(
            "movement_type IN (" + ",".join(f"'{t}'" for t in LEDGER_MOVEMENT_TYPES) + ")",
            name="ck_cc_ledger_type_valid",
        ),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    transaction_number = Column(String, unique=True, nullable=False, index=True)
    movement_type = Column(String, nullable=False, index=True)
    inward_id = Column(GUID, ForeignKey("cc_inwards.id"), nullable=False, index=True)
    stock_unit_id = Column(GUID, ForeignKey("cc_stock_units.id"), nullable=False, index=True)
    allocation_id = Column(GUID, ForeignKey("cc_allocations.id"), nullable=True, index=True)
    # SPLIT_OUT -> the child unit; SPLIT_IN -> the parent unit; NULL for every other movement.
    related_stock_unit_id = Column(GUID, ForeignKey("cc_stock_units.id"), nullable=True, index=True)
    length_mm = Column(Integer, nullable=False, default=0)
    piece_qty = Column(Integer, nullable=True)
    unit_remaining_after_mm = Column(Integer, nullable=True)
    # Disposition authority stays with the existing NC Tracker; this is only a pointer.
    nc_record_id = Column(GUID, ForeignKey("nc_records.id"), nullable=True)
    reason = Column(String, nullable=True)
    reference = Column(String, nullable=True)
    client_request_id = Column(String, nullable=True)
    performed_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    performed_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    stock_unit = relationship("ContinuousCastingStockUnit", foreign_keys=[stock_unit_id])
    related_stock_unit = relationship("ContinuousCastingStockUnit", foreign_keys=[related_stock_unit_id])
    allocation = relationship("ContinuousCastingAllocation")


@event.listens_for(ContinuousCastingStockLedger, "before_update")
def _ledger_rows_are_immutable_on_update(mapper, connection, target):
    raise ValueError("cc_stock_ledger is append-only: rows cannot be updated.")


@event.listens_for(ContinuousCastingStockLedger, "before_delete")
def _ledger_rows_are_immutable_on_delete(mapper, connection, target):
    raise ValueError("cc_stock_ledger is append-only: rows cannot be deleted.")


class ContinuousCastingCutRecord(Base):
    """Actual cutting / blank-preparation result for an allocation, distinct from the
    planned allocation. actual_good_blanks is what the future material gate compares
    against the first OMS stage's cumulative good + rejected."""
    __tablename__ = "cc_cut_records"
    __table_args__ = (
        # One recorded result per CUT_CONSUME ledger row; and an optional idempotency key.
        Index(
            "ux_cc_cut_one_result_per_ledger_entry", "ledger_entry_id", unique=True,
            postgresql_where=text("ledger_entry_id IS NOT NULL"),
            sqlite_where=text("ledger_entry_id IS NOT NULL"),
        ),
        Index(
            "ux_cc_cut_client_request_id", "client_request_id", unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
            sqlite_where=text("client_request_id IS NOT NULL"),
        ),
        CheckConstraint("actual_cuts >= 0", name="ck_cc_cut_actual_cuts_nonneg"),
        # RECONCILED means the consumed length equals the length the recorded cut needs exactly;
        # VARIANCE means it does not (and says by how much); only RECONCILED results are usable.
        CheckConstraint(
            "(reconciliation_status = 'RECONCILED' AND variance_mm IS NOT NULL AND variance_mm = 0) "
            "OR (reconciliation_status = 'VARIANCE' AND variance_mm IS NOT NULL AND variance_mm <> 0) "
            "OR reconciliation_status = 'PENDING'",
            name="ck_cc_cut_status_matches_variance",
        ),
        CheckConstraint("planned_blanks >= 0", name="ck_cc_cut_planned_nonneg"),
        CheckConstraint("actual_good_blanks >= 0", name="ck_cc_cut_good_nonneg"),
        CheckConstraint("rejected_blanks >= 0", name="ck_cc_cut_rejected_nonneg"),
        CheckConstraint("blank_length_mm > 0", name="ck_cc_cut_blank_positive"),
        CheckConstraint("kerf_mm >= 0", name="ck_cc_cut_kerf_nonneg"),
        CheckConstraint("end_trim_mm >= 0", name="ck_cc_cut_trim_nonneg"),
        CheckConstraint("consumed_length_mm >= 0", name="ck_cc_cut_consumed_nonneg"),
        CheckConstraint("retained_remnant_length_mm >= 0", name="ck_cc_cut_remnant_nonneg"),
        CheckConstraint(
            "reconciliation_status IN ('PENDING','RECONCILED','VARIANCE')",
            name="ck_cc_cut_reconciliation_valid",
        ),
    )

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    cut_number = Column(String, unique=True, nullable=False, index=True)
    work_order_id = Column(GUID, ForeignKey("work_orders.id"), nullable=False, index=True)
    allocation_id = Column(GUID, ForeignKey("cc_allocations.id"), nullable=False, index=True)
    stock_unit_id = Column(GUID, ForeignKey("cc_stock_units.id"), nullable=False, index=True)
    ledger_entry_id = Column(GUID, ForeignKey("cc_stock_ledger.id"), nullable=True)
    planned_blanks = Column(Integer, nullable=False, default=0)
    actual_good_blanks = Column(Integer, nullable=False, default=0)
    rejected_blanks = Column(Integer, nullable=False, default=0)
    blank_length_mm = Column(Integer, nullable=False)
    kerf_mm = Column(Integer, nullable=False, default=0)
    # Number of saw cuts actually made (each costs one kerf); with end_trim_mm it explains the consumed length.
    actual_cuts = Column(Integer, nullable=False, default=0)
    end_trim_mm = Column(Integer, nullable=False, default=0)
    consumed_length_mm = Column(Integer, nullable=False, default=0)
    client_request_id = Column(String, nullable=True)
    retained_remnant_unit_id = Column(GUID, ForeignKey("cc_stock_units.id"), nullable=True)
    retained_remnant_length_mm = Column(Integer, nullable=False, default=0)
    nc_record_id = Column(GUID, ForeignKey("nc_records.id"), nullable=True)
    reconciliation_status = Column(String, nullable=False, default="PENDING")
    variance_mm = Column(Integer, nullable=True)
    remarks = Column(String, nullable=True)
    performed_by_id = Column(GUID, ForeignKey("users.id"), nullable=True)
    performed_by_name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    work_order = relationship("WorkOrder", foreign_keys=[work_order_id])
    allocation = relationship("ContinuousCastingAllocation")
    stock_unit = relationship("ContinuousCastingStockUnit", foreign_keys=[stock_unit_id])
    retained_remnant_unit = relationship("ContinuousCastingStockUnit", foreign_keys=[retained_remnant_unit_id])
    ledger_entry = relationship("ContinuousCastingStockLedger")


@event.listens_for(ContinuousCastingCutRecord, "before_update")
def _cut_records_are_immutable_on_update(mapper, connection, target):
    raise ValueError("cc_cut_records is immutable: a recorded cut result cannot be updated.")


@event.listens_for(ContinuousCastingCutRecord, "before_delete")
def _cut_records_are_immutable_on_delete(mapper, connection, target):
    raise ValueError("cc_cut_records is immutable: a recorded cut result cannot be deleted.")


# ---------------------------------------------------------------------------
# Physical existence vs allocation eligibility. Stock received but pending QA is real,
# visible inventory -- it is simply not allocatable to a WO routing until the existing
# quality process has set the inward's qa_status to ACCEPTED.
# ---------------------------------------------------------------------------
def qa_allocation_block_reason(qa_status):
    """None if this inward QA status permits allocation, else a human-readable reason."""
    if qa_status == ALLOCATABLE_QA_STATUS:
        return None
    return f"inward QA status is {qa_status or 'unknown'}; allocation requires {ALLOCATABLE_QA_STATUS}"


def allocation_ineligibility_reason(unit):
    """None when `unit` may be allocated to a WO routing, otherwise why not."""
    inward = unit.inward
    reason = qa_allocation_block_reason(inward.qa_status if inward is not None else None)
    if reason:
        return reason
    if unit.status != UNIT_STATUS_IN_STOCK:
        return f"unit status is {unit.status}; allocation requires {UNIT_STATUS_IN_STOCK}"
    free = (unit.remaining_length_mm or 0) - (unit.reserved_length_mm or 0) - (unit.issued_length_mm or 0)
    if free <= 0:
        return "no free length remains on this unit"
    return None


def is_allocation_eligible(unit) -> bool:
    return allocation_ineligibility_reason(unit) is None


# ---------------------------------------------------------------------------
# Business-number generators: parse-max-and-increment, like next_nc_number and the
# packing unit code. NOT concurrency-safe on their own -- two transactions can compute
# the same number, and the unique constraint on each number column is the only
# backstop (a collision surfaces as IntegrityError on flush/commit, which the caller
# must treat as "number taken", never as success). Sessions here use autoflush=False,
# so pending (added, not yet flushed) rows of the same model are counted as well.
# ---------------------------------------------------------------------------
def _highest_suffix(db: Session, model, attr: str, prefix: str) -> int:
    column = getattr(model, attr)
    pattern = re.compile(rf"{re.escape(prefix)}-([0-9]+)")
    values = [v for (v,) in db.query(column).filter(column.like(f"{prefix}-%")).all()]
    values += [getattr(o, attr, None) for o in db.new if isinstance(o, model)]
    highest = 0
    for value in values:
        m = pattern.fullmatch(value or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return highest


def _next_numbers(db: Session, model, attr: str, prefix: str, count: int) -> list:
    if count < 0:
        raise ValueError("count must not be negative")
    start = _highest_suffix(db, model, attr, prefix) + 1
    return [f"{prefix}-{start + i:0{CC_NUMBER_WIDTH}d}" for i in range(count)]


def next_cc_inward_number(db: Session) -> str:
    return _next_numbers(db, ContinuousCastingInward, "inward_number", CC_INWARD_PREFIX, 1)[0]


def next_cc_unit_number(db: Session) -> str:
    return _next_numbers(db, ContinuousCastingStockUnit, "unit_number", CC_UNIT_PREFIX, 1)[0]


def next_cc_unit_numbers(db: Session, count: int) -> list:
    """`count` consecutive unit numbers in one call -- for creating many units of one inward."""
    return _next_numbers(db, ContinuousCastingStockUnit, "unit_number", CC_UNIT_PREFIX, count)


def next_cc_allocation_number(db: Session) -> str:
    return _next_numbers(db, ContinuousCastingAllocation, "allocation_number", CC_ALLOCATION_PREFIX, 1)[0]


def next_cc_cut_number(db: Session) -> str:
    return _next_numbers(db, ContinuousCastingCutRecord, "cut_number", CC_CUT_PREFIX, 1)[0]


def next_cc_ledger_transaction_number(db: Session) -> str:
    return _next_numbers(db, ContinuousCastingStockLedger, "transaction_number", CC_LEDGER_PREFIX, 1)[0]


def next_cc_ledger_transaction_numbers(db: Session, count: int) -> list:
    """`count` consecutive ledger transaction numbers in one call (one ledger row per unit)."""
    return _next_numbers(db, ContinuousCastingStockLedger, "transaction_number", CC_LEDGER_PREFIX, count)
