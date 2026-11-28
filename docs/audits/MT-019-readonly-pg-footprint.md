# MT-019 — one-shot read-only PostgreSQL logical footprint

The connected Render SQL action cannot reach the database because the external IP allowlist is intentionally empty. **Do not relax the allowlist** or paste credentials into chat to enable this diagnostic. No automatic worker task or API endpoint is introduced.

When an authorized operator already has a trusted internal Render shell with `RECOVERY_DATABASE_URL` configured, the single command below prints a JSON report without exposing that URL:

```bash
python -m services.demo.shadow_pg_storage_footprint --execute-readonly
```

Running the module without `--execute-readonly` prints a no-op message and makes **no database connection**. Missing credentials, invalid relation limits and connection errors fail without echoing connection details. Only the operator explicitly launches the command; no startup hook, job or schedule invokes it.

The report uses a `REPEATABLE READ, READ ONLY` PostgreSQL transaction, 5-second per-statement and 1-second lock timeouts, and *catalog/statistics metadata* to return the database's logical byte count and up to ten (maximum twelve) largest ordinary public tables, including heap/index sizes and estimated live/dead tuples. It never fetches original trading payloads, executes COUNT on event rows, deletes, restores, archives or modifies schemas.

**What it deliberately cannot answer:** The logical `pg_database_size()` is *not* host disk free space, is *not* actual `pg_wal` directory occupancy and does not count all cluster data outside the current DB. Dead tuple counts are statistics, not recoverable bytes. All flags for physical disk headroom, WAL headroom, safe archival/reclamation/deletion, trading restart, training and all-time history remain FALSE.

For actual current host disk usage, inspect the database's **Metrics → Disk Usage** chart in its existing Render dashboard at `https://dashboard.render.com/d/dpg-dbgcrl6c6qcc73f1hi1g-a` (allocated disk is 15 GB; autoscaling is disabled). For **WAL headroom**, separate privileged operator evidence is needed; no grant, IP allowlist change, pricing change, database resize or write-capable deployment is authorized by this probe.

Tests validate one-flag no-op/missing-URL behavior, invalid inputs before connection, sanitized failures, strict SQL read-only constraints, no unverified space claims and a real disposable `pocket_test` PostgreSQL row-preservation check.

Keep collectors, trading, automatic archival and API migrations on hold until actual disk/WAL and independently authenticated historic-R2 source/reconciliation gates are satisfied.
