# MT-019 — Bounded retention and reduced status/checkpoint churn

This change adds executable storage-reduction paths. It does **not** activate
production deletion, relax the recovery hold, claim bytes freed, or restart
trading. Existing recovery/operator checkpoints in WORK_QUEUE.md still apply.

## Changes

1. `services.demo.shadow_diagnostic_retention` is a separate online maintenance
   process. It preserves at least 24 hours of hot diagnostics and supports the
   same six diagnostic kinds and packed format as the existing recovery tools.
   It is not imported/scheduled by the API, worker, migration or predeploy.
   Preview defaults to one bounded read-only cycle; `--execute --continuous`
   explicitly selects ongoing retention after recovery acceptance.
2. Selection first reads at most 100 raw keys or 2 packed keys (configurable,
   maxima 100/8), then checks eligibility only for those keys. Cursors advance
   past protected/fresh rows. Each namespace completes at most one pass/cycle;
   raw and packed pages alternate. Each read uses a short READ ONLY snapshot.
3. Complete source rows are uploaded and read back from R2 before a separate
   short SQL transaction. The existing restricted function locks and compares
   every original column, atomically inserts the manifest and removes exact
   source IDs. Concurrent changes abort the entire page. No SQL transaction
   remains open across R2 I/O. Normal application accounts receive no grants.
4. Optional `MT_SHADOW_SPLIT_STATUS_ENABLED=true` stores large derived status
   fields in four fixed reusable slots (Scalper research, timing, statistics,
   comparison). A publication lock serializes overlapping publishers. Digests
   are read from PostgreSQL, so unchanged sections are not sent/written again,
   including after process restart. Sections + main status commit atomically.
   DemoStore reconstructs the exact view from one SELECT snapshot. Plain and
   compressed legacy status remain readable. At most four extra rows persist;
   there is no append-only version history or cleanup grant requirement.
5. Identical committed checkpoints no longer rewrite solely because 30 seconds
   elapsed. Changed state still writes with every corresponding atomic audit
   commit, failed commits never update the saved signature, first writes after
   process restart persist, and explicit startup/shutdown checkpoints remain.

Status sections are derived views only. This change does not externalize
financial checkpoint data, delete datasets, drop indexes or change strategies.
Checkpoint cold-state separation remains a later change requiring backup and
restoration support. The current PostgreSQL/R2 manifests/readers are reused.

## Activation order

- Keep current live recovery holds/flags until the recorded physical/WAL,
  credentials and account-recovery requirements are resolved. This new path
  CLI online path requires `MT_STORAGE_RECOVERY_HOLD=false`. The explicit
  archive-only held-collector route below preserves the hold and starts no
  trading/collection work. Use the existing stopped-writer recovery tools for
  held backlog reclamation before activating ongoing retention.
- Deploy the status reader to **all API/readers first**, with split writing
  OFF. The currently manual API deployment has a migration predeploy; coordinate
  it under the existing recovery procedure. Old API readers cannot interpret
  the split envelope. Then deploy the writer; only then enable split status.
- Status rollback: disable split writing and publish one complete legacy status
  before reverting readers. Four obsolete section slots can remain harmlessly.
- Retention requires a private, separate `RECOVERY_DATABASE_URL`, existing
  `pocket_archive_maintenance` LOGIN with only the installed scoped function,
  R2 write/readback, verified cold-history readers and physical/WAL headroom.
  Existing role installer is not rerun by this feature. No passwords here.
- `DATABASE_CAPACITY_GB` must match provisioned capacity. Execution additionally
  refuses logical usage above 80%; this is not a physical free-space sensor.
- Explicit online opt-ins (all default OFF):
  `MT_DIAGNOSTIC_RETENTION_ENABLED=true`,
  `MT_DIAGNOSTIC_RETENTION_READ_PATH_VERIFIED=true`,
  `MT_DIAGNOSTIC_RETENTION_HEADROOM_VERIFIED=true`.
  `MT_ARCHIVE_RECOVERY_LOOP` must remain false. These are operator assertions,
  not substitutes for measured readiness. Do not set them to bypass blockers.
- Preview from an already authorized private shell:
  `python -m services.demo.shadow_diagnostic_retention --pages 10`.
  It reports eligible rows only within the pages visited, not full history.
- After successful supervised acceptance, run a **single** separate process:
  `python -m services.demo.shadow_diagnostic_retention --execute --continuous`.
  Default cycle: 10 pages/namespace, 60-second wait between cycles. Configure
  `--pages` (1–100), `--interval-seconds` (10–3600), `--raw-page-size` (1–100),
  `--packed-page-size` (1–8) and `--age-hours` (24–8760). This adds no Render
  service/cost automatically. If placement in an existing worker is chosen,
  use a separately supervised process/private maintenance credential; do not
  give the paper executor maintenance authority.
