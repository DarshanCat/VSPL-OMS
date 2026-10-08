import subprocess
from urllib.parse import urlparse, unquote
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2.credentials import Credentials
import pg8000.dbapi

token = subprocess.check_output('gcloud.cmd auth print-access-token', shell=True).decode().strip()
credentials = Credentials(token)

secret = subprocess.check_output('gcloud.cmd secrets versions access latest --secret=VSPL_DATABASE_URL --project=vspl-oms-510015', shell=True).decode().strip()
parsed = urlparse(secret)
username = unquote(parsed.username) if parsed.username else 'vspl_user'
password = unquote(parsed.password) if parsed.password else ''
dbname = parsed.path.lstrip('/')

connector = Connector(credentials=credentials)
conn = connector.connect(
    'vspl-oms-510015:asia-south1:vspl-oms-db',
    'pg8000',
    user=username,
    password=password,
    db=dbname,
    ip_type=IPTypes.PUBLIC
)
cur = conn.cursor()

cur.execute("""
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'audit_logs' 
ORDER BY ordinal_position;
""")
print('audit_logs columns:', [r[0] for r in cur.fetchall()])

cur.execute("""
SELECT action, entity, entity_id, created_at, details
FROM audit_logs
WHERE entity IN ('POMaster', 'POLine', 'po_master', 'po_lines')
ORDER BY created_at DESC;
""")
logs = cur.fetchall()
print(f"Total audit log rows referencing POMaster/POLine: {len(logs)}")
for l in logs[:10]:
    print(l)

# Check audit_logs foreign key constraints
cur.execute("""
SELECT tc.constraint_name, kcu.column_name, ccu.table_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
WHERE tc.table_name = 'audit_logs' AND tc.constraint_type = 'FOREIGN KEY';
""")
fk_audit = cur.fetchall()
print(f"FK constraints on audit_logs: {fk_audit}")

cur.close()
conn.close()
connector.close()
