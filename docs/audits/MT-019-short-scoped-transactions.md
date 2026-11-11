# MT-019 — Short scoped archive transactions

## Root cause and safe change

The previous recovery-only scoped archive paths opened a PostgreSQL transaction,
selected eligible diagnostics, and kept that transaction open while uploading
and verifying R2 objects. The R2 network work can take much longer than the
SQL read or exact-row deletion and unnecessarily extends transaction lifetime.
Open transactions can retain snapshots/locks and create pressure on vacuum/WAL.

For **scoped=true** only, both
`services.demo.shadow_archive_recovery.archive_and_reclaim_one` and
`services.demo.shadow_batch_archive_recovery.archive_one` now:

1. Open one short PostgreSQL transaction to fetch a bounded diagnostic-only
   candidate page. Close the transaction and return the connection to the pool.
2. Outside every DB transaction, serialize **all original research_job
   fields**, upload to R2, and verify the full object/readback and checksum.
3. Open a second short PostgreSQL transaction that invokes ONLY the existing
   `public.mt_reclaim_shadow_diagnostics` SECURITY DEFINER function.
   It atomically inserts a durable manifest and rechecks every source row
   (ID, timestamps, original parameters/progress/lease fields, 24-hour age,
   namespace and diagnostic allowlist) before deleting exact IDs.
4. Compare actual returned deleted IDs/count to the intended list **inside
   that second transaction**. Any mismatch fails and rolls back. Uploaded
   R2 objects can remain as content-addressed orphans, which is preferable
   to deleting an unverified or changed PostgreSQL source record.

The historical operator-only `scoped=false` direct-delete compatibility
path intentionally keeps the original `FOR UPDATE SKIP LOCKED` read, R2
upload, manifest and deletion within one locked transaction. **Do not use
the direct-owner path for unattended production retention.**

## Safety limits

- This is a **code-only** efficiency improvement, not permission to enable
  archival, install credentials or resume paper trading.
- SQL identity recheck means a row updated *between the snapshot and the
  short reclaim transaction* fails closed; the original PostgreSQL row survives.
- Direct PostgreSQL writes remain blocked for the scoped archive login by
  the separate least-privilege role and function. Never grant broad DELETE.
- The candidate query and SQL fence still require a physical disk/WAL
  safety review, frozen nonfinancial writers including the API, and operator
  acknowledgments described in PR #190's archive-runbook gates.
- The R2 bucket is not transactionally coupled to PostgreSQL. SQL failures
  can leave verified but unreferenced R2 objects. Do not garbage-collect
  those objects until a separate safe reconciliation design exists.
- The physical Render disk free-space and WAL headroom are **not**
  established by PostgreSQL logical database size or this refactor.

## Verification

Regression tests check scoped transaction sequence:
`begin snapshot -> commit -> R2 verified -> begin exact reclaim -> commit`
for both raw and packed diagnostics, no direct DELETE in scoped mode, and
abort without apparent success for a changed source row. Legacy direct-owner
tests remain in place to catch inadvertent behavior changes.

PR must pass the complete API/PostgreSQL test suite before merge. GitHub
Actions backlog issue #192 currently prevents CI validation. Do not deploy
this change until the CI sequence is resolved, and never enable archival
automatically as part of a merge.