- R2 failure, changed source, lock timeout or bad receipt stops the process
  with a redacted error class. The failing page's cursor is not advanced. R2
  copies can remain safely unreferenced; inspect before restart. Cursors are
  in-memory: restart rescans from each prefix, without losing unarchived rows.
  Newly inserted random-UUID keys behind a cursor are visited next pass.

## Archive-only route on the existing held collector

After backlog verification and API cold-reader acceptance, a disabled collector
can serve as an isolated retention worker without changing its start command,
adding a service, or releasing the API/collector recovery holds. Set
`MT_DIAGNOSTIC_RETENTION_HELD_WORKER=true` together with the three explicit
retention readiness flags above. This route additionally requires all of:

- `MT_STORAGE_RECOVERY_HOLD=true`, `WORKER_ROLE=collector`,
  `COLLECTION_ENABLED=false`, `RUNTIME_DB_PROFILE=research`.
- `STAGING_ACCEPTANCE=off`, `STAGING_OPERATOR_ACTION=off`.
- Recovery archival, every recovery one-shot and recurring control backup off.
- The existing private scoped maintenance credential and R2 archive writer.

The research entry point dispatches directly to maintenance before any normal
worker or audit actions. The paper executor never starts. The existing scoped
SQL role is reverified, and the 24-hour minimum, allowlists, complete R2
readback, exact-row reclaim and logical capacity guard remain in force.

A separate autocommit connection holds one database session advisory lease.
A replacement waits for the previous process to exit before doing archive
work. The runner rechecks configuration and lease connectivity before each
page and after R2 verification, immediately before the SQL transaction. No SQL
transaction stays open across R2 I/O. Each cycle examines at most ten 100-key
raw pages and ten two-key packed pages, followed by a 60-second wait.

Errors close clients and park the process with a sanitized review-required
event; they do not exit into a platform crash-retry loop. An explicit deploy or
restart revalidates readiness and rescans from the start. Cursors are not a
claim of complete historical coverage. Provider disk monitoring remains
separate from logical SQL size; the headroom flag is an operator assertion.

Disable `MT_DIAGNOSTIC_RETENTION_HELD_WORKER` and
`MT_DIAGNOSTIC_RETENTION_ENABLED` before returning this service to other work.
Keep its recovery hold while doing so. No startup hook is enabled by default.

## Empty-namespace boundary probe

The online retention path verifies the `idempotency_key` column's effective
collation before using a bounded high-key existence probe. For supported
libc English or byte-order collations, the enclosing upper fence increments
the last ASCII letter of the fixed allowlisted namespace. Incrementing the
trailing slash to `0` would be incorrect under English punctuation ordering.
Both the original lower high-key bound and exact `LIKE` namespace predicate
remain: malformed high suffixes still block completion. Unknown or ICU
collations fail closed and require a separately verified query plan.

This avoids walking unrelated later namespaces when an empty packed namespace
finishes its pass. Older offline audits retain their existing boundary checks.
It adds no index, grants, hosted write, activation flag or writer restart.
Do not merge/deploy during an active durably claimed backlog run: a deploy
would stop that run, whose consumed ID deliberately cannot restart.

## What to measure

Retention reports scanned/eligible/deleted row counts, original event counts,
serialized source JSON bytes, R2 compressed bytes, completed namespace passes
and before/after **logical** database size. `physical_bytes_freed` is explicitly
null: row deletion/JSON byte counts cannot establish filesystem reclamation.
Manifests and PostgreSQL row/index overhead remain. Compare actual incoming
bytes with offload throughput and oldest eligible age before declaring the
backlog cleared; a full pass under concurrent writes is not global history
completeness. Monitor provider physical usage/WAL separately.

Status telemetry adds section upserts, section transport bytes and unchanged
section bytes avoided. Checkpoint telemetry already counts unchanged skips and
transport bytes avoided. These measure write reduction, not disk reclamation.

## Validation

Tests exercise default-off/recovery exclusion, read-only bounded selection,
cursor behavior, R2 failure before SQL, logical-capacity protection, exact
status reconstruction, missing/corrupt sections, unchanged versus changed
status sections, rollback, and the existing checkpoint changed/failed-write
invariants. Disposable PostgreSQL CI additionally exercises xmin stability,
publication rollback, and a concurrent source mutation between R2 readback
and scoped SQL deletion with full-page rollback. No production experiment is
implied by passing tests.
