"""VSPL OMS -- Google Cloud Run & Cloud SQL Comprehensive Functional Acceptance Test

Executes non-destructive, read-only functional validation across all manufacturing
execution modules, master data, analytics, audit logs, and RBAC policies.
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
from typing import Any, Dict, List, Tuple

BASE_URL = "https://vspl-oms-203224391095.asia-south1.run.app"


def get_admin_token() -> str:
    # Retrieve password from Secret Manager
    cmd = "gcloud secrets versions access latest --secret=VSPL_ADMIN_PASSWORD --project=vspl-oms-510015"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    password = res.stdout.strip()

    login_url = f"{BASE_URL}/api/v1/auth/login"
    login_data = json.dumps({
        "email": "aravind.gurudev@vijayspheroidals.com",
        "password": password
    }).encode("utf-8")

    req = urllib.request.Request(login_url, data=login_data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body["access_token"]


def test_endpoint(name: str, method: str, path: str, token: str, expected_status: int = 200) -> Tuple[bool, str, Any]:
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            status_code = resp.getcode()
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in content_type:
                body = json.loads(raw.decode("utf-8"))
            else:
                body = f"[{len(raw)} bytes of {content_type}]"

            passed = status_code == expected_status
            return passed, f"HTTP {status_code}", body
    except urllib.error.HTTPError as e:
        raw_err = e.read().decode("utf-8", errors="replace")
        passed = e.code == expected_status
        return passed, f"HTTP {e.code}", raw_err[:200]
    except Exception as e:
        return False, "ERROR", str(e)


def run_all_tests():
    print("=" * 80)
    print("VSPL OMS -- GCP PRODUCTION FUNCTIONAL ACCEPTANCE VERIFICATION")
    print(f"Target: {BASE_URL}")
    print("=" * 80)

    # 1. Health
    print("\n[1/10] SYSTEM HEALTH & CONTAINER INTEGRITY")
    passed, status, body = test_endpoint("Container Health", "GET", "/health", "")
    print(f"  {'GET /health':<45} : {status} (Result: {'PASS' if passed else 'FAIL'})")

    # 2. Authenticate Admin
    print("\n[2/10] AUTHENTICATION & ADMIN IDENTITY")
    token = get_admin_token()
    passed, status, body = test_endpoint("Auth Me", "GET", "/api/v1/auth/me", token)
    print(f"  {'GET /api/v1/auth/me':<45} : {status} -> User: {body.get('email')} ({body.get('role')})")

    # 3. Master Data
    print("\n[3/10] MASTER DATA & CROSS REFERENCES")
    master_tests = [
        ("GET /api/v1/masters/parts", "/api/v1/masters/parts?limit=10"),
        ("GET /api/v1/masters/customers", "/api/v1/masters/customers?limit=10"),
        ("GET /api/v1/masters/part-cross-references", "/api/v1/masters/part-cross-references?limit=10"),
        ("GET /api/v1/masters/rejection-types", "/api/v1/rejection/types"),
        ("GET /api/v1/masters/pos", "/api/v1/masters/pos"),
        ("GET /api/v1/masters/schedules", "/api/v1/masters/schedules"),
        ("GET /api/v1/masters/machines", "/api/v1/masters/machines"),
        ("GET /api/v1/masters/operators", "/api/v1/masters/operators"),
        ("GET /api/v1/masters/shifts", "/api/v1/masters/shifts"),
    ]
    for label, path in master_tests:
        passed, status, body = test_endpoint(label, "GET", path, token)
        count = ""
        if isinstance(body, dict):
            count = f"total={body.get('total', len(body))}"
        elif isinstance(body, list):
            count = f"items={len(body)}"
        print(f"  {label:<45} : {status} [{count}]")

    # 4. Operations & OARs
    print("\n[4/10] ORDER INTAKE & OAR GENEALOGY")
    passed, status, oars = test_endpoint("OAR List", "GET", "/api/v1/operations/oars", token)
    oar_count = len(oars) if isinstance(oars, list) else 0
    print(f"  {'GET /api/v1/operations/oars':<45} : {status} [OARs: {oar_count}]")
    if oar_count > 0:
        first_oar = oars[0].get("oar_number") if isinstance(oars[0], dict) else "OAR-0005"
        passed, status, gen = test_endpoint("OAR Genealogy", "GET", f"/api/v1/operations/oars/{first_oar}/genealogy", token)
        print(f"  {f'GET /api/v1/operations/oars/{first_oar}/genealogy':<45} : {status}")

    # 5. Work Orders & Dynamic Routing
    print("\n[5/10] WORK ORDERS, WIP & ROUTE PROGRESSION")
    passed, status, wos = test_endpoint("Work Orders", "GET", "/api/v1/work-orders", token)
    wo_count = len(wos) if isinstance(wos, list) else 0
    print(f"  {'GET /api/v1/work-orders':<45} : {status} [WOs: {wo_count}]")
    if wo_count > 0:
        first_wo = wos[0].get("wo_number") if isinstance(wos[0], dict) else "WO-1012"
        passed, status, tracking = test_endpoint("WO Tracking", "GET", f"/api/v1/work-orders/{first_wo}/tracking", token)
        print(f"  {f'GET /api/v1/work-orders/{first_wo}/tracking':<45} : {status}")
        passed, status, route = test_endpoint("WO Route", "GET", f"/api/v1/work-orders/{first_wo}/route", token)
        route_len = len(route) if isinstance(route, list) else 0
        print(f"  {f'GET /api/v1/work-orders/{first_wo}/route':<45} : {status} [Stages: {route_len}]")

    # 6. Production & Movements
    print("\n[6/10] PRODUCTION TRACKING & RECONCILIATION")
    prod_tests = [
        ("GET /api/v1/production/stage-summary", "/api/v1/production/stage-summary"),
        ("GET /api/v1/production/wip", "/api/v1/production/wip"),
        ("GET /api/v1/production/movements", "/api/v1/production/movements"),
        ("GET /api/v1/production/reconciliation", "/api/v1/production/reconciliation"),
    ]
    for label, path in prod_tests:
        passed, status, body = test_endpoint(label, "GET", path, token)
        extra = ""
        if isinstance(body, dict):
            extra = f"keys: {list(body.keys())[:4]}"
        elif isinstance(body, list):
            extra = f"count: {len(body)}"
        print(f"  {label:<45} : {status} [{extra}]")

    # 7. Rejection & Non-Conformance
    print("\n[7/10] QUALITY, NC RECORDS & REJECTION DISPOSITION")
    rejection_tests = [
        ("GET /api/v1/rejection", "/api/v1/rejection"),
        ("GET /api/v1/rejection/summary", "/api/v1/rejection/summary"),
        ("GET /api/v1/operations/nc", "/api/v1/operations/nc"),
    ]
    for label, path in rejection_tests:
        passed, status, body = test_endpoint(label, "GET", path, token)
        cnt = len(body) if isinstance(body, list) else (len(body.keys()) if isinstance(body, dict) else "")
        print(f"  {label:<45} : {status} [records: {cnt}]")

    # 8. Packing & Dispatch
    print("\n[8/10] PACKING, DISPATCH & BSR")
    pack_tests = [
        ("GET /api/v1/packing/queue", "/api/v1/packing/queue"),
        ("GET /api/v1/dispatch/queue", "/api/v1/dispatch/queue"),
        ("GET /api/v1/dispatch/history", "/api/v1/dispatch/history"),
    ]
    for label, path in pack_tests:
        passed, status, body = test_endpoint(label, "GET", path, token)
        cnt = len(body) if isinstance(body, list) else (len(body.keys()) if isinstance(body, dict) else "")
        print(f"  {label:<45} : {status} [records: {cnt}]")

    # 9. Analytics, KPIs & AI
    print("\n[9/10] ANALYTICS, PLANT KPIS & GOVERNANCE")
    analytics_tests = [
        ("GET /api/v1/dashboard/stats", "/api/v1/dashboard/stats"),
        ("GET /api/v1/analytics/kpis/plant", "/api/v1/analytics/kpis/plant"),
        ("GET /api/v1/analytics/anomalies", "/api/v1/analytics/anomalies"),
        ("GET /api/v1/analytics/models/governance", "/api/v1/analytics/models/governance"),
        ("GET /api/v1/ai/insights", "/api/v1/ai/insights"),
        ("GET /api/v1/reports/export/wip-csv", "/api/v1/reports/export/wip-csv"),
    ]
    for label, path in analytics_tests:
        passed, status, body = test_endpoint(label, "GET", path, token)
        print(f"  {label:<45} : {status}")

    # 10. User Administration, Roles & Audit Logs
    print("\n[10/10] RBAC DIRECTORY, ROLES & AUDIT LOGS")
    admin_tests = [
        ("GET /api/v1/users", "/api/v1/users"),
        ("GET /api/v1/roles", "/api/v1/roles"),
        ("GET /api/v1/admin/audit-logs", "/api/v1/admin/audit-logs"),
    ]
    for label, path in admin_tests:
        passed, status, body = test_endpoint(label, "GET", path, token)
        cnt = len(body) if isinstance(body, list) else (len(body.keys()) if isinstance(body, dict) else "")
        print(f"  {label:<45} : {status} [records: {cnt}]")

    print("\n" + "=" * 80)
    print("ALL FUNCTIONAL MODULE CHECKS COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_all_tests()
