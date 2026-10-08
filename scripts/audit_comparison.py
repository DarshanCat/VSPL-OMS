import json
import subprocess
import urllib.parse
import psycopg2

def run_audit():
    # Load manifest
    manifest_path = r'backups\neon-2026-09-29\neon_manifest_20260929_180636.json'
    with open(manifest_path, 'r', encoding='utf-8') as f:
        neon_manifest = json.load(f)

    # Get Cloud SQL credentials from Secret Manager safely
    cmd = ['gcloud', 'secrets', 'versions', 'access', 'latest', '--secret=VSPL_DATABASE_URL', '--project=vspl-oms-510015']
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    url = res.stdout.strip()
    parsed = urllib.parse.urlparse(url)

    db_user = parsed.username
    db_pass = parsed.password
    db_name = parsed.path.lstrip('/')

    conn = psycopg2.connect(
        host="34.100.147.34",
        port=5432,
        user=db_user,
        password=db_pass,
        dbname=db_name,
        sslmode="require"
    )

    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            gcp_tables = [r[0] for r in cur.fetchall()]
            
            gcp_table_counts = {}
            for t in gcp_tables:
                cur.execute(f'SELECT COUNT(*) FROM "{t}";')
                gcp_table_counts[t] = cur.fetchone()[0]

            # Sequences check
            cur.execute("""
                SELECT sequencename, last_value 
                FROM pg_sequences 
                WHERE schemaname = 'public'
                ORDER BY sequencename;
            """)
            gcp_sequences = {r[0]: r[1] for r in cur.fetchall()}

            # Compare tables
            neon_tables = neon_manifest.get('tables', {})
            all_table_names = sorted(set(list(neon_tables.keys()) + list(gcp_table_counts.keys())))

            print("=" * 70)
            print("DATABASE COMPARISON AUDIT: NEON SNAPSHOT vs. CLOUD SQL STAGING")
            print("=" * 70)
            print(f"{'Table Name':<34} | {'Neon Snapshot':>13} | {'Cloud SQL Staging':>17}")
            print("-" * 70)
            for t in all_table_names:
                neon_cnt = neon_tables.get(t, {}).get('row_count', 'MISSING')
                gcp_cnt = gcp_table_counts.get(t, 'MISSING')
                print(f"{t:<34} | {str(neon_cnt):>13} | {str(gcp_cnt):>17}")
            print("=" * 70)
            print(f"Total Tables: Neon={len(neon_tables)} | Cloud SQL={len(gcp_tables)}")
            print(f"Total Rows:   Neon={neon_manifest.get('total_rows')} | Cloud SQL={sum(gcp_table_counts.values())}")
            print("=" * 70)
            print(f"Cloud SQL Sequences Count: {len(gcp_sequences)}")
            for seq, val in gcp_sequences.items():
                print(f"  {seq:<32}: last_value = {val}")
            print("=" * 70)
    finally:
        conn.close()

if __name__ == '__main__':
    run_audit()
