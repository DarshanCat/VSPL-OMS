"""Continuous Casting material master (Phase 11A): create, read and (safe) update. No delete.

A material is the technical identity of continuous-casting stock -- code, grade, section and the primary /
secondary stock dimensions in whole millimetres. Engineering (and Admin) own it, because Engineering later
validates it against a WO routing. This module reuses the existing ContinuousCastingMaterial model; it does not
add a second material model, a revision system or lifecycle states beyond the existing is_active flag.

Update rules: a material that nothing references can be edited freely. Once any inward or any routing refers
to it, its IDENTITY (code, grade, section, dimensions) is frozen -- changing it would silently change what
historical stock and engineering validations meant -- while the description and is_active (deactivate /
reactivate) stay editable. Deactivation is safe: the existing inward rule already refuses an inactive material.

Each call is one atomic transaction that commits inside the service (so a future router stays thin). It writes
an audit row, no stock-ledger row and nothing in any OMS table. Reading is not role-restricted here: access
control for reads is the caller's authentication.
"""
from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.roles import CC_MATERIAL_MASTER_ROLES
from app.models.audit import AuditLog
from app.models.user import User
from app.models.continuous_casting import (
    ContinuousCastingMaterial, ContinuousCastingInward, ContinuousCastingRouting,
)
from app.schemas.continuous_casting import CCMaterialCreate, CCMaterialUpdate, CCMaterialResult, INT32_MAX
from app.services.continuous_casting_service import _require_role, _bad_request, _is_unique_violation
from app.services.continuous_casting_reservation_service import _lock

Material, Inward, Routing = ContinuousCastingMaterial, ContinuousCastingInward, ContinuousCastingRouting
IDENTITY_FIELDS = ("material_code", "grade", "section", "stock_dimension_a_mm", "stock_dimension_b_mm")
REQUIRED_FIELDS = ("material_code", "grade", "section", "stock_dimension_a_mm", "is_active")
TEXT_FIELDS = ("material_code", "grade", "section")
DIMENSION_FIELDS = ("stock_dimension_a_mm", "stock_dimension_b_mm")


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _bad_request(f"{label} is required.")
    cleaned = value.strip()
    if len(cleaned) > 100:
        raise _bad_request(f"{label} is too long (100 characters at most).")
    return cleaned


def _dimension(value, label: str, required: bool) -> Optional[int]:
    if value is None:
        if required:
            raise _bad_request(f"{label} is required.")
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > INT32_MAX:
        raise _bad_request(f"{label} must be a positive whole number of millimetres.")
    return value


def _description(value) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 500:
        raise _bad_request("description must be text of 500 characters at most.")
    return value.strip() or None


def _counts(db: Session, material_id) -> tuple:
    inwards = db.query(func.count(Inward.id)).filter(Inward.material_id == material_id).scalar()
    routings = db.query(func.count(Routing.id)).filter(Routing.validated_material_id == material_id).scalar()
    return int(inwards), int(routings)


def _result(material, inwards: int, routings: int, message: str) -> CCMaterialResult:
    return CCMaterialResult(
        success=True, material_id=str(material.id), material_code=material.material_code, grade=material.grade,
        section=material.section, stock_dimension_a_mm=material.stock_dimension_a_mm,
        stock_dimension_b_mm=material.stock_dimension_b_mm, description=material.description,
        is_active=material.is_active, referenced=bool(inwards or routings), inward_count=inwards,
        routing_count=routings, created_by=material.created_by, updated_by=material.updated_by, message=message,
    )


def _duplicate_code(db: Session, code: str, exclude_id=None) -> bool:
    query = db.query(Material.id).filter(func.lower(Material.material_code) == code.lower())
    if exclude_id is not None:
        query = query.filter(Material.id != exclude_id)
    return query.first() is not None


def _conflict(code: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT,
                         f"A material with code '{code}' already exists (codes are unique regardless of case); "
                         f"nothing was saved.")


def _atomic(db: Session, work):
    """Run `work`, commit, and roll everything back on any failure."""
    try:
        result = work()
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        if _is_unique_violation(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, "A material with this code already exists; nothing was saved.")
        raise _bad_request("The change violates a material integrity rule and was not saved.")
    except Exception:
        db.rollback()
        raise


