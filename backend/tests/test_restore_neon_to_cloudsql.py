"""Tests for the production-safe Neon -> Cloud SQL restore utility."""

import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from restore_neon_to_cloudsql import (
    validate_target_url,
    load_and_validate_snapshot,
    compute_sha256,
    mask_url,
    run_restore,
    RESTORE_TABLE_ORDER,
    LEGACY_EXCLUDED_TABLES,
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_TABLE_COUNT,
    EXPECTED_TOTAL_ROWS,
)


def test_target_url_safety_rejects_neon():
    # Neon URL
    neon_url = "postgresql://user:pass@ep-cool-snowflake-12345.ap-southeast-1.aws.neon.tech/vspl_smes?sslmode=require"
    valid, msg = validate_target_url(neon_url)
    assert not valid
    assert "Neon" in msg


def test_target_url_safety_accepts_cloudsql():
    # Cloud SQL URL
    cloudsql_url = "postgresql://vspl_app:secret@34.100.147.34:5432/vspl_smes?sslmode=require"
    valid, msg = validate_target_url(cloudsql_url)
    assert valid


def test_mask_url_hides_password():
    raw_url = "postgresql://vspl_app:MySuperSecretPassword@34.100.147.34:5432/vspl_smes?sslmode=require"
    masked = mask_url(raw_url)
    assert "MySuperSecretPassword" not in masked
    assert "***@" in masked
    assert "34.100.147.34" in masked


def test_legacy_table_exclusion():
    assert "customer_part_mappings" in LEGACY_EXCLUDED_TABLES
    assert "customer_part_mappings" not in RESTORE_TABLE_ORDER
    assert "customer_part_cross_references" in RESTORE_TABLE_ORDER


def test_fk_ordering_rules():
    # Level 1 masters must precede Level 2/3/4 dependent tables
    assert RESTORE_TABLE_ORDER.index("customers") < RESTORE_TABLE_ORDER.index("orders")
    assert RESTORE_TABLE_ORDER.index("parts") < RESTORE_TABLE_ORDER.index("orders")
    assert RESTORE_TABLE_ORDER.index("orders") < RESTORE_TABLE_ORDER.index("work_orders")
    assert RESTORE_TABLE_ORDER.index("work_orders") < RESTORE_TABLE_ORDER.index("wo_routes")
    assert RESTORE_TABLE_ORDER.index("work_orders") < RESTORE_TABLE_ORDER.index("stage_wips")
    assert RESTORE_TABLE_ORDER.index("work_orders") < RESTORE_TABLE_ORDER.index("production_movements")
    assert RESTORE_TABLE_ORDER.index("users") < RESTORE_TABLE_ORDER.index("production_movements")


def test_snapshot_validation_with_real_snapshot():
    snapshot_path = Path("backups/neon-2026-09-29/neon_snapshot_20260929_180636.json")
    if snapshot_path.exists():
        data = load_and_validate_snapshot(snapshot_path, EXPECTED_SNAPSHOT_SHA256)
        assert len(data) == EXPECTED_TABLE_COUNT
        assert sum(len(v) for v in data.values()) == EXPECTED_TOTAL_ROWS
        assert "users" in data
        admin = next(u for u in data["users"] if u.get("email") == "aravind.gurudev@vijayspheroidals.com")
        assert admin["is_active"] is True
        assert str(admin["role"]).upper() in ("ADMIN", "USERROLE.ADMIN")


def test_snapshot_validation_fails_on_corrupt_hash(tmp_path):
    dummy_file = tmp_path / "dummy_snapshot.json"
    dummy_file.write_text('{"users": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="SNAPSHOT CHECKSUM MISMATCH"):
        load_and_validate_snapshot(dummy_file, EXPECTED_SNAPSHOT_SHA256)


def test_snapshot_validation_fails_if_admin_missing(tmp_path):
    # Construct 26 table dummy snapshot with 8355 rows but missing aravind admin
    dummy = {f"t{i}": [] for i in range(25)}
    dummy["t0"] = [{"id": f"row-{i}"} for i in range(8354)]
    dummy["users"] = [{"email": "other@vspl.com", "is_active": True, "role": "USER"}]
    dummy_file = tmp_path / "test_snap.json"
    dummy_file.write_text(json.dumps(dummy), encoding="utf-8")
    h = compute_sha256(dummy_file)
    with pytest.raises(ValueError, match="Authoritative admin account"):
        load_and_validate_snapshot(dummy_file, h)


def test_dry_run_requires_no_commit_flag():
    snapshot_path = Path("backups/neon-2026-09-29/neon_snapshot_20260929_180636.json")
    if snapshot_path.exists():
        # Mock psycopg2 connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with patch("psycopg2.connect", return_value=mock_conn):
            result = run_restore(
                snapshot_path=snapshot_path,
                target_url="postgresql://user:pass@34.100.147.34:5432/vspl_smes",
                commit=False,
            )
            assert result["mode"] == "DRY_RUN"
            assert result["success"] is True
            # In dry-run mode, execute should never be called with DELETE or INSERT
            for call_args in mock_cur.execute.call_args_list:
                sql = call_args[0][0].strip().upper()
                assert not sql.startswith("DELETE")
                assert not sql.startswith("INSERT")
                assert not sql.startswith("TRUNCATE")
