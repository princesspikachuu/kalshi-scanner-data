# Shadow diagnostic archival: safe rollout

The indexed query and cycle guards were delivered in PR #228. The run marker and cumulative budget changes below require their own passing CI and rollout. Never enable archival with active writers.

## Scope

- Only the six allowlisted, succeeded, older-than-24-hours, unarchived `demo/shadow/event/` diagnostics qualify.
- The scoped SQL reclaim function locks and rechecks exact original records. Verified R2 read-back and a restore manifest precede deletion.
- Orders, fills, positions, controls, settlement data and all other research namespaces are out of scope.
- The automatic loop requires `MT_ARCHIVE_RECOVERY_LOOP=true` and all of the explicit acknowledgments in `shadow_archive_automatic.configuration`. Leave the opt-in flag unset in ordinary services.
- Activation is a separate operator action after the tested configuration is reviewable. Publishing this code does not enable cleanup.

## Prerequisites for an operator-approved staging rehearsal

1. Confirm the recovery hold, disabled collectors, stopped paper writers and drained API write paths. Never infer stopped writers from `COLLECTION_ENABLED` alone.
2. Confirm that the target database is `pocket_staging` and that the maintenance connection logs in as `pocket_archive_maintenance` with scoped SQL reclaim only. Do not substitute the normal `DATABASE_URL` or the owner URL.
3. Confirm Render disk headroom separately from `pg_database_size`. Verify sufficient WAL capacity and avoid parallel archive or VACUUM operations.
4. Confirm `public.research_job_shadow_archive_events_v2` exists and is valid/ready. This index was built manually in staging; **this PR does not create it**. Do not deploy to other databases without an independently reviewed online index migration.
5. Make the private recovery credential available through secure configuration. Do not commit it, print it in logs, or rely on temporary shell files as persistent secrets.
6. Run the focused non-destructive tests and inspect CI. Rehearse one bounded verified batch while writers are stopped, then verify archived restore evidence and manifest.

## Resource and failure behavior

- Each recovery **run**, including all cycles and their waits, shares a 600-second elapsed budget, 128 MiB cumulative WAL delta budget, and 256 MiB cumulative logical growth limit. The logical ceiling remains 12 billion bytes. Budgets are checked between verified atomic batches; the last batch may overshoot by one batch.
- The original capacity-percent guard remains. PostgreSQL logical bytes are not a substitute for Render physical disk usage.
- Each cycle reports its deleted row counts, compressed bytes and database size before/after. Its WAL delta and elapsed time are cumulative for the run, with a stop reason.
- Safety configuration is rechecked before every batch. A changed flag or database credential fails closed.
- Final reporting rechecks budgets after the last batch, so crossing a limit on that batch also halts the loop before the WAL baseline can reset. The configured capacity-percent guard is checked between batches as well.
- Resource budget reached, exhausted backlog, failed claim or archive failure => close the clients and remain idle until shutdown. Do not throw an error that simply invites Render to restart the same deletion loop.
- Crash during archive upload may leave an already-verified R2 object without a manifest; existing R2 digest keys are content-addressed. The SQL fence either commits an exact-row reclaim plus manifest or rolls back. Verify before resuming.

## Durable run claim and activation configuration

`MT_ARCHIVE_RUN_ID` is a new, explicit 32-character lowercase hex run identifier.
It is non-secret, but must be newly generated for each independently reviewed run.
Before any deletion, the worker writes `demo/recovery-runs/<run_id>.json` with a
conditional `IfNoneMatch: *` PUT and verifies the exact bounded read-back. No
credentials, infrastructure inventory, event bodies or database URLs enter this
marker. Never delete, overwrite, expire, or automatically rotate these markers.

A duplicate marker, failed marker write, failed read-back or worker crash cannot
rearm the same ID. If the process dies after claiming but before doing any work,
the ID is still consumed. Reusing it after a redeploy or restart leaves cleanup
idle. This deliberately favors operator review over automatic retries.

Only rearm with a new ID after the prior worker is stopped and its results,
archive receipts, physical headroom and writer holds have been reviewed. Never
change the run ID to bypass an error or while an earlier run could still be
active; overlapping workers with different IDs are not supported.

For a first automatic raw-diagnostic recovery run, retain all existing safety
flags and private scoped credentials. The proposed non-secret settings are:

| Variable | Value |
| --- | --- |
| `MT_ARCHIVE_RUN_ID` | fresh reviewed 32-character lowercase hex ID |
| `MT_ARCHIVE_RAW_BATCH_SIZE` | `100` |
| `MT_ARCHIVE_RAW_BATCHES` | `50` |
| `MT_ARCHIVE_PACKED_BATCHES` | `0` |
| `MT_ARCHIVE_INTERVAL_SECONDS` | `60` |

This attempts at most 5,000 raw rows per cycle, subject to the shared run limits,
and disables packed diagnostics for this initial rollout. `RAW_BATCHES` accepts
1–250; `PACKED_BATCHES` accepts 0–8. It still requires all acknowledgments in
`configuration`, `MT_STORAGE_RECOVERY_HOLD=true`, and disabled collection. The
restricted role must actually connect to `pocket_staging`. Do not use an owner or
normal application connection. Activation requires fresh writer-drain and Render
physical-headroom checks; logical bytes alone do not establish retained WAL.

This is bounded recovery automation, not a continuously operating retention
service. Do not resume trading or collectors with it running. Automatic rearming
or writer-safe continuous archiving is separate follow-on work.

## Validation

Focused tests:
```
python -m unittest services.api.tests.test_shadow_archive_candidate_query services.api.tests.test_shadow_archive_automatic_limits services.api.tests.test_shadow_archive_automatic services.api.tests.test_shadow_archive_recovery services.api.tests.test_shadow_archive_run_safety
```

These tests use no hosted DB or R2. Test imports require the app's Python dependencies. Staging timing data from earlier operator trials: indexed candidate query fetched 100 rows in 0.044 s; 100 verified archived/deleted in 0.931 s; a guarded 19,500-row run stopped normally at its WAL budget.

## Rollback

- Do not enable the archival loop on a service that is collecting or processing trades.
- For a code regression, disable `MT_ARCHIVE_RECOVERY_LOOP` and redeploy a known-good commit; do not drop a valid index while active cleanup may be using it.
- Retain the R2 archives and manifest records. Never restore records or delete archive objects without a separate verification plan.
- Do not use `VACUUM FULL` during low-disk recovery. Standard `VACUUM (ANALYZE)` is an independent maintenance task that requires owner authorization and resource review.

## Follow-on work

- A continuously operating collector-safe archival path must be designed, reviewed and tested separately before removing any writer-stopped requirement.
- Add a Render physical disk-pressure alert, archiving lag metrics, and sustained-growth measurements; a single logical DB size sample cannot prove sufficient physical headroom.

## Continuation checkpoint (2026-11-14)

- PR #228 remains the implementation branch; no hosted archival or deployment was performed during this verification.
- Reproduced the earlier revision's test failures: stale SQL ordering expectation, legacy connection mocks missing WAL readings, and new budget fixtures missing the final reporting read.
- Moved both new regression modules into `services/api/tests` so the existing full CI discovers them.
- Fixed the final-batch budget loophole and added regressions for WAL/growth/time crossing on the final batch, mid-cycle stopping, revoked safety flags, and no retry after a budget stop.
- Historical checkpoint above describes PR #228. For the cumulative-run/marker revision, repeat full CI on its exact head. Keep cleanup disabled until the new run configuration and its separate activation have been reviewed.
