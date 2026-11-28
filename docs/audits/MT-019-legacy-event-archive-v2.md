# MT-019 / #196 — Safe legacy demo event archive replacement

## Why the old path could lose useful history

The old `services.demo.maintenance.archive_events()` copied only
`id`, `parameters`, and `progress` to Cloudflare R2. After verifying the
object, it replaced PostgreSQL `progress` using an ID match and an
`archive`-absent check, without verifying whether any source field had
changed while the R2 upload ran. It could therefore overwrite new progress
with a pointer to an old snapshot. It also did not preserve all original
`research_job` metadata for recovery if PostgreSQL were lost.

## New v2 behavior (not activated)

- **Default OFF even if the saved Demo policy says archive enabled.** The
  normal five-minute maintenance stage now requires the additional private
  `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED=true` operator setting. Do **not**
  set it while MT-019 is open or before an independent restore-read review.
- Restrict source rows exclusively to `demo/shadow/event/` entries with
  old, succeeded, allowlisted **nonfinancial diagnostic** event kinds:
  the same `SAFE_EVENT_KINDS` as the scoped MT-019 recovery archiver.
  No `demo/event/` trading events, fills, order history, settlements,
  balances, controls, or other shadow event kinds are auto-archived.
- Select a bounded keyset page (at most 25 records) in a short read-only
  PostgreSQL transaction. Close it **before R2 upload**.
- Serialize every original `research_job` field, including immutable
  row identity, idempotency key, creation/start/finish/lease times, asset,
  status, retry counters, lease token, parameters and full progress. Store
  an explicitly versioned `demo-shadow-diagnostic-full-row-v2` object in
  R2 using the existing content-addressed SHA-256 + complete readback
  verification.
- In a second short PostgreSQL transaction, lock all original IDs in UUID
  order, **compare all 15 fields to the R2 snapshot**, then update only
  unchanged progress objects to verified R2 pointers. A changed, missing
  or conflicting source row aborts the transaction, preserving all original
  source data. Any already-uploaded R2 object may safely remain orphaned.
- Keep a separate new cursor `demo/archive-scan-v2`, leaving older
  scan/backup markers intact. No source row is physically deleted.
- The restoration handler supports previous **v1 progress-only R2 lists**
  for existing archived data, and also reads the new full-row v2 records.
  For v2, it checks every original non-progress database column before
  restoring progress. Both versions use a locked pointer-identity check and
  optimistic progress compare to prevent overwriting later changes.

The new automatic archiver is intentionally **not a PostgreSQL PITR backup**,
not a substitute for the separately verified 4,190-record R2 controls snapshot,
and not authorization to delete historical rows. Live research and trading
are still recovery-held. The Render PostgreSQL *physical* free-disk/WAL
headroom remains unverified; the restricted scoped maintenance role is
not installed and exposed database credentials require rotation.

## Acceptance before opt-in

CI must pass the full real-disposable-PostgreSQL suite: full-row serialization,
actual R2-format roundtrip contract, preservation of protected events, source
change during network upload, rollback without stale pointer, v1 and v2
restore compatibility, metadata mismatch rejection, and normal maintenance
default-OFF behavior. After code deployment and MT-019 storage/writer gates
are independently satisfied, separately verify that the dashboard can read
versioned archive pointers without hiding important research history.
Keep `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED=false` until approved. If a single
record exceeds R2's 4-MB compressed object cap, fail closed and preserve the
source row; do not silently truncate or skip it.
