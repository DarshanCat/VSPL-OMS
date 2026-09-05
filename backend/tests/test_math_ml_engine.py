"""
VSPL SMES + OMS - Comprehensive Mathematical Engine, ML Architecture & End-to-End Simulation Tests

Covers:
1. Pure Mathematical KPI Functions (Achievement, Yield, Rejection Rate, Velocity, Takt Time, OEE, Balances, Variance)
2. Zero-Division & Edge-Case Safety
3. Feature Engineering & Validation Pipeline
4. Modular ML Models (Delay, Rejection Risk, Bottleneck, Forecasting, Anomaly Detection)
5. Model Governance & Insufficient Data Handling
6. Model Feedback Loop Tracking
7. Required End-to-End Simulation: TEST-WO-001 (OAR -> WO -> Release -> F1(50+50) -> F2(50 + 40/10) -> F3 -> FI -> PACKING -> DISPATCH -> Conservation of Mass & Reconciliation)
8. Analytics REST API Endpoints Verification
"""

import pytest
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.main import app
from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole
from app.models.order import Order, Part, Customer, OrderStatus
from app.models.work_order import WorkOrder, WORoute, WOStatus
from app.models.production_movement import ProductionMovement, StageWIP
from app.models.packing import PackingRecord
from app.models.dispatch import Dispatch
from app.models.nc import NCRecord

from app.analytics.math_engine import (
    safe_div,
    production_achievement,
    rejection_rate,
    stage_completion_pct,
    yield_pct,
    wip_trend,
    production_velocity,
    cycle_time_hours,
    takt_time,
    oee_proxy,
    stage_result_balance,
    reconciliation_variance
)
from app.analytics.feature_engineering import (
    validate_movement_record,
    extract_wo_features,
    extract_stage_features,
    extract_time_features,
    build_historical_movement_dataset
)
from app.analytics.ml_models import (
    ModelGovernance,
    DelayPredictionModel,
    RejectionRiskModel,
    BottleneckPredictionModel,
    ProductionForecastingModel,
    AnomalyDetectionModel
)
from app.analytics.pipeline import MLPipelineCoordinator
from app.services.production_service import ProductionService
from app.services.packing_service import PackingService
from app.services.dispatch_service import DispatchService
from app.services.oms_integration_service import OMSIntegrationService
from app.schemas.production import MovePartsRequest
from app.schemas.packing import PackingUpdateRequest
from app.schemas.dispatch import DispatchRequest