def _create(db: Session, req: CCMaterialCreate, user: User) -> CCMaterialResult:
    code = _text(req.material_code, "material_code")
    grade = _text(req.grade, "grade")
    section = _text(req.section, "section")
    dim_a = _dimension(req.stock_dimension_a_mm, "stock_dimension_a_mm", True)
    dim_b = _dimension(req.stock_dimension_b_mm, "stock_dimension_b_mm", False)
    description = _description(req.description)
    if _duplicate_code(db, code):
        raise _conflict(code)
    actor = user.full_name
    material = Material(material_code=code, grade=grade, section=section, stock_dimension_a_mm=dim_a,
                        stock_dimension_b_mm=dim_b, description=description, is_active=True,
                        created_by=actor, updated_by=actor)
    db.add(material)
    db.flush()
    db.add(AuditLog(
        user_id=user.id, user_name=actor, action="CC_MATERIAL_CREATED", entity="ContinuousCastingMaterial",
        entity_id=code, new_value=f"{code}: grade {grade}, section {section}, {dim_a} x {dim_b} mm",
        details=description,
    ))
    db.flush()
    return _result(material, 0, 0, f"Material '{code}' created.")


def _update(db: Session, req: CCMaterialUpdate, user: User) -> CCMaterialResult:
    material = _lock(db, Material, req.material_id)                       # serialises concurrent edits
    if material is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Continuous casting material not found.")
    sent = set(getattr(req, "model_fields_set", set())) - {"material_id"}
    if not sent:
        raise _bad_request("Nothing to update: send at least one field.")
    unknown = sent - set(IDENTITY_FIELDS) - {"description", "is_active"}
    if unknown:
        raise _bad_request(f"Unknown field(s): {', '.join(sorted(unknown))}.")

    new_values = {}
    for name in sent:
        value = getattr(req, name)
        if name in REQUIRED_FIELDS and value is None:
            raise _bad_request(f"{name} cannot be cleared.")
        if name in TEXT_FIELDS:
            new_values[name] = _text(value, name)
        elif name == "stock_dimension_a_mm":
            new_values[name] = _dimension(value, name, True)
        elif name == "stock_dimension_b_mm":
            new_values[name] = _dimension(value, name, False)
        elif name == "description":
            new_values[name] = _description(value)
        else:
            if not isinstance(value, bool):
                raise _bad_request("is_active must be true or false.")
            new_values[name] = value
    changes = {name: (getattr(material, name), value) for name, value in new_values.items()
               if getattr(material, name) != value}
    if not changes:
        raise _bad_request("No changes: every value sent equals the current value.")

    inwards, routings = _counts(db, material.id)
    frozen = sorted(name for name in changes if name in IDENTITY_FIELDS)
    if (inwards or routings) and frozen:
        raise _bad_request(
            f"Material '{material.material_code}' is referenced by {inwards} inward(s) and {routings} routing(s); "
            f"its identity ({', '.join(frozen)}) can no longer be changed. Description and active status can.")
    if "material_code" in changes and _duplicate_code(db, changes["material_code"][1], exclude_id=material.id):
        raise _conflict(changes["material_code"][1])

    old_text = "; ".join(f"{name}={old}" for name, (old, _new) in sorted(changes.items()))
    new_text = "; ".join(f"{name}={new}" for name, (_old, new) in sorted(changes.items()))
    actor = user.full_name
    for name, (_old, new) in changes.items():
        setattr(material, name, new)
    material.updated_by = actor
    db.add(AuditLog(
        user_id=user.id, user_name=actor, action="CC_MATERIAL_UPDATED", entity="ContinuousCastingMaterial",
        entity_id=material.material_code, old_value=old_text, new_value=new_text,
    ))
    db.flush()
    return _result(material, inwards, routings, f"Material '{material.material_code}' updated.")


class ContinuousCastingMaterialService:
    """Create, read and update only. Deleting a material is deliberately not offered."""

    @staticmethod
    def create_material(db: Session, req: CCMaterialCreate, current_user: Optional[User] = None) -> CCMaterialResult:
        _require_role(current_user, CC_MATERIAL_MASTER_ROLES, "create a continuous-casting material")
        return _atomic(db, lambda: _create(db, req, current_user))

    @staticmethod
    def update_material(db: Session, req: CCMaterialUpdate, current_user: Optional[User] = None) -> CCMaterialResult:
        _require_role(current_user, CC_MATERIAL_MASTER_ROLES, "update a continuous-casting material")
        return _atomic(db, lambda: _update(db, req, current_user))

    @staticmethod
    def get_material(db: Session, material_id) -> CCMaterialResult:
        """Read one material (no role restriction; the caller's authentication governs reads)."""
        material = db.query(Material).filter(Material.id == material_id).first()
        if material is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Continuous casting material not found.")
        inwards, routings = _counts(db, material.id)
        return _result(material, inwards, routings, "OK")
