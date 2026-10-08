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
SELECT conname, contype, pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class t ON c.conrelid = t.oid
WHERE t.relname = 'po_master';
""")
for r in cur.fetchall():
    print('Constraint:', r)

cur.execute("""
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'po_master';
""")
for r in cur.fetchall():
    print('Index:', r)

cur.close()
conn.close()
connector.close()
