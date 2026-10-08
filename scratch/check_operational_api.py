import urllib.request
import json
import subprocess
from datetime import datetime, timedelta
from jose import jwt

secret_key = subprocess.check_output('gcloud.cmd secrets versions access latest --secret=VSPL_SECRET_KEY --project=vspl-oms-510015', shell=True).decode().strip()

payload = {
    "sub": "aravind.gurudev@vijayspheroidals.com",
    "role": "ADMIN",
    "exp": datetime.utcnow() + timedelta(hours=2)
}
token = jwt.encode(payload, secret_key, algorithm="HS256")

endpoints = [
    "/api/v1/masters/pos",
    "/api/v1/operations/oars",
    "/api/v1/work-orders",
    "/api/v1/dashboard/stats"
]

base_url = "https://oms.vijayspheroidals.in"

for ep in endpoints:
    url = f"{base_url}{ep}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "User-Agent": "Antigravity/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            print(f"\nEndpoint: {ep} | Status: {resp.status}")
            if isinstance(data, list):
                print(f"Count: {len(data)}")
                if len(data) > 0 and len(data) <= 10:
                    for item in data:
                        print(" ", item)
                elif len(data) > 10:
                    print(f"  First 3: {data[:3]}")
            elif isinstance(data, dict):
                print(f"Dict keys: {list(data.keys())}")
                print(f"Content: {data}")
    except Exception as e:
        print(f"\nEndpoint: {ep} | Error: {e}")
