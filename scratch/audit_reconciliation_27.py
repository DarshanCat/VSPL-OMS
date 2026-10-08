import openpyxl
import subprocess
from urllib.parse import urlparse, unquote
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2.credentials import Credentials

excel_path = r"C:\Users\Darshan\.gemini\antigravity\brain\9283038f-a0e0-4fca-b665-b36c5e21dba1\.user_uploaded\media_1791441452333.xlsx"
wb = openpyxl.load_workbook(excel_path, data_only=True)
ws = wb['Sheet1']
rows = []
for r in range(2, ws.max_row + 1):
    row_data = [ws.cell(row=r, column=c).value for c in range(1, 23)]
    if not any(row_data):
        continue
    rows.append(row_data)

headers = [
    'wo', 'ts', 'oar', 'cust', 'cust_code', 'uniq_prod_id',
    'part_no', 'internal_part_code', 'internal_id', 'region',
    'grade', 'cust_grade', 'order_type', 'order_cat',
    'po_num', 'del_date', 'po_rate', 'po_qty', 'wo_qty',
    'remarks', 'wo_type', 'status'
]
source_data = [dict(zip(headers, r)) for r in rows]

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
SELECT 
    w.wo_number,
    w.physical_wo_qty,
    w.status AS wo_status,
    w.is_replacement,
    o.oar_number,
    o.customer_po,
    o.po_qty,
    o.delivery_date,
    c.customer_code,
    c.name AS customer_name,
    p.part_number,
    p.description AS part_desc
FROM work_orders w
JOIN orders o ON w.order_id = o.id
JOIN customers c ON o.customer_id = c.id
JOIN parts p ON o.part_id = p.id
ORDER BY w.wo_number ASC;
""")
db_wos = cur.fetchall()

source_by_wo = {d['wo']: d for d in source_data}

print("=== 27 FLAGGED RECORDS ANALYSIS ===")
print(f"{'WO':<10} | {'Source Value (openpyxl)':<26} | {'DB Value (Postgres)':<22} | {'Field':<15} | {'Classification'}")
print("-" * 115)

count = 0
for r in db_wos:
    wo_num = r[0]
    src = source_by_wo.get(wo_num)
    if r[5] != src['po_num']:
        count += 1
        src_repr = f"{src['po_num']} ({type(src['po_num']).__name__})"
        db_repr = f"'{r[5]}' ({type(r[5]).__name__})"
        print(f"{wo_num:<10} | {src_repr:<26} | {db_repr:<22} | {'customer_po':<15} | Validation script type mismatch (int != str)")

print("-" * 115)
print(f"Total flagged records: {count} / 59")

# Also check string-normalized comparison across ALL fields
print("\n=== STRING-NORMALIZED FULL RECONCILIATION ACROSS ALL 59 WOs ===")
all_mismatches = []
for r in db_wos:
    wo_num = r[0]
    src = source_by_wo.get(wo_num)
    
    # 1. Qty
    if r[1] != int(src['wo_qty']):
        all_mismatches.append((wo_num, 'wo_qty', src['wo_qty'], r[1]))
    # 2. OAR
    if str(r[4]).strip() != str(src['oar']).strip():
        all_mismatches.append((wo_num, 'oar', src['oar'], r[4]))
    # 3. Customer PO
    if str(r[5]).strip() != str(src['po_num']).strip():
        all_mismatches.append((wo_num, 'po_num', src['po_num'], r[5]))
    # 4. Customer Code
    if str(r[8]).strip() != str(src['cust_code']).strip():
        all_mismatches.append((wo_num, 'cust_code', src['cust_code'], r[8]))
    # 5. Part Number
    if str(r[10]).strip() != str(src['internal_id']).strip():
        all_mismatches.append((wo_num, 'internal_id', src['internal_id'], r[10]))

print(f"Total real data mismatches after string normalization: {len(all_mismatches)}")

cur.close()
conn.close()
connector.close()