# Isolated SQLite database for rapid test execution
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module")
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed Admin and Operators
    admin = User(
        email="admin.math@vspl.com",
        hashed_password=hash_password("admin123"),
        full_name="Math Engine Admin",
        role=UserRole.ADMIN,
        employee_id="ADM-MTH",
        department="Analytics & AI"
    )
    db.add(admin)

    cust = Customer(customer_code="CUST-TURBINE", name="GE Power India Ltd")
    part = Part(part_number="BRZ-SEAL-500", grade="AB2 / CuAl10Fe5Ni5", description="Heavy Duty Marine Seal")
    db.add(cust)
    db.add(part)
    db.commit()

    yield db
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="module")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def auth_headers(db_session):
    token = create_access_token({"sub": "admin.math@vspl.com", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


# =========================================================================
# 1. PURE MATHEMATICAL KPI ENGINE UNIT TESTS
# =========================================================================

def test_math_engine_pure_functions():
    # Achievement
    assert production_achievement(90, 100) == 90.0
    assert production_achievement(150, 100) == 150.0
    assert production_achievement(0, 100) == 0.0
    assert production_achievement(50, 0) == 0.0  # Zero safe

    # Rejection Rate
    assert rejection_rate(10, 100) == 10.0
    assert rejection_rate(0, 100) == 0.0
    assert rejection_rate(5, 0) == 0.0  # Zero safe

    # Stage Completion %
    assert stage_completion_pct(90, 100) == 90.0
    assert stage_completion_pct(120, 100) == 100.0  # Capped at 100%

    # Yield %
    assert yield_pct(95, 100) == 95.0
    assert yield_pct(0, 0) == 100.0

    # WIP Trend
    assert wip_trend(250, 200) == 50.0
    assert wip_trend(150, 200) == -50.0

    # Production Velocity
    assert production_velocity(100, 4.0) == 25.0
    assert production_velocity(100, 0.0) == 0.0

    # Takt Time
    assert takt_time(28800, 400) == 72.0  # 8 hours for 400 units = 72s / unit
    assert takt_time(28800, 0) == 0.0

    # OEE Proxy
    assert oee_proxy(90.0, 90.0, 90.0) == 72.9
    assert oee_proxy(100.0, 100.0, 100.0) == 100.0

    # Stage Result Balance
    bal = stage_result_balance(100, 90, 10)
    assert bal["in_process_qty"] == 0
    assert bal["total_processed"] == 100
    assert bal["is_balanced"] is True

    # Partial balance
    partial_bal = stage_result_balance(100, 40, 10)
    assert partial_bal["in_process_qty"] == 50
    assert partial_bal["is_balanced"] is True

    # Conservation of Mass / Reconciliation Variance
    assert reconciliation_variance(1000, 500, 400, 100) == 0
    assert reconciliation_variance(1000, 500, 400, 50) == 50  # 50 unallocated


# =========================================================================
# 2. FEATURE ENGINEERING & VALIDATION TESTS
# =========================================================================

def test_feature_engineering_validation(db_session):
    # Time features
    dt = datetime(2026, 9, 2, 10, 30)
    tf = extract_time_features(dt)
    assert tf["hour_of_day"] == 10
    assert tf["shift_name"] == "Shift A (Morning)"
    assert tf["is_weekend"] is False

    # Movement validation
    mov_valid = ProductionMovement(
        movement_id="MOV-TEST-1",
        work_order_id="00000000-0000-0000-0000-000000000001",
        from_stage="F1",
        to_stage="F2",
        quantity_moved=50,
        rejected_quantity=0
    )
    is_v, msg = validate_movement_record(mov_valid)
    assert is_v is True

    mov_invalid = ProductionMovement(
        movement_id="MOV-TEST-2",
        work_order_id="00000000-0000-0000-0000-000000000001",
        from_stage="F1",
        to_stage="F2",
        quantity_moved=-10,
        rejected_quantity=0
    )
    is_v, msg = validate_movement_record(mov_invalid)
    assert is_v is False


# =========================================================================
# 3. MODULAR ML & STATISTICAL INTELLIGENCE MODELS
# =========================================================================

def test_ml_models_and_governance():
    # 1. Delay Prediction Model
    wo_feats = {
        "physical_wo_qty": 200,
        "alloy_complexity": 1.45,
        "current_stage_idx": 1,
        "route_length": 6,
        "days_to_deadline": 2
    }
    pred_delay = DelayPredictionModel.predict(wo_feats, historical_samples_count=25)
    assert pred_delay["governance"]["status"] == "TRAINED"
    assert pred_delay["governance"]["is_prediction"] is True
    assert pred_delay["delay_probability_pct"] is not None
    assert pred_delay["risk_level"] in ("HIGH", "CRITICAL", "AMBER")

    # 2. Insufficient Data Handling (Strict Requirement)
    pred_insufficient = DelayPredictionModel.predict(wo_feats, historical_samples_count=1)
    assert pred_insufficient["governance"]["status"] == "INSUFFICIENT_DATA"
    assert pred_insufficient["delay_probability_pct"] is None
    assert "Insufficient" in pred_insufficient["reason"]

    # 3. Rejection Risk Model
    pred_rej = RejectionRiskModel.predict(
        part_grade="AB2 / CuAl10Fe5Ni5",
        stage="F1",
        machine_id="M-CC01",
        quantity=100,
        historical_samples_count=20
    )
    assert pred_rej["governance"]["status"] == "TRAINED"
    assert pred_rej["predicted_rejection_rate_pct"] > 0
    assert pred_rej["expected_rejection_qty"] >= 1
    assert pred_rej["probable_defect_code"] == "DEF-POROSITY"

    # 4. Bottleneck Detection
    stage_wips = {"F1": 50, "F2": 600, "F3": 100, "FI": 20}
    b_res = BottleneckPredictionModel.analyze_stages(stage_wips)
    assert b_res["primary_bottleneck_stage"] == "F2"
    assert b_res["stage_breakdown"][0]["bottleneck_risk"] == "CRITICAL"

    # 5. Production Forecasting
    daily_hist = [120.0, 140.0, 150.0, 160.0, 175.0, 190.0, 205.0]
    fc = ProductionForecastingModel.forecast(daily_hist, forecast_days=7)
    assert fc["governance"]["status"] == "TRAINED"
    assert fc["trend_direction"] == "RISING"
    assert len(fc["forecast_points"]) == 7

    # 6. Anomaly Detection
    sample_movs = [
        {"from_stage": "F1", "quantity_moved": 40, "rejected_quantity": 25, "wo_number": "WO-999", "machine_id": "M-CC01"}
    ]
    anom = AnomalyDetectionModel.scan_movement_anomalies(sample_movs, stage_wips)
    assert anom["total_anomalies_detected"] >= 1
    assert any(a["anomaly_type"] == "SCRAP_RATE_SPIKE" for a in anom["anomaly_alerts"])


# =========================================================================
# 4. REQUIRED END-TO-END FACTORY SIMULATION: TEST-WO-001
# =========================================================================

def test_e2e_simulation_test_wo_001(db_session, client, auth_headers):
    """
    Simulates the exact requested operational flow:
    1. Create OAR
    2. Create & Release Work Order TEST-WO-001 (Qty = 100)
    3. Apply OMS Target & Route: F1 -> F2 -> F3 -> FI -> PACKING -> DISPATCH
    4. F1 -> F2: Move 50 (Tx 1)
    5. F1 -> F2: Move 50 (Tx 2)
    6. Verify F1 available = 0, F2 available = 100
    7. F2 -> F3: Move 50 (Tx 3)
    8. F2: Process remaining 50 with OK = 40, Rej = 10 (Tx 4: Move 40 to F3 with 10 Rej)
    9. Verify stage-wise results: F2 OK = 90, F2 Rej = 10 (Separate, non-generic)
    10. Verify NO cumulative live quantity error
    11. F3 -> FI: Move 90 (Tx 5)
    12. FI -> PACKING: Move 90 (Tx 6)
    13. PACKING: Pack 90 pieces
    14. DISPATCH: Ship 90 pieces (Invoice INV-TEST-001)
    15. Verify Over-dispatch is blocked
    16. Verify 100% Conservation of Mass / Plant Reconciliation (Variance = 0)
    """
    cust = db_session.query(Customer).first()
    part = db_session.query(Part).first()

    # 1. Create OAR
    order = Order(
        oar_number="OAR-TEST-001",
        customer_id=cust.id,
        part_id=part.id,
        customer_po="PO-TEST-001",
        po_qty=100,
        max_batch_size=100,
        delivery_date=date.today() + timedelta(days=10),
        order_type="Standard",
        status=OrderStatus.ACCEPT
    )
    db_session.add(order)
    db_session.commit()

    # 2. Create & Release Work Order
    wo = WorkOrder(
        wo_number="TEST-WO-001",
        order_id=order.id,
        physical_wo_qty=100,
        current_stage="F1",
        projected_final_good=100,
        shortfall="No",
        status=WOStatus.RELEASED,
        released_by="Production Planner",
        release_date=datetime.now()
    )
    db_session.add(wo)
    db_session.commit()

    # 3. Create Dynamic Route: F1 -> F2 -> F3 -> FI -> PACKING -> DISPATCH
    route_stages = ["F1", "F2", "F3", "FI", "PACKING", "DISPATCH"]
    for seq, stg in enumerate(route_stages, start=1):
        r = WORoute(
            work_order_id=wo.id,
            stage=stg,
            sequence=seq,
            stage_target_qty=100,
            cumulative_ent_qty=100 if seq == 1 else 0,
            stage_status="In-Progress" if seq == 1 else "Pending"
        )
        db_session.add(r)
        
        wip = StageWIP(
            work_order_id=wo.id,
            stage=stg,
            ent_qty=100 if seq == 1 else 0,
            ok_qty=0,
            inproc_qty=100 if seq == 1 else 0,
            onhand_qty=0,
            rejected_qty=0,
            received_qty=100 if seq == 1 else 0,
            available_wip=100 if seq == 1 else 0,
            moved_out_qty=0
        )
        db_session.add(wip)
    db_session.commit()

    # 4. F1 -> F2: Move 50 (Tx 1)
    res1 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="TEST-WO-001",
        from_stage="F1",
        to_stage="F2",
        quantity_moved=50,
        rejected_quantity=0,
        machine_id="M-CC01",
        operator_name="Operator 1",
        shift="Shift A",
        client_request_id="REQ-E2E-001"
    ))
    assert res1.success is True
    assert res1.available_wip_remaining == 50
    assert res1.to_stage_available_wip == 50

    # 5. F1 -> F2: Move 50 (Tx 2 - Partial Movement)
    res2 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="TEST-WO-001",
        from_stage="F1",
        to_stage="F2",
        quantity_moved=50,
        rejected_quantity=0,
        machine_id="M-CC01",
        operator_name="Operator 1",
        shift="Shift A",
        client_request_id="REQ-E2E-002"
    ))
    assert res2.success is True
    assert res2.available_wip_remaining == 0
    assert res2.to_stage_available_wip == 100

    # 6. F2 -> F3: Move 50 (Tx 3)
    res3 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="TEST-WO-001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=50,
        rejected_quantity=0,
        machine_id="M-LATHE-01",
        operator_name="Operator 2",
        shift="Shift B",
        client_request_id="REQ-E2E-003"
    ))
    assert res3.success is True
    assert res3.available_wip_remaining == 50
    assert res3.to_stage_available_wip == 50

    # 7. F2: Process remaining 50 with OK = 40, Rejection = 10 (Tx 4)
    res4 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="TEST-WO-001",
        from_stage="F2",
        to_stage="F3",
        quantity_moved=40,
        rejected_quantity=10,
        machine_id="M-LATHE-01",
        operator_name="Operator 2",
        shift="Shift B",
        defect_code="DEF-POROSITY",
        remarks="Subsurface porosity on turning",
        client_request_id="REQ-E2E-004"
    ))
    assert res4.success is True
    assert res4.available_wip_remaining == 0
    assert res4.to_stage_available_wip == 90  # 50 + 40 = 90 OK at F3

    # 8. Verify Stage-wise Isolation: F2 OK = 90, F2 Rejection = 10
    f2_wip = db_session.query(StageWIP).filter(StageWIP.work_order_id == wo.id, StageWIP.stage == "F2").first()
    assert f2_wip.ok_qty == 90
    assert f2_wip.rejected_qty == 10
    assert f2_wip.available_wip == 0

    # Verify NC was automatically raised for F2 rejection
    f2_nc = db_session.query(NCRecord).filter(NCRecord.work_order_id == wo.id, NCRecord.stage == "F2").first()
    assert f2_nc is not None
    assert f2_nc.qty == 10
    assert f2_nc.defect_code == "DEF-POROSITY"

    # 9. F3 -> FI: Move 90 (Tx 5)
    res5 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="TEST-WO-001",
        from_stage="F3",
        to_stage="FI",
        quantity_moved=90,
        rejected_quantity=0,
        machine_id="M-VMC-01",
        operator_name="Operator 3",
        shift="Shift A",
        client_request_id="REQ-E2E-005"
    ))
    assert res5.success is True
    assert res5.to_stage_available_wip == 90

    # 10. FI -> PACKING: Move 90 (Tx 6)
    res6 = ProductionService.move_parts(db_session, MovePartsRequest(
        wo_number="TEST-WO-001",
        from_stage="FI",
        to_stage="PACKING",
        quantity_moved=90,
        rejected_quantity=0,
        machine_id="M-INSPECT-01",
        operator_name="QA Lead",
        shift="Shift A",
        client_request_id="REQ-E2E-006"
    ))
    assert res6.success is True

    # 11. Packing Record Verification
    p_rec = db_session.query(PackingRecord).filter(PackingRecord.work_order_id == wo.id).first()
    assert p_rec is not None
    assert p_rec.fi_approved_qty == 90

    # Pack 90 pieces
    pack_res = PackingService.update_packing(db_session, PackingUpdateRequest(
        wo_number="TEST-WO-001",
        packed_quantity=90,
        box_count=3,
        package_type="Wooden Crate with VCI",
        remarks="Packed and verified"
    ))
    assert pack_res.ready_for_dispatch == 90
    db_session.refresh(p_rec)
    assert p_rec.status == "Ready-for-Dispatch"

    # 12. Dispatch Gatekeeper: Over-dispatch protection (Try 100 > 90)
    with pytest.raises(Exception):
        DispatchService.execute_dispatch(db_session, DispatchRequest(
            wo_number="TEST-WO-001",
            invoice_number="INV-FAIL-001",
            dispatched_quantity=100
        ))

    # Valid Dispatch of 90 pieces
    disp_res = DispatchService.execute_dispatch(db_session, DispatchRequest(
        wo_number="TEST-WO-001",
        invoice_number="INV-TEST-001",
        dispatched_quantity=90,
        vehicle_number="KA-01-EA-9999",
        transporter="VRL Logistics",
        remarks="Dispatched to GE Power"
    ))
    assert disp_res.dispatched_quantity == 90
    assert disp_res.wo_status == "dispatched"

    # 13. Authoritative Conservation of Mass / Plant Reconciliation
    recon = OMSIntegrationService.reconcile_work_order(db_session, wo)
    assert recon.released_qty == 100
    assert recon.total_rejected == 10
    assert recon.dispatched_qty == 90
    assert recon.total_wip == 0
    assert recon.variance == 0
    assert recon.is_balanced is True


