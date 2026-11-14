# Shadow diagnostic archival: safe rollout

Status: **draft / not deployed**. Never enable archival with active writers.

## Scope

- Only the six allowlisted, succeeded, older-than-24-hours, unarchived `demo/shadow/event/` diagnostics qualify.
- The scoped SQL reclaim function locks and rechecks exact original records. Verified R2 read-back and a restore manifest precede deletion.
- Orders, fills, positions, controls, settlement data and all other research namespaces are out of scope.
- The automatic loop requires `MT_ARCHIVE_RECOVERY_LOOP=true` and all of the explicit acknowledgments in `shadow_archive_automatic.configuration`. Leave the opt-in flag unset in ordinary services.
- No production rollout or unattended deletion is authorized by this pull request.

## Prerequisites for an operator-approved staging rehearsal

1. Confirm the recovery hold, disabled collectors, stopped paper writers and drained API write paths. Never infer stopped writers from `COLLECTION_ENABLED` alone.
2. Confirm that the target database is `pocket_staging` and that the maintenance connection logs in as `pocket_archive_maintenance` with scoped SQL reclaim only. Do not substitute the normal `DATABASE_URL` or the owner URL.
3. Confirm Render disk headroom separately from `pg_database_size`. Verify sufficient WAL capacity and avoid parallel archive or VACUUM operations.
4. Confirm `public.research_job_shadow_archive_events_v2` exists and is valid/ready. This index was built manually in staging; **this PR does not create it**. Do not deploy to other databases without an independently reviewed online index migration.
5. Make the private recovery credential available through secure configuration. Do not commit it, print it in logs, or rely on temporary shell files as persistent secrets.
6. Run the focused non-destructive tests and inspect CI. Rehearse one bounded verified batch while writers are stopped, then verify archived restore evidence and manifest.

## Resource and failure behavior

- Each opt-in archival cycle checks a 600-second elapsed budget, 128 MiB WAL delta budget, logical database ceiling of 12 billion bytes, and 256 MiB growth limit **between** verified atomic batches.
- The original capacity-percent guard remains. PostgreSQL logical bytes are not a substitute for Render physical disk usage.
- Each cycle reports deleted row counts, compressed bytes, WAL delta, database size before/after, elapsed time, and a stop reason.
- Safety configuration is rechecked before every batch. A changed flag or database credential fails closed.
- Resource budget reached => one logged cycle report, then an operator-review-required error rather than continuous unattended retries.
- Crash during archive upload may leave an already-verified R2 object without a manifest; existing R2 digest keys are content-addressed. The SQL fence either commits an exact-row reclaim plus manifest or rolls back. Verify before resuming.

## Validation

Focused tests:
```
python -m unittest tests.test_shadow_archive_candidate_query tests.test_shadow_archive_automatic_limits
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
