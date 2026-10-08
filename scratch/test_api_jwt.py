import urllib.request
import json
import subprocess
from datetime import datetime, timedelta
from jose import jwt

# Get secret key
secret_key = subprocess.check_output('gcloud.cmd secrets versions access latest --secret=VSPL_SECRET_KEY --project=vspl-oms-510015', shell=True).decode().strip()

# Create JWT token for admin
payload = {
    "sub": "aravind.gurudev@vijayspheroidals.com",
    "role": "ADMIN",
    "exp": datetime.utcnow() + timedelta(hours=2)
}
token = jwt.encode(payload, secret_key, algorithm="HS256")

urls_to_test = [
    "https://oms.vijayspheroidals.in",
    "https://vspl-oms-mz6h7opzhq-el.a.run.app"
]

for base_url in urls_to_test:
    print(f"\n==========================================")
    print(f"TESTING BASE URL: {base_url}")
    print(f"==========================================")
    
    endpoint = f"{base_url}/api/v1/masters/pos"
    req = urllib.request.Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "User-Agent": "Antigravity/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"PO API Status: {resp.status}")
            headers_dict = dict(resp.headers)
            print(f"Server Header: {headers_dict.get('server')}")
            print(f"Date Header: {headers_dict.get('date')}")
            print(f"Cache-Control Header: {headers_dict.get('cache-control')}")
            print(f"X-Cloud-Trace-Context: {headers_dict.get('x-cloud-trace-context')}")
            
            body = resp.read().decode()
            pos = json.loads(body)
            print(f"\nTotal POs returned by API: {len(pos)}")
            for idx, p in enumerate(pos, 1):
                po_num = p.get('po_number')
                cust = p.get('customer_code')
                status = p.get('status')
                created = p.get('created_at')
                lines = p.get('lines', [])
                print(f"  {idx}. PO: '{po_num}' | Customer: {cust} | Status: {status} | Lines: {len(lines)} | Created: {created}")
    except Exception as e:
        print(f"Request failed: {e}")
