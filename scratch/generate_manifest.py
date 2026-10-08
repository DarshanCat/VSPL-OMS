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
SELECT p.id, p.po_number, p.customer_id, c.customer_code, c.name, p.status, p.created_at
FROM po_master p
LEFT JOIN customers c ON p.customer_id = c.id
ORDER BY p.created_at DESC;
""")
pos = cur.fetchall()

print("--- MANIFEST SUMMARY ---")
total_po_count = len(pos)
total_line_count = 0

for p in pos:
    po_id = str(p[0])
    po_num = p[1]
    cust_code = p[3]
    cust_name = p[4]
    cur.execute("""
    SELECT l.id, l.part_id, pt.part_number, l.po_qty, l.required_date
    FROM po_lines l
    LEFT JOIN parts pt ON l.part_id = pt.id
    WHERE l.po_id = %s
    ORDER BY l.created_at ASC;
    """, (po_id,))
    lines = cur.fetchall()
    total_line_count += len(lines)
    print(f"\nPO [{po_num}] (UUID: {po_id})")
    print(f"  Customer: {cust_code} - {cust_name}")
    print(f"  Lines count: {len(lines)}")
    for l in lines:
        print(f"    - Line UUID: {l[0]} | Part: {l[2]} (UUID: {l[1]}) | Qty: {l[3]} | Req Date: {l[4]}")

print(f"\nTotal po_master rows to delete: {total_po_count}")
print(f"Total po_lines rows to delete: {total_line_count}")
print(f"GRAND TOTAL ROWS: {total_po_count + total_line_count}")

cur.close()
conn.close()
connector.close()
