# MT-019 — Zero-storage-upgrade recovery and archival runbook

**Owner constraint: do not purchase more Render Postgres storage or enable disk autoscaling.** The current database has 10 GB provisioned and was automatically suspended by Render at 2026-11-10 12:34 UTC after reaching the physical disk limit. Its existing writes are not safe to resume unchanged.

## Verified root cause

- Live `database_storage_audit` samples: database ~5.86 GB on Nov 7 06:05 UTC and ~8.82 GB on Nov 9 23:35 UTC. `research_job` rose from ~2.97 GB to ~5.90 GB, almost the entire measured logical growth.
- The `demo/shadow` share of the 1% table sample increased from 2,376 sampled rows (~0.66 MB of sampled parameter+progress bytes) to 14,319 (~18.37 MB); **the 1% sample does not measure the whole table**. Causal candidates are continually appended `demo/shadow/event/<UUID>` rows, index overhead, update/WAL activity, and unbounded/retained history.
- **Correction:** The active shadow worker *does* call `services.demo.maintenance.maintenance` approximately every five minutes from `HostedRun.control`. Live `demo_archive_scan` events showed `archived:0` with batches of 129–200 rows through Nov 10 00:14 UTC. The archiver waits 30 days normally, seven days under pressure, but the new high-volume event history is only days old.
- Even once old enough, that routine alternates two prefixes, inspects 200 rows per run (at most ~28,800 shadow rows/day), and **updates** old PostgreSQL rows with verified R2 pointers rather than removing them. The normal runtime principals intentionally lack broad DELETE privileges. This is not a sustainable 10 GB hot-event retention system.
- Control backups also repeatedly failed with `QueryCanceled` (SQLSTATE 57014) or `backup_capacity`; do not assume all current controls are backed up just because R2 is configured. Last verified `demo_control_backup_verified` in the sampled logs was Nov 8 04:36 UTC.

## Real storage roles

- **Cloudflare R2**: implementation already exists for compressed, content-addressed provider archives and `demo/events` / `demo/backups`. Archive uploads use read-after-write byte/checksum verification.
- **Render Postgres**: transactional live wallet, orders, positions, settlements, jobs, recent activity and indexed aggregates. It is **not** merely a temporary disposable cache. Some canonical research-publication tables are intentionally immutable, and active account state depends on this database.
- Keep R2 as cold history and Postgres as bounded hot/indexed state, but verify actual bucket access and a successful backup before removing any current database records.

## Prioritized cleanup decisions

1. **Safe to offload after verification**: completed `demo/shadow/event` rows older than an explicitly selected hot window (default 24 hours). Retain every original event, parameters, progress, UTC creation timestamp and row ID in R2. Preserve a durable Postgres manifest with reference/checksum/count/time bounds. They are not the active execution checkpoint and the current `/demo/shadow/events` endpoint reads only the latest 100.
2. **Do not delete as a quick fix**: `demo/shadow/checkpoint`, current bot/folder control rows, outstanding orders, settlement evidence, funding records, reports required for P/L and all immutable research datasets/artifacts.
3. **Audit next**: high-volume `FAVORITE_STAT_DECISION`, `CYCLE_REPORT`, `MARKET`, `SCALPER_OBSERVATION_BATCH` and repeated status events. Determine which are genuine unique learning/financial evidence versus duplicate derived detail. The pre-outage `shadow_durability_cost.event_kinds` logs support counts by category, **not byte shares**.
4. **Repair failed backups**: avoid retrying the same unbounded backup query every five minutes. Consider R2 chunking and bounded incremental snapshots, preserving atomic financial checkpoint logic.
5. **Repair ongoing archiving**: a separate bounded/privilege-scoped recurring archive path must keep pace with newly generated events (not just 200 rows every ten minutes). Do not grant broad DELETE to normal paper-trading workers. Add storage thresholds based on *physical* as well as logical disk bytes.

## Operator-only archive/reclaim code in this branch

`python -m services.demo.shadow_archive_recovery` is **read-only preview by default**. To actually process a bounded batch requires all of:

- a separately authorized `RECOVERY_DATABASE_URL` connection (never the normal app's `DATABASE_URL` as an implicit fallback),
- validated `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` available privately,
- stopped paper writers, checked by the operator and explicitly acknowledged as `--writers-stopped`,
- `--execute`, an explicit age floor of at least six hours, and a maximum of 150 rows per batch.

Per batch the routine selects only old, succeeded `demo/shadow/event/` rows, uploads all original values to R2, verifies read-back, writes a manifest under `demo/shadow/archive-manifest/` and deletes exactly the selected IDs **in one PostgreSQL transaction**. If upload, verification, manifest insertion, deletion permissions, or row counts fail, the DB transaction aborts. No normal worker invokes this script.

### When a safe database connection is available

1. Stop/disable every writer using the database (not merely new trading entries); confirm no concurrent service is producing events or checkpoints. Leave worker/service configurations intact for later restoration.
2. Ask Render support for a way to **temporarily resume an at-quota database for an offload/reclaim operation without increasing the purchased disk allocation**, if normal Resume immediately re-suspends. Render's standard published recovery path recommends adding disk; zero-upgrade recovery is not guaranteed. Never force connection or change the IP allowlist just to make this tool run.
3. Confirm current database backup/integrity and R2 bucket read/write/verification; test restoration of a small archived batch. Establish a pre-operation logical and physical disk snapshot. Avoid full-table copy or table rewrite at a full disk.
4. First preview via `python -m services.demo.shadow_archive_recovery --age-hours 24 --batch-size 50`; **only after inspection/backup** use `--execute --writers-stopped --age-hours 24 --batch-size 50 --max-batches 1`.
5. Verify one manifest and its R2 object, count retained raw records, compare deletion count, check disk/WAL free space, then repeat bounded batches only while healthy. Do not run hundreds of batches blindly against a full disk.
6. Normal `VACUUM` only makes dead tuples/pages reusable for PostgreSQL in many cases; it is **not a promise that the Render volume shrinks**. Avoid `VACUUM FULL` or heavy rewrites near hard quota without additional free disk and an outage plan.
7. Test recent activity, wallet, pending positions, settlements, API dashboard, R2 restoration and background worker health before restoring new trading writes. Confirm growth stays below available capacity over comparable hours.

## Remaining blockers

- Render Postgres is suspended; the connector cannot query or reclaim rows.
- The scoped operator recovery role/connection and historical R2 restore UX need validation.
- No recurring purge has been enabled. This tool is an explicit one-time safe recovery instrument, **not yet the permanent retention service**.
- No Render storage was increased and no records were deleted by this code change.
