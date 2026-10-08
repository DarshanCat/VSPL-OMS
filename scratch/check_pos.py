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
WHERE table_name = 'customers' 
ORDER BY ordinal_position;
""")
cols = [r[0] for r in cur.fetchall()]
print('Customer columns:', cols)

cur.execute("""
SELECT p.id, p.po_number, p.customer_id, c.name, c.customer_code, p.status, p.created_at 
FROM po_master p 
LEFT JOIN customers c ON p.customer_id = c.id 
ORDER BY p.created_at DESC;
""")
print('\n--- ALL 7 PO RECORDS WITH CUSTOMERS ---')
for r in cur.fetchall():
    print(r)

cur.execute("""
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'po_lines' 
ORDER BY ordinal_position;
""")
line_cols = [r[0] for r in cur.fetchall()]
print('PO Lines columns:', line_cols)

cur.execute("""
SELECT l.id, l.po_id, p.po_number, l.part_id, l.po_qty, l.required_date, l.created_at
FROM po_lines l
JOIN po_master p ON l.po_id = p.id
ORDER BY p.created_at DESC;
""")
print('\n--- ALL 16 PO LINES ---')
for r in cur.fetchall():
    print(r)

cur.close()
conn.close()
connector.close()
