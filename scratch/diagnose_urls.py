import urllib.request
import ssl
import time

ctx = ssl.create_default_context()

urls = [
    ("Direct Cloud Run (Root)", "https://vspl-oms-mz6h7opzhq-el.a.run.app/"),
    ("Direct Cloud Run (/health)", "https://vspl-oms-mz6h7opzhq-el.a.run.app/health"),
    ("Direct Cloud Run (/api/v1/auth/login)", "https://vspl-oms-mz6h7opzhq-el.a.run.app/api/v1/auth/login"),
    ("Production Domain (Root)", "https://oms.vijayspheroidals.in/"),
    ("Production Domain (/health)", "https://oms.vijayspheroidals.in/health"),
    ("Production Domain (/api/v1/auth/login)", "https://oms.vijayspheroidals.in/api/v1/auth/login"),
]

for desc, url in urls:
    print(f"\n==========================================")
    print(f"TESTING: {desc}")
    print(f"URL: {url}")
    print(f"==========================================")
    t0 = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "Antigravity-Diagnostics/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            dur = time.time() - t0
            print(f"Status: {resp.status} ({resp.reason}) in {dur:.3f}s")
            print("Headers:")
            for k, v in resp.headers.items():
                print(f"  {k}: {v}")
            body = resp.read()
            print(f"Body length: {len(body)} bytes")
            print(f"Body sample: {body[:300]}")
    except urllib.error.HTTPError as e:
        dur = time.time() - t0
        print(f"HTTPError: {e.code} ({e.reason}) in {dur:.3f}s")
        print("Headers:")
        for k, v in e.headers.items():
            print(f"  {k}: {v}")
        body = e.read()
        print(f"Body length: {len(body)} bytes")
        print(f"Body sample: {body[:500]}")
    except Exception as e:
        dur = time.time() - t0
        print(f"Error: {e} in {dur:.3f}s")
