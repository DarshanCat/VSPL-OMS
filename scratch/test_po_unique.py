import subprocess
from urllib.parse import urlparse, unquote
from google.cloud.sql.connector import Connector, IPTypes
from google.oauth2.credentials import Credentials
import pg8000.dbapi
import uuid

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
conn.autocommit = False
cur = conn.cursor()

# Get customer IDs for LTC and MIL
cur.execute("SELECT id, customer_code FROM customers WHERE customer_code IN ('LTC', 'MIL');")
custs = {r[1]: r[0] for r in cur.fetchall()}
print('Customer IDs:', custs)

try:
    # Try inserting 'Schedule' for MIL
    id1 = str(uuid.uuid4())
    cur.execute("INSERT INTO po_master (id, po_number, customer_id, status) VALUES (%s, %s, %s, %s);", (id1, 'Schedule', custs['MIL'], 'OPEN'))
    print("Inserted Schedule for MIL")
    
    # Try inserting 'Schedule' for LTC
    id2 = str(uuid.uuid4())
    cur.execute("INSERT INTO po_master (id, po_number, customer_id, status) VALUES (%s, %s, %s, %s);", (id2, 'Schedule', custs['LTC'], 'OPEN'))
    print("Inserted Schedule for LTC")
    
    # Try inserting 'SCHEDULE' for MIL
    id3 = str(uuid.uuid4())
    cur.execute("INSERT INTO po_master (id, po_number, customer_id, status) VALUES (%s, %s, %s, %s);", (id3, 'SCHEDULE', custs['MIL'], 'OPEN'))
    print("Inserted SCHEDULE for MIL")
    
    # Try inserting 'SCHDULE' for MIL
    id4 = str(uuid.uuid4())
    cur.execute("INSERT INTO po_master (id, po_number, customer_id, status) VALUES (%s, %s, %s, %s);", (id4, 'SCHDULE', custs['MIL'], 'OPEN'))
    print("Inserted SCHDULE for MIL")

except Exception as e:
    print(f"FAILED: {e}")
finally:
    conn.rollback()
    print("Rollback complete.")

cur.close()
conn.close()
connector.close()
