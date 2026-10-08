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

cust_codes = ['AUM', 'WIE', 'PMC', 'BLV', 'ACD', 'MIL', 'SMX', 'ASB', 'YUK', 'BEL', 'ADN', 'LTC', 'TMI']

print("--- CUSTOMER MATCHING IN DATABASE ---")
for c in cust_codes:
    cur.execute("SELECT id, customer_code, name, is_active FROM customers WHERE customer_code = %s;", (c,))
    rows = cur.fetchall()
    if rows:
        r = rows[0]
        print(f"Code '{c}': FOUND -> Name: '{r[2]}' | UUID: {r[0]} | Active: {r[3]}")
    else:
        print(f"Code '{c}': NOT FOUND in customers table!")
        # Search by ILIKE
        cur.execute("SELECT id, customer_code, name FROM customers WHERE customer_code ILIKE %s OR name ILIKE %s;", (f"%{c}%", f"%{c}%"))
        suggestions = cur.fetchall()
        print(f"   Suggestions: {suggestions}")

cur.close()
conn.close()
connector.close()
