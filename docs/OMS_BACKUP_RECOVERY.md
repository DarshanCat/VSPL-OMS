# OMS Backup & Recovery

This document uses only the actual deployment configuration in this repository
(`backend/docker-compose.yml`, `backend/.env.example`) — no backup infrastructure is
invented here.

## Backup

- **Mechanism**: standard PostgreSQL logical backup.
  ```bash
  pg_dump -Fc "$DATABASE_URL" -f vspl_smes_$(date +%Y%m%d_%H%M%S).dump
  ```
- **Frequency**: **not currently automated inside this repository.** No cron job,
  scheduled task, or backup service is defined anywhere in this codebase. If your
  production PostgreSQL is a managed service (RDS, Cloud SQL, Azure Database, etc.), use
  its built-in automated backup feature and record the actual schedule here. If it is
  self-hosted (e.g. the `postgres:16` container in `docker-compose.yml`), you must set up
  a scheduled `pg_dump` yourself — this is an infrastructure responsibility, not something
  the application does for you.
- **Location**: wherever you configure the `pg_dump` output to go (local disk, S3, etc.) —
  record your actual location here once decided. Do not store backups on the same disk as
  the database with no redundancy.
- **Retention**: define per your company's data-retention policy; not prescribed by this
  application.
- **Verification**: `pg_restore --list <dump-file>` confirms a dump is well-formed without
  actually restoring it; periodically test a real restore into a scratch database.

## Restore Process

```bash
# Into a fresh/empty database:
pg_restore -d "$DATABASE_URL" vspl_smes_<timestamp>.dump
```
After restoring, start the backend once against that database — `auto_migrate_schema()`
will apply any additive schema changes the dump predates, then verify with
`docs/PRODUCTION_SMOKE_TEST.md`.

## Recovery Responsibility

Whoever holds production database access (your DBA/ops team) owns backup execution and
restore testing. Application engineering owns verifying the restored system's schema and
manufacturing data integrity after a restore (see Disaster Recovery sequence below).

## Recovery Testing

Not yet performed against real production infrastructure in this project's history — a
restore has only been exercised conceptually in this document. **Do not claim a tested
recovery capability that has not actually been run.** Schedule and record an actual test
restore before relying on this procedure during a real incident.

---

## Disaster Recovery Sequence

1. **Identify the incident** — what actually failed (application, database, infra,
   security) and since when.
2. **Protect current state** — do not let anyone "fix" data by hand while you're still
   diagnosing; stop writes if the incident risks further corruption.
3. **Stop unsafe transactions if necessary** — take the affected endpoint/service down
   rather than let it keep writing against a suspect database.
4. **Assess database integrity** — connect and inspect; run the reconciliation endpoint if
   the DB is reachable at all (`is_plant_balanced`), check for the obvious signs of
   corruption (missing tables, broken constraints).
5. **Determine the recovery point** — the most recent backup known to be good, and how much
   real transaction data (if any) would be lost by restoring to it.
6. **Restore/recover** — using the Restore Process above, into a *separate* database first
   if there's any doubt, not directly overwriting the live one.
7. **Validate schema** — confirm all expected tables/indexes/constraints exist (see
   `docs/PRODUCTION_DEPLOYMENT.md` §3 for the expected table list and the `\dt`/`\d`
   commands used during go-live verification).
8. **Validate OMS health** — `GET /health`, then a real login.
9. **Validate manufacturing data** — run the plant reconciliation endpoint and spot-check a
   handful of known WOs against what the business expects.
10. **Run smoke tests** — the full `docs/PRODUCTION_SMOKE_TEST.md` checklist.
11. **Reopen operations** — only after 7–10 pass; communicate to operators what, if
    anything, needs to be re-entered because of data lost between the last good backup and
    the incident.
