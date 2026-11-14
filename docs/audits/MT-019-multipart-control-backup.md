# MT-019 — Verified, multipart control backup V2 (off by default)

## Why

The old `services.demo.maintenance.backup()` issues one broad OR-heavy
`research_job` query with `LIMIT 2001`, then refuses backup if it finds over
2,000 rows. Live logs before the storage incident repeatedly show SQLSTATE
57014 (`QueryCanceled`) and `backup_capacity`. It must not simply discard
open orders, unsettled positions, live execution history or other controls.

## V2 design

- Preserve **exactly the original scope** of demo and live controls/open orders,
  including full `live/write/` pilot history.
- Within one `REPEATABLE READ READ ONLY` transaction, use the existing
  idempotency-key index to fetch bounded pages from individual namespaces.
  The transaction closes **before any R2 network upload** to avoid long-lived
  snapshots holding back PostgreSQL vacuum.
- Refuse to publish a partial backup: a **temporary unlinked spool file** stages
  at most 100,000 source rows / 512 MiB canonical JSON **or less when
  the worker filesystem is smaller**, while reserving at least 256 MiB free
  local disk; at most 12 MiB in one record and ~2 MiB active Python chunk memory. The spool closes on
  failure and is closed after R2 verification. The real permitted ceiling
  requires checking Render worker local disk headroom and an exact database
  census; do not silently truncate or assume the 512 MiB cap is safe to use.
- Stage framed, up-to-200-record / approximately 2 MiB chunks in the temporary
  file, close the database read transaction, then upload each to
  immutable content-addressed R2 `demo/backups/` objects. `put_verified`
  performs read-after-write byte and JSON verification for every part.
- Upload a separate root manifest with all chunk receipts, exact source row
  count and a SHA-256 digest of canonical ordered rows. Read the root and
  **every chunk back from R2**, recomputing count, duplicate-free keys and
  digest **without keeping the reconstructed full backup in RAM** before
  publishing `demo/backup-health`.
- After the full R2 restore check, publish a small independent content-addressed
  receipt under **`demo/backups/roots/`**, containing the verified root reference,
  record count and digest. This prefix is discoverable using an R2 bucket listing
  even if PostgreSQL loses its `demo/backup-health` record. Verify the catalog
  receipt by readback **before** updating backup-health.
- Failure leaves the prior backup-health marker untouched and **never deletes**
  any database record. Orphaned content-addressed R2 chunks may remain after
  failure but are not claimed to constitute a complete backup.
- Restore function `restore_verified_snapshot(objects, root_reference)`
  performs read-only verification of a complete V2 root manifest.

## Current activation state

Both switches default OFF:

1. **One-time trial while workers are held:** set
   `MT_CONTROL_BACKUP_V2_ONCE=true` on *one disabled, recovery-held collector*.
   On boot it runs one bounded complete snapshot and logs only counts, SHA-safe
   verification outcome and an error *type* if it fails; it then idles.
   Immediately restore that flag to `false` after inspection. This makes
   durable, new R2 backup objects and updates `backup-health` only on success,
   but does not resume trading or delete history.
2. **Recurring live maintenance:** after the trial passes and the backup scope
   is within the caps, set `MT_CONTROL_BACKUP_V2_ENABLED=true` on the actual
   *demo trading worker*. Existing maintenance cadence and backup due policy
   are unchanged. Until explicitly set, the legacy backup function remains
   selected. Do not enable live workers simply to test this flag.

To remain fully safe, inspect the measured breakdown from
`MT_CONTROL_BACKUP_AUDIT=true` before trying V2. The first live audit already found at least 2,001 shadow-bot records / 67.8 MB,
exceeding the original 64 MiB in-memory V2 cap. We replaced that with a bounded
local spool, but **it is still not automatically safe for recurrent backups**:
the 4,190-row exact census (~190,253,997 bytes of JSONB), the one-time
read-only 512 MiB spool budget preflight (reported 52.9 GB available on /tmp),
and measured R2 throughput during a controlled one-time backup trial. The
filesystem report was advisory, not proof of per-instance ephemeral quotas.
If the complete source exceeds 100,000 rows / 512 MiB, implement incremental
versioned R2 backups rather than increasing caps blindly. A verified R2 control backup is
not a PostgreSQL point-in-time backup and does not replace database backups.

Cloudflare R2 private credentials and the ordinary least-privileged
`DATABASE_URL` are already supplied to the worker. This feature does **not**
require the database-owner account or DELETE permission.
