"""Tests for Continuous Casting Planning Requirement Card calculations and stock sufficiency."""
import math
import pytest
from app.services.continuous_casting_routing_service import (
    calculate_blank_length_mm,
    calculate_gross_required_length_mm,
    calculate_cross_section_area_mm2,
    calculate_weight_per_mm_kg,
    calculate_net_blank_weight_kg,
    calculate_net_blank_weight_total_kg,
    calculate_gross_material_weight_kg,
    DENSITY_CAST_IRON_KG_MM3,
)


def test_blank_length_calculation():
    # Finished axial 127mm + 5mm Face A + 5mm Face B = 137mm
    blank = calculate_blank_length_mm(127, 5, 5)
    assert blank == 137


def test_gross_required_length_calculation():
    # 19 blanks @ 137mm + 19 cuts @ 4mm kerf + 30mm trim = 2603 + 76 + 30 = 2709mm
    gross = calculate_gross_required_length_mm(19, 137, 19, 4, 30)
    assert gross == 2709


def test_rectangular_section_geometry_and_weight():
    # Material CC-14: 160 x 205 mm rectangular bar
    dim_a, dim_b = 160, 205
    area = calculate_cross_section_area_mm2("RECTANGLE", dim_a, dim_b)
    assert area == 32800.0

    weight_per_mm = calculate_weight_per_mm_kg("RECTANGLE", dim_a, dim_b)
    # 32800 * 7.2e-6 = 0.23616 kg/mm
    assert pytest.approx(weight_per_mm, 0.00001) == 0.23616

    # Net blank weight for 137mm blank
    net_blank_wt = calculate_net_blank_weight_kg(137, "RECTANGLE", dim_a, dim_b)
    assert net_blank_wt == 32.35

    # Net blank weight total for 19 blanks (using full precision intermediate: 19 * 32.35392 kg = 614.72448 kg -> 614.72 kg)
    net_total_wt = calculate_net_blank_weight_total_kg(19, 137, "RECTANGLE", dim_a, dim_b)
    assert net_total_wt == 614.72

    # Gross material weight for 2700mm
    gross_mat_wt = calculate_gross_material_weight_kg(2700, "RECTANGLE", dim_a, dim_b)
    assert gross_mat_wt == 637.63


def test_round_section_geometry_and_weight():
    # Round bar Ø 210 mm
    diameter = 210
    area = calculate_cross_section_area_mm2("ROUND", diameter)
    expected_area = math.pi * (105.0 ** 2)
    assert pytest.approx(area, 0.01) == expected_area

    weight_per_mm = calculate_weight_per_mm_kg("ROUND", diameter)
    assert pytest.approx(weight_per_mm, 0.0001) == expected_area * 7.2e-6

    # Net blank weight for 135mm blank
    net_blank_wt = calculate_net_blank_weight_kg(135, "ROUND", diameter)
    assert net_blank_wt == 33.67

    # Net total for 19 blanks (using full precision intermediate: 19 * 33.66625 kg = 639.6588 kg -> 639.66 kg)
    net_total_wt = calculate_net_blank_weight_total_kg(19, 135, "ROUND", diameter)
    assert net_total_wt == 639.66


def test_square_section_geometry():
    # Square bar 70 x 70 mm
    area = calculate_cross_section_area_mm2("SQUARE", 70)
    assert area == 4900.0

    weight_per_mm = calculate_weight_per_mm_kg("SQUARE", 70)
    assert pytest.approx(weight_per_mm, 0.00001) == 4900.0 * 7.2e-6


def test_stock_sufficiency_and_shortage_logic():
    gross_req = 2700
    allocated = 3000
    available_stock = 9000

    # Case 1: Fully allocated -> SUFFICIENT, shortage = 0
    rem_req = max(0, gross_req - allocated)
    assert rem_req == 0
    is_sufficient = (allocated >= gross_req) or (available_stock >= rem_req)
    assert is_sufficient is True
    shortage = 0 if is_sufficient else (rem_req - available_stock)
    assert shortage == 0

    # Case 2: Partial allocation (1000mm) with sufficient free inventory (5000mm)
    allocated_2 = 1000
    rem_req_2 = gross_req - allocated_2  # 1700mm
    is_sufficient_2 = (allocated_2 >= gross_req) or (available_stock >= rem_req_2)
    assert is_sufficient_2 is True
    assert (0 if is_sufficient_2 else (rem_req_2 - available_stock)) == 0

    # Case 3: Shortage: Required 2700mm, Allocated 0mm, Available only 1500mm -> SHORT by 1200mm
    available_low = 1500
    allocated_3 = 0
    rem_req_3 = gross_req - allocated_3
    is_sufficient_3 = (allocated_3 >= gross_req) or (available_low >= rem_req_3)
    assert is_sufficient_3 is False
    shortage_3 = rem_req_3 - available_low
    assert shortage_3 == 1200
