import subprocess
from urllib.parse import urlparse, unquote
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2.credentials import Credentials
import pg8000.dbapi
import json

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

print("==================================================")
print("1. TARGET POs VERIFICATION")
print("==================================================")
cur.execute("""
SELECT p.id, p.po_number, p.customer_id, c.customer_code, c.name, p.status, p.created_at
FROM po_master p
LEFT JOIN customers c ON p.customer_id = c.id
ORDER BY p.created_at DESC;
""")
po_records = cur.fetchall()
for r in po_records:
    print(f"ID: {r[0]} | PO: {r[1]} | CustID: {r[2]} | Code: {r[3]} | Name: {r[4]} | Status: {r[5]} | CreatedAt: {r[6]}")

cur.execute("SELECT COUNT(*) FROM po_master;")
total_po_master = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM po_lines;")
total_po_lines = cur.fetchone()[0]
print(f"\nTotal in po_master: {total_po_master}")
print(f"Total in po_lines: {total_po_lines}")

po_ids = [str(r[0]) for r in po_records]

print("\n==================================================")
print("2. ALL FOREIGN KEYS REFERENCING po_master OR po_lines")
print("==================================================")
cur.execute("""
SELECT
    tc.table_name AS from_table,
    kcu.column_name AS from_column,
    ccu.table_name AS to_table,
    ccu.column_name AS to_column,
    tc.constraint_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND ccu.table_name IN ('po_master', 'po_lines');
""")
fks = cur.fetchall()
for fk in fks:
    print(f"FK: {fk[0]}.{fk[1]} -> {fk[2]}.{fk[3]} (constraint: {fk[4]})")

print("\n==================================================")
print("3. CHECK ALL REFERENCING TABLES FOR TARGET PO ROWS")
print("==================================================")
for fk in fks:
    table, col, to_table, to_col, cname = fk
    # count matches
    if to_table == 'po_master':
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({','.join(['%s']*len(po_ids))});", tuple(po_ids))
        cnt = cur.fetchone()[0]
        print(f"Table '{table}'.'{col}' referencing po_master: {cnt} rows found")
    elif to_table == 'po_lines':
        cur.execute(f"""
        SELECT COUNT(*) FROM {table} 
        WHERE {col} IN (SELECT id FROM po_lines WHERE po_id IN ({','.join(['%s']*len(po_ids))}));
        """, tuple(po_ids))
        cnt = cur.fetchone()[0]
        print(f"Table '{table}'.'{col}' referencing po_lines: {cnt} rows found")

print("\n==================================================")
print("4. DETAILED PO LINES BREAKDOWN PER PO")
print("==================================================")
for r in po_records:
    po_id = str(r[0])
    po_num = r[1]
    cur.execute("""
    SELECT l.id, l.part_id, pt.part_number, l.po_qty, l.required_date, l.created_at
    FROM po_lines l
    LEFT JOIN parts pt ON l.part_id = pt.id
    WHERE l.po_id = %s
    ORDER BY l.created_at ASC;
    """, (po_id,))
    lines = cur.fetchall()
    print(f"\n--- PO: {po_num} (ID: {po_id}) | Lines: {len(lines)} ---")
    tot_qty = 0
    for l in lines:
        tot_qty += (l[3] or 0)
        print(f"  Line ID: {l[0]} | Part: {l[2]} (PartID: {l[1]}) | Qty: {l[3]} | ReqDate: {l[4]} | Created: {l[5]}")
    print(f"  Total PO Qty across lines: {tot_qty}")

print("\n==================================================")
print("5. VERIFY DOWNSTREAM OPERATIONAL TABLES")
print("==================================================")
operational_tables = [
    'orders', 'work_orders', 'wo_engineering_readiness', 'wo_routes',
    'production_updates', 'production_movements', 'stage_wips',
    'nc_records', 'rejection_dispositions', 'conversions',
    'packing_records', 'packing_transactions', 'dispatches'
]

for t in operational_tables:
    cur.execute(f"SELECT COUNT(*) FROM {t};")
    cnt = cur.fetchone()[0]
    print(f"Table '{t}': total rows in DB = {cnt}")

print("\n==================================================")
print("6. CHECK PROTECTED TABLES")
print("==================================================")
protected_tables = [
    'customers', 'parts', 'customer_part_mappings',
    'cc_materials', 'cc_inwards', 'cc_stock_units', 'cc_stock_ledger',
    'machines', 'shifts', 'heats', 'audit_logs', 'users'
]

for t in protected_tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t};")
        cnt = cur.fetchone()[0]
        print(f"Protected Table '{t}': total rows in DB = {cnt}")
    except Exception as e:
        print(f"Protected Table '{t}': Error: {e}")

print("\n==================================================")
print("7. CHECK SCHEDULES & OTHER LINKED TABLES")
print("==================================================")
# Check schedules table or any other masters
other_tables = ['schedules', 'schedule_lines', 'schedule_master', 'schedules_master']
for t in other_tables:
    cur.execute(f"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '{t}');")
    exists = cur.fetchone()[0]
    if exists:
        cur.execute(f"SELECT COUNT(*) FROM {t};")
        cnt = cur.fetchone()[0]
        print(f"Table '{t}': exists, count = {cnt}")
    else:
        print(f"Table '{t}': does not exist")

cur.close()
conn.close()
connector.close()
