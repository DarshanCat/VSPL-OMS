import subprocess
import json

cmd = "gcloud.cmd logging read \"resource.type=\\\"cloud_run_revision\\\" AND resource.labels.service_name=\\\"vspl-oms\\\"\" --project=vspl-oms-510015 --limit=200 --format=json"
raw = subprocess.check_output(cmd, shell=True).decode('utf-8')
entries = json.loads(raw)

# Sort entries chronologically
entries = sorted(entries, key=lambda x: x.get('timestamp', ''))

print(f"Total log entries retrieved: {len(entries)}")
print("\n--- CHRONOLOGICAL LOG ENTRIES ---")
for e in entries:
    ts = e.get('timestamp')
    log_name = e.get('logName', '').split('/')[-1]
    sev = e.get('severity', 'INFO')
    text = e.get('textPayload') or e.get('jsonPayload') or e.get('httpRequest', {}).get('status')
    if isinstance(text, dict):
        text = json.dumps(text)
    print(f"[{ts}] [{sev}] [{log_name}] {text}")
