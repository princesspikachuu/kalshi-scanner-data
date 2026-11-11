# MT-019 — Automatic *recovery-hold* archival (opt-in; not yet activated)

## Verified one-time test, Nov 10 2026 (Pacific)

The operator confirmed:

- `shadow_archive_recovery --age-hours 24 --batch-size 50`: 50 eligible raw diagnostic rows in one bounded sample (not a total backlog estimate).
- Normal `pocket_research_runtime` role: `DELETE=false`, `INSERT=true`.
- R2 `head_bucket` passed and a small new `demo/events/` object passed write + readback integrity checks.
- Dedicated owner connection: `pocket_staging` `DELETE=true`, `INSERT=true` (only used interactively).
- `--execute --writers-stopped --age-hours 24 --batch-size 10 --max-batches 1` succeeded: **10 archived, 10 deleted, 7892 compressed bytes, manifest stored, verified**.
- These are exact selected *non-financial* diagnostic history rows; no wallet/order/fill/settlement records were selected. PG DELETE frees pages for reuse after routine vacuum; it does not prove the Render disk allocation shrinks.

**IMPORTANT SECURITY:** A prior Shell error exposed a runtime database credential in the conversation. Rotate that credential and update all dependent services before restoring trading. No credential values should be placed in source, issues, logs, chat, or this document. Unset the operator recovery URL in the interactive Shell when finished.

## What this change adds

`services/demo/shadow_archive_automatic.py` is a conservative recovery-only loop. **It is OFF in all currently deployed configurations**. Only a *disabled research collector worker* with all explicit opt-ins can run it:

- `MT_ARCHIVE_RECOVERY_LOOP=true`
- `MT_ARCHIVE_WRITERS_STOPPED=true` — operator confirms every paper writer using the database is stopped and remains stopped; do **not** set this for an active trading deployment
- `MT_STORAGE_RECOVERY_HOLD=true`
- `WORKER_ROLE=collector`, `COLLECTION_ENABLED=false`
- `STAGING_ACCEPTANCE=off`, `STAGING_OPERATOR_ACTION=off`, `MT_STORAGE_RECOVERY_AUDIT=false`
- `RECOVERY_DATABASE_URL` — *private maintenance credential, different from* `DATABASE_URL`
- `DATABASE_CAPACITY_GB=15` (current measured Render allocation, update only upon owner-approved capacity change)

For each scheduled cycle (default once every 60 seconds), it checks logical database size and stops when >80% of decimal provisioned GB, processes up to three 50-row raw diagnostic transactions and up to two two-row packed diagnostic transactions, with no more than 8 batches per format per cycle. Each is original-age >=24h, R2-uploaded, checksum/read-back verified, manifest-persisted, exact-row deleted atomically with the manifest. Every packed diagnostic original event remains in R2. Cycle results log only counts and bytes, no secrets. Any failure stops the loop and requires operator review. The worker's normal research/trading path remains off.

**The 80% guard is an extra logical-size check, not physical disk/WAL free-space measurement.** Render physical metrics and restart/WAL headroom still require monitoring. The loop does not automate vacuum or index rebuild; do not force a table rewrite near disk quota.

## Dedicated archive role setup (one-time DBA task)

**Never put the owner `pocket_staging` connection URL in Render worker environment.** The automatic loop refuses roles that own `research_job` or have superuser/role-creation/database-creation flags.

Create an isolated, random-password maintenance login and grant *only* the permissions this archive requires. Run in a trusted DBA session; change identifiers if the schema differs:

```sql
CREATE ROLE pocket_archive_maintenance LOGIN PASSWORD '<strong-random-secret>';
GRANT CONNECT ON DATABASE pocket_staging TO pocket_archive_maintenance;
GRANT USAGE ON SCHEMA public TO pocket_archive_maintenance;
GRANT SELECT, INSERT, DELETE ON TABLE public.research_job TO pocket_archive_maintenance;
```

This is still a **table-level DELETE grant**, not row-level SQL authorization. The code restricts event kinds and namespace and checks exact IDs, but the role itself can DELETE other rows if compromised. For stronger privileges, a reviewed SECURITY DEFINER procedure with only eligible-row deletion plus an independent R2 receipt check is required before unattended *live* archival. Rotate password/revoke role if retiring this feature.

Configure `RECOVERY_DATABASE_URL` as a private Render environment secret on **only one** designated research collector service, never on the API or trading worker. Confirm its `current_user` is neither database owner nor admin. Set all opt-in flags above only after inspecting both Render worker statuses and confirming paper writers stopped; changing these environment variables causes a deployment. Never set the flag on both workers simultaneously.

## Not implemented / not claimed

- No archival loop is enabled or deployed to run now. The code path is inert until an operator explicitly opts in.
- This is **paused-system backlog automation**, not a safe permanent retention path while trading continues. It intentionally fails closed if any recovery-hold flag is absent. To support normal operation, add read-through for R2 archives, a durable lease/heartbeat and verification of live writer/collector coordination, physical disk metrics, scoped SQL permissions, and sustained-rate tests before scheduling live cleanup.
- R2 archived events are currently restorable by manifest but not transparently included in the normal recent-event UI. Do not present them as a lossless live dashboard until cold-history retrieval is added.
- Database backup-health problems (`QueryCanceled`, `backup_capacity`) require separate repair. R2 proof-of-write is not a full financial-control backup.