# =========================================================================
# 5. REST API ENDPOINTS INTEGRATION TESTS
# =========================================================================

def test_analytics_api_endpoints(client, auth_headers):
    # 1. Plant KPIs
    r_kpi = client.get("/api/v1/analytics/kpis/plant", headers=auth_headers)
    assert r_kpi.status_code == 200
    data_kpi = r_kpi.json()
    assert "overall_achievement_pct" in data_kpi
    assert "overall_yield_pct" in data_kpi
    assert "total_plant_wip" in data_kpi

    # 2. Work Order Specific KPIs
    r_wo_kpi = client.get("/api/v1/analytics/kpis/work-order/TEST-WO-001", headers=auth_headers)
    assert r_wo_kpi.status_code == 200
    data_wo = r_wo_kpi.json()
    assert data_wo["wo_number"] == "TEST-WO-001"
    assert data_wo["overall_yield_pct"] == 90.0  # 90 Good / 100 Input
    assert data_wo["total_scrap_qty"] == 10

    # 3. Delay Prediction
    r_delay = client.post("/api/v1/analytics/predictions/delay", json={"wo_number": "TEST-WO-001"}, headers=auth_headers)
    assert r_delay.status_code == 200
    data_delay = r_delay.json()
    assert "governance" in data_delay
    assert data_delay["governance"]["is_prediction"] is True

    # 4. Rejection Prediction
    r_rej = client.post("/api/v1/analytics/predictions/rejection", json={"wo_number": "TEST-WO-001", "target_stage": "F1"}, headers=auth_headers)
    assert r_rej.status_code == 200
    data_rej = r_rej.json()
    assert "predicted_rejection_rate_pct" in data_rej

    # 5. Bottleneck Prediction
    r_bot = client.get("/api/v1/analytics/predictions/bottlenecks", headers=auth_headers)
    assert r_bot.status_code == 200
    data_bot = r_bot.json()
    assert "stage_breakdown" in data_bot

    # 6. Production Forecast
    r_fc = client.get("/api/v1/analytics/forecasts/production?days=7", headers=auth_headers)
    assert r_fc.status_code == 200
    data_fc = r_fc.json()
    assert len(data_fc["forecast_points"]) == 7

    # 7. Anomaly Scan
    r_anom = client.get("/api/v1/analytics/anomalies", headers=auth_headers)
    assert r_anom.status_code == 200
    data_anom = r_anom.json()
    assert "total_anomalies_detected" in data_anom

    # 8. Model Governance
    r_gov = client.get("/api/v1/analytics/models/governance", headers=auth_headers)
    assert r_gov.status_code == 200
    data_gov = r_gov.json()
    assert len(data_gov["registered_models"]) == 5

    # 9. Prediction Feedback
    r_fbk = client.post("/api/v1/analytics/feedback", json={
        "wo_number": "TEST-WO-001",
        "model_name": "VSPL-Delay-Risk-Predictor",
        "predicted_outcome": {"risk": "HIGH"},
        "actual_outcome": {"completed_on_time": True},
        "notes": "Fast-tracked by manager"
    }, headers=auth_headers)
    assert r_fbk.status_code == 200
    assert r_fbk.json()["success"] is True
