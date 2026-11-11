# MT-019 — Held-worker read-only WAL preflight

This is an **optional, OFF-by-default one-shot** evidence-gathering step, not
authorization to delete rows, turn on retention or resume trading.

## Purpose and output

Render MCP cannot connect to `pocket_staging` with its deliberately empty
external IP allowlist. A recovery-held processing worker can use the existing
private `DATABASE_URL` to report aggregate PostgreSQL data without changing
the database or exposing a connection string.

The `MT_WAL_PREFLIGHT_ONCE=true` startup audit emits a single
`mt019_wal_preflight` JSON record with:

- `logical_database.database_bytes`: PostgreSQL logical DB size, **not** physical disk utilization.
- `wal_counters`: generated WAL records/bytes and statistics reset timestamp;
  cumulative counters, **not** current WAL bytes or headroom.
- `wal_directory`: count/sum of files returned by `pg_ls_waldir()` if the
  runtime role has permission; failures are recorded only by exception class.
  This reports PostgreSQL's visible WAL directory, **not** total physical usage.
- `connections`: aggregate DB session counts. This **cannot prove all
  writers are stopped**, including intermittent API writers.
- `archive_role_presence`: whether the maintenance role, LOGIN state and
  constrained function exist. This does **not** prove the account has correct
  credentials or privileges.

Each query uses `default_transaction_read_only=on`, a 3-second statement
timeout, a single connection pool slot, and no R2/market clients. Failed
statistics remain unknown rather than guessed. No usernames, SQL statements,
query content, secrets or connection URLs are emitted.

The audit record always contains:
`verified_physical_free_disk=false`,
`verified_all_writers_stopped=false`, and
`authorizes_archive_reclaim=false`.

## Deployment and one-shot execution gates

1. Wait for this PR's full CI to pass before merging. Its code must run only
   on the established `pocket-processing-staging` recovery-held deployment,
   with `WORKER_ROLE=collector`, `COLLECTION_ENABLED=false`,
   `MT_STORAGE_RECOVERY_HOLD=true`, operator action/acceptance OFF.
2. Confirm all other one-shots and `MT_ARCHIVE_RECOVERY_LOOP` are OFF. Keep
   the research worker held. Do not enable trading or archival.
3. Only on the processing worker, use Render's private environment settings
   to temporarily set `MT_WAL_PREFLIGHT_ONCE=true`. The change deploys that
   worker and runs one bounded read-only audit per startup. Duplicate deploys
   can duplicate the read-only report but cannot alter data.
4. Inspect a sanitized `mt019_wal_preflight` event in the worker logs, then
   **immediately restore `MT_WAL_PREFLIGHT_ONCE=false`** and confirm the
   replacement processing worker is LIVE and remains idle/recovery-held.
5. Compare logical size and WAL counters with previous and subsequent snapshots;
   do not infer generated-byte rate without two samples separated in time.
6. Independently inspect **actual Render physical disk utilization/free bytes**
   and safe WAL headroom in Render's PostgreSQL Dashboard or an authorized
   private operator context. The connector's metric list does not expose
   physical disk free space. SQL audit output alone is insufficient to approve
   archive deletion.

## Operator-only follow-up

After physical space, backup/restoration, writer quiescence (including API),
credential rotation and financial integrity checks, follow the narrowly scoped
role procedure at `docs/audits/MT-019-least-privilege-archive-role.md`.
Do not install a maintenance role automatically or grant broad DELETE.
The first archive trial must be one small batch of 24h+ nonfinancial diagnostics,
with complete verified R2 readback, durable manifest and exact ID reconciliation.

Keep `MT-019` IN PROGRESS and the data-gathering and trading workers stopped
until a separately verified live-safe retention design is ready.
