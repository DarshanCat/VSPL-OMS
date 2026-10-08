import urllib.request
import urllib.parse
import json
import subprocess

# Get admin password
admin_pwd = subprocess.check_output('gcloud.cmd secrets versions access latest --secret=VSPL_ADMIN_PASSWORD --project=vspl-oms-510015', shell=True).decode().strip()
admin_email = "aravind.gurudev@vijayspheroidals.com"

urls_to_test = [
    "https://oms.vijayspheroidals.in",
    "https://vspl-oms-mz6h7opzhq-el.a.run.app"
]

for base_url in urls_to_test:
    print(f"\n==========================================")
    print(f"TESTING BASE URL: {base_url}")
    print(f"==========================================")
    
    # Check root / health
    try:
        req = urllib.request.Request(f"{base_url}/api/v1/health", headers={"User-Agent": "Antigravity/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"Health Status: {resp.status}, Body: {resp.read().decode()}")
    except Exception as e:
        print(f"Health check failed: {e}")

    # Login to get token
    try:
        login_data = json.dumps({"email": admin_email, "password": admin_pwd}).encode('utf-8')
        req = urllib.request.Request(
            f"{base_url}/api/v1/auth/login",
            data=login_data,
            headers={"Content-Type": "application/json", "User-Agent": "Antigravity/1.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            login_res = json.loads(resp.read().decode())
            token = login_res.get("access_token")
            print(f"Login OK. User: {login_res.get('user', {}).get('email')}")
            
            # Now call /api/v1/masters/pos
            po_req = urllib.request.Request(
                f"{base_url}/api/v1/masters/pos",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "User-Agent": "Antigravity/1.0"
                }
            )
            with urllib.request.urlopen(po_req, timeout=10) as po_resp:
                print(f"PO API Status: {po_resp.status}")
                print(f"Response Headers: {dict(po_resp.headers)}")
                pos_data = json.loads(po_resp.read().decode())
                print(f"Total POs returned by API: {len(pos_data)}")
                for p in pos_data:
                    print(f"  - PO: {p.get('po_number')} | Customer: {p.get('customer_code')} | Status: {p.get('status')} | Lines: {len(p.get('lines', []))}")
    except Exception as e:
        print(f"Login/PO API request failed: {e}")
