"""Tests for Continuous Casting Material Stock Summary API and Read Service."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import continuous_casting as cc
from app.models.user import User, UserRole
from app.services.continuous_casting_read_service import ContinuousCastingReadService
from app.services.continuous_casting_material_service import ContinuousCastingMaterialService
from app.services.continuous_casting_service import ContinuousCastingInwardService
from app.schemas.continuous_casting import CCMaterialCreate, CCInwardCreate

SPECS = [
    {"material_code": "CC-01", "grade": "SG 500/7", "dim_a": 86, "dim_b": 96, "section": "RECTANGLE", "pcs": 105, "wt_per_mtr": 59.86, "nw_kgs": 6284.88, "desc": "Ductile Cast Iron Bar 86x96 mm (SG 500/7)"},
    {"material_code": "CC-02", "grade": "65-45-12", "dim_a": 95, "dim_b": 100, "section": "RECTANGLE", "pcs": 18, "wt_per_mtr": 68.88, "nw_kgs": 1239.75, "desc": "Ductile Cast Iron Bar 95x100 mm (65-45-12)"},
    {"material_code": "CC-03", "grade": "65-45-12", "dim_a": 55, "dim_b": 55, "section": "SQUARE", "pcs": 12, "wt_per_mtr": 21.93, "nw_kgs": 263.18, "desc": "Ductile Cast Iron Square Bar 55x55 mm (65-45-12)"},
    {"material_code": "CC-04", "grade": "65-45-12", "dim_a": 70, "dim_b": 70, "section": "SQUARE", "pcs": 9, "wt_per_mtr": 35.53, "nw_kgs": 319.73, "desc": "Ductile Cast Iron Square Bar 70x70 mm (65-45-12)"},
    {"material_code": "CC-05", "grade": "65-45-12", "dim_a": 45, "dim_b": 75, "section": "RECTANGLE", "pcs": 21, "wt_per_mtr": 24.47, "nw_kgs": 513.84, "desc": "Ductile Cast Iron Flat Bar 45x75 mm (65-45-12)"},
    {"material_code": "CC-06", "grade": "65-45-12", "dim_a": 80, "dim_b": 80, "section": "SQUARE", "pcs": 9, "wt_per_mtr": 46.40, "nw_kgs": 417.60, "desc": "Ductile Cast Iron Square Bar 80x80 mm (65-45-12)"},
    {"material_code": "CC-07", "grade": "65-45-12", "dim_a": 120, "dim_b": 140, "section": "RECTANGLE", "pcs": 18, "wt_per_mtr": 121.80, "nw_kgs": 2192.40, "desc": "Ductile Cast Iron Rectangular Bar 120x140 mm (65-45-12)"},
    {"material_code": "CC-08", "grade": "65-45-12", "dim_a": 115, "dim_b": 155, "section": "RECTANGLE", "pcs": 15, "wt_per_mtr": 129.23, "nw_kgs": 1938.47, "desc": "Ductile Cast Iron Rectangular Bar 115x155 mm (65-45-12)"},
    {"material_code": "CC-09", "grade": "65-45-12", "dim_a": 145, "dim_b": 195, "section": "RECTANGLE", "pcs": 9, "wt_per_mtr": 204.99, "nw_kgs": 1844.94, "desc": "Ductile Cast Iron Rectangular Bar 145x195 mm (65-45-12)"},
    {"material_code": "CC-10", "grade": "65-45-12", "dim_a": 125, "dim_b": 135, "section": "RECTANGLE", "pcs": 9, "wt_per_mtr": 122.34, "nw_kgs": 1101.09, "desc": "Ductile Cast Iron Rectangular Bar 125x135 mm (65-45-12)"},
    {"material_code": "CC-11", "grade": "65-45-12", "dim_a": 55, "dim_b": 75, "section": "RECTANGLE", "pcs": 9, "wt_per_mtr": 29.91, "nw_kgs": 269.16, "desc": "Ductile Cast Iron Flat Bar 55x75 mm (65-45-12)"},
    {"material_code": "CC-12", "grade": "65-45-12", "dim_a": 100, "dim_b": 115, "section": "RECTANGLE", "pcs": 9, "wt_per_mtr": 83.38, "nw_kgs": 750.38, "desc": "Ductile Cast Iron Rectangular Bar 100x115 mm (65-45-12)"},
    {"material_code": "CC-13", "grade": "65-45-12", "dim_a": 175, "dim_b": 175, "section": "SQUARE", "pcs": 9, "wt_per_mtr": 222.03, "nw_kgs": 1998.28, "desc": "Ductile Cast Iron Square Bar 175x175 mm (65-45-12)"},
    {"material_code": "CC-14", "grade": "65-45-12", "dim_a": 160, "dim_b": 205, "section": "RECTANGLE", "pcs": 12, "wt_per_mtr": 237.80, "nw_kgs": 2853.60, "desc": "Ductile Cast Iron Rectangular Bar 160x205 mm (65-45-12)"},
    {"material_code": "CC-15", "grade": "65-45-12", "dim_a": 210, "dim_b": 220, "section": "RECTANGLE", "pcs": 9, "wt_per_mtr": 334.95, "nw_kgs": 3014.55, "desc": "Ductile Cast Iron Rectangular Bar 210x220 mm (65-45-12)"},
]


@pytest.fixture()
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def populated_db(test_db):
    user = User(full_name="Admin User", email="admin@example.test", hashed_password="x", role=UserRole.ADMIN, is_active=True)
    test_db.add(user)
    test_db.commit()

    for s in SPECS:
        m = ContinuousCastingMaterialService.create_material(
            test_db,
            CCMaterialCreate(
                material_code=s["material_code"],
                grade=s["grade"],
                section=s["section"],
                stock_dimension_a_mm=s["dim_a"],
                stock_dimension_b_mm=s["dim_b"],
                description=s["desc"],
            ),
            current_user=user,
        )

        ContinuousCastingInwardService.create_inward(
            test_db,
            CCInwardCreate(
                material_id=m.material_id,
                unit_lengths_mm=[1000] * s["pcs"],
                grn_reference="VSPL Q3 DUCTILE CAST IRON BAR",
                location="vspl f1",
                remarks=f"Opening stock: {s['dim_a']}*{s['dim_b']}*1000 mm | {s['pcs']} bars | Wt/Mtr: {s['wt_per_mtr']} kg/m | N.W.: {s['nw_kgs']:.2f} kg",
            ),
            current_user=user,
        )

    return test_db


def test_stock_summary_all_15_materials(populated_db):
    res = ContinuousCastingReadService.list_material_stock_summary(populated_db, limit=50)
    assert res.total == 15
    assert len(res.items) == 15

    # Check CC-01 details
    cc01 = next(item for item in res.items if item.material_code == "CC-01")
    assert cc01.grade == "SG 500/7"
    assert cc01.section == "RECTANGLE"
    assert cc01.size_display == "86×96×1000 mm"
    assert cc01.unit_count == 105
    assert cc01.total_length_mm == 105000
    assert cc01.documented_weight_kg == 6284.88
    assert cc01.status == "IN_STOCK"

    # Check CC-14
    cc14 = next(item for item in res.items if item.material_code == "CC-14")
    assert cc14.grade == "65-45-12"
    assert cc14.unit_count == 12
    assert cc14.total_length_mm == 12000
    assert cc14.documented_weight_kg == 2853.60

    # Check CC-15
    cc15 = next(item for item in res.items if item.material_code == "CC-15")
    assert cc15.grade == "65-45-12"
    assert cc15.unit_count == 9
    assert cc15.total_length_mm == 9000
    assert cc15.documented_weight_kg == 3014.55

    # Check Totals (authoritative document reconciliation)
    assert res.totals.total_bars == 273
    assert res.totals.total_length_mm == 273000
    assert res.totals.total_weight_kg == 25001.85


def test_stock_summary_filtering(populated_db):
    # Grade filter SG 500/7
    res_sg = ContinuousCastingReadService.list_material_stock_summary(populated_db, grade="SG 500/7")
    assert res_sg.total == 1
    assert res_sg.items[0].material_code == "CC-01"
    assert res_sg.totals.total_bars == 105
    assert res_sg.totals.total_weight_kg == 6284.88

    # Grade filter 65-45-12
    res_65 = ContinuousCastingReadService.list_material_stock_summary(populated_db, grade="65-45-12")
    assert res_65.total == 14
    assert res_65.totals.total_bars == 168
    assert res_65.totals.total_weight_kg == 18716.97

    # Search filter CC-01
    res_search = ContinuousCastingReadService.list_material_stock_summary(populated_db, search="CC-01")
    assert res_search.total == 1
    assert res_search.items[0].material_code == "CC-01"

    # Location filter
    res_loc = ContinuousCastingReadService.list_material_stock_summary(populated_db, location="vspl f1")
    assert res_loc.total == 15
    assert res_loc.totals.total_bars == 273


def test_stock_summary_no_duplicates(populated_db):
    res = ContinuousCastingReadService.list_material_stock_summary(populated_db, limit=100)
    codes = [item.material_code for item in res.items]
    assert len(codes) == 15
    assert len(set(codes)) == 15
