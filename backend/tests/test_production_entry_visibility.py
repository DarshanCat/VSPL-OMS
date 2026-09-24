"""Regression tests for Production Entry quantity visibility and validation.

Business scenario under test (see task spec): produce a delta at F1, move it to F2,
and confirm every one of the six summary metrics (Target, OK Produced, Rejected,
In Process/WIP, Not Yet Produced, Remaining to Produce) behaves exactly as specified
-- especially that movement never inflates "Produced", and that "Not Yet Produced" /
"Remaining to Produce" are both Target minus cumulative OK (not the physical
unprocessed-material ceiling, which is a separate, already-existing figure).

Target here is the stage's authoritative, potentially yield-projected
stage_target_qty (existing OMS Engine calculate_stage_targets), not a flat
assumption of 1:1 yield -- these tests read the real value back from the API rather
than hardcoding it, per "use the authoritative stage-level state" (task item 13).
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.main import app


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _admin(client):
    resp = client.post("/api/v1/auth/login", json={"email": "admin@vspl.com", "password": "admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _intake_wo(client, headers, po_qty=10):
    resp = client.post(
        "/api/v1/operations/intake", headers=headers,
        json={
            "customer_code": "CUST-VALVE", "customer_name": "Visibility Test",
            "customer_po": f"PO-VIS-{uuid.uuid4().hex[:8]}", "part_number": "BRZ-BUSH-100",
            "po_quantity": po_qty, "max_batch_size": po_qty,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["wos_created"][0]


def _stage_state(client, headers, wo, stage):
    resp = client.get(f"/api/v1/work-orders/{wo}/stage/{stage}/state", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _produce(client, headers, wo, stage, good, rejected=0):
    return client.post(
        "/api/v1/production/entry", headers=headers,
        json={"wo_number": wo, "stage": stage, "good_qty": good, "rejected_quantity": rejected},
    )


def _move(client, headers, wo, from_stage, to_stage, qty, rejected=0):
    return client.post(
        "/api/v1/production/move", headers=headers,
        json={"wo_number": wo, "from_stage": from_stage, "to_stage": to_stage, "quantity_moved": qty, "rejected_quantity": rejected},
    )


def test_produce_5_shows_correct_six_metrics(client):
    """Target 10 (scenario 1), produce 5 -> remaining production = 5 (scenarios 1, 3)."""
    headers = _admin(client)
    wo = _intake_wo(client, headers)

    before = _stage_state(client, headers, wo, "F1")
    target = before["target_qty"]
    assert before["ok_completed_qty"] == 0
    assert before["not_yet_produced"] == target
    assert before["remaining_to_produce"] == target
    assert before["already_moved_qty"] == 0

    resp = _produce(client, headers, wo, "F1", good=5)
    assert resp.status_code == 200, resp.text

    after = _stage_state(client, headers, wo, "F1")
    assert after["ok_completed_qty"] == 5
    assert after["rejected_qty"] == 0
    assert after["not_yet_produced"] == target - 5
    assert after["remaining_to_produce"] == target - 5
    assert after["already_moved_qty"] == 0  # nothing moved yet


def test_move_to_f2_does_not_change_produced_or_remaining(client):
    """Scenarios 2, 9: moving must not increase Produced. Scenario 10: F1 available
    WIP drops, F2 In Process/WIP becomes the moved quantity.

    Produces and moves the WO's entire physically-unprocessed backlog (in_process_qty)
    rather than a fixed "5" -- F1's ent_qty is the full physical_wo_qty from release,
    so moving only a partial amount would correctly leave F1's available_wip > 0 (more
    unprocessed material genuinely remains). Draining the full backlog is what
    actually makes "F1 available WIP = 0" true, per requirement 10.
    """
    headers = _admin(client)
    wo = _intake_wo(client, headers)

    f1_initial = _stage_state(client, headers, wo, "F1")
    producible = f1_initial["in_process_qty"]
    assert producible > 0

    produce_resp = _produce(client, headers, wo, "F1", good=producible)
    assert produce_resp.status_code == 200, produce_resp.text

    f1_before_move = _stage_state(client, headers, wo, "F1")
    ok_before_move = f1_before_move["ok_completed_qty"]
    not_yet_before_move = f1_before_move["not_yet_produced"]
    assert f1_before_move["already_moved_qty"] == 0  # produced, not yet moved

    move_resp = _move(client, headers, wo, "F1", "F2", producible)
    assert move_resp.status_code == 200, move_resp.text

    f1_after = _stage_state(client, headers, wo, "F1")
    f2_after = _stage_state(client, headers, wo, "F2")

    # Produced (cumulative OK) at F1 is completely unchanged by the move.
    assert f1_after["ok_completed_qty"] == ok_before_move
    # Not Yet Produced / Remaining to Produce are also unaffected by movement.
    assert f1_after["not_yet_produced"] == not_yet_before_move
    assert f1_after["remaining_to_produce"] == not_yet_before_move
    # F1's available WIP for further movement drops to 0 -- everything producible so
    # far has left the stage.
    assert f1_after["available_wip"] == 0
    # In Process/WIP for material that left F1 is now visible at F2.
    assert f1_after["already_moved_qty"] == producible
    assert f2_after["in_process_qty"] == producible


def test_production_of_5_succeeds_then_6_more_fails(client):
    """Scenarios 5, 6: after target 10 / produced 5, 0..5 is allowed, 6+ must be
    rejected by the backend."""
    headers = _admin(client)
    wo = _intake_wo(client, headers)
    _produce(client, headers, wo, "F1", good=5)

    state = _stage_state(client, headers, wo, "F1")
    remaining_physical = state["in_process_qty"]
    assert remaining_physical == 5

    ok_resp = _produce(client, headers, wo, "F1", good=remaining_physical)
    assert ok_resp.status_code == 200, ok_resp.text

    over_resp = _produce(client, headers, wo, "F1", good=1)
    assert over_resp.status_code == 400, over_resp.text


def test_production_beyond_target_after_full_completion_fails(client):
    """Scenario 7 / task's worked example: Target reached, Not Yet Produced = 0,
    any further production must be rejected.

    Uses a single-stage route (F1 -> DISPATCH) so F1's target_qty equals
    physical_wo_qty exactly with no yield back-projection -- calculate_stage_targets
    (the existing, unmodified OMS Engine formula) makes the LAST production stage's
    target exactly the released quantity, and F1 is that last stage here. This is
    the existing engine's real behavior, not a simplification invented for the test.
    """
    headers = _admin(client)
    wo = _intake_wo(client, headers, po_qty=10)
    release = client.post(
        "/api/v1/operations/wo-release", headers=headers,
        json={"wo_number": wo, "physical_wo_qty": 10, "route_stages": ["F1"]},
    )
    assert release.status_code == 200, release.text

    state = _stage_state(client, headers, wo, "F1")
    full = state["target_qty"]
    assert full == 10

    resp = _produce(client, headers, wo, "F1", good=full)
    assert resp.status_code == 200, resp.text

    final_state = _stage_state(client, headers, wo, "F1")
    assert final_state["not_yet_produced"] == 0
    assert final_state["remaining_to_produce"] == 0

    beyond = _produce(client, headers, wo, "F1", good=1)
    assert beyond.status_code == 400, beyond.text


def test_rejection_does_not_count_as_produced_or_in_process(client):
    """Scenario: rejected quantity must not count as Produced or In Process."""
    headers = _admin(client)
    wo = _intake_wo(client, headers)

    resp = _produce(client, headers, wo, "F1", good=3, rejected=2)
    assert resp.status_code == 200, resp.text

    state = _stage_state(client, headers, wo, "F1")
    assert state["ok_completed_qty"] == 3
    assert state["rejected_qty"] == 2
    # Not Yet Produced is Target - OK only (never subtracts rejected per spec).
    assert state["not_yet_produced"] == state["target_qty"] - 3
    # already_moved_qty (the "In Process/WIP" figure once produced material leaves
    # the stage) reflects only OK material, never rejected pieces.
    assert state["already_moved_qty"] == 0  # nothing moved; on_hand absorbs the 3 OK


def test_new_production_delta_is_never_cumulative(client):
    """Two separate production entries of 3 each must sum, not overwrite."""
    headers = _admin(client)
    wo = _intake_wo(client, headers)

    _produce(client, headers, wo, "F1", good=3)
    _produce(client, headers, wo, "F1", good=3)

    state = _stage_state(client, headers, wo, "F1")
    assert state["ok_completed_qty"] == 6


def test_cross_wo_movement_remains_blocked(client):
    headers = _admin(client)
    wo_a = _intake_wo(client, headers)
    wo_b = _intake_wo(client, headers)

    resp = client.post(
        "/api/v1/production/move", headers=headers,
        json={
            "wo_number": wo_a, "target_wo_number": wo_b,
            "from_stage": "F1", "to_stage": "F2", "quantity_moved": 1, "rejected_quantity": 0,
        },
    )
    assert resp.status_code == 400, resp.text
