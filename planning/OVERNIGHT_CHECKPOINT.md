# Pocket Analytics continuation checkpoint

## Instructions and boundaries

Owner asked for overnight independent build work, periodic durable saves, and to
skip steps needing direct involvement. Full app remains **undeployed**. Do not
merge PRs, enable deployments, provision resources, change live infrastructure,
create Google credentials, or execute trading. Keep owner email and secrets out
of this public repo. Do not spawn subagents unless explicitly authorized.

Work in draft PR #9, branch `build/google-auth-foundation`:
https://github.com/princesspikachuu/kalshi-scanner-data/pull/9

Read actual remote branch/CI before editing. Use a fresh worktree if another is
dirty. Use expected-head leases when updating branch refs. Do not overwrite work
from another session. Checkpoints are committed with each independent milestone.
If another scheduled run is working, avoid overlapping writes and inspect its
checkpoint before continuing. Eight hourly continuation sessions were requested
for this night; the schedule ends automatically, not an indefinite daily job.

## Existing foundation

- Google-only owner auth/API, PostgreSQL migrations, disposable PG CI.
- Separate Cloudflare gateway/sign-in smoke page and unlinked staging Blueprint.
- Google client ID/account-side setup not available; skip this while owner sleeps.
- No services/DBs/buckets deployed or provisioned. Live research app is unchanged.
- Draft branch predates later live loss-prevention fixes; do not replace main's
  dashboard files from this old base. Before eventual integration, reconcile main.
- Current desired table: original UI preserved; loss prevention changes return
  metrics and adds sell threshold within each cell. Original loss rate >50% says
  “Trade not recommended” instead of threshold; exactly 50% does not. Counts and
  full original cohort remain unchanged. No live trades exist.

## Current milestone: durable collection queue

Added `migrations/0004_collection_leases.sql`,
`services/research/queue.py` + README and queue integration tests. CI now watches
`services/research/**`. Existing migration-count test updated for migration 4.

Implemented: idempotent enqueue, concurrent claims via SKIP LOCKED, bounded
leases/heartbeat, unique attempt token fencing, cancellation, delayed retries,
attempt exhaustion, atomic immutable archive references + per-job page cursors.
Completed pages survive reclaim/cancel and duplicate pages do not inflate counts.

Not implemented: provider fetch adapter, R2 client, a running worker, normalized
observations, aggregate publication, historical queries or UI. Queue completion
is not dataset publication and does not advance global coverage. Archive upload
verification is the future archive adapter's responsibility, explicitly documented.

Local validation: API suite 28 tests, 12 passed, 16 real-Postgres cases skipped
(no disposable database here). The skipped group includes 10 new queue cases and
6 existing auth cases. Real PG verification MUST come from CI; inspect its result
before claiming the queue works against PostgreSQL. CI is test-only, no deployment.

## Next independent milestones (complete in order, adjust to evidence)

1. Inspect queue commit CI. Fix any failures; record exact verified result here.
2. Immutable archive codec + object-store interface: canonical JSON, deterministic
   gzip, content-addressed keys, checksums/size verification, safe bounded reads.
   Fake/local test adapter allowed; R2 adapter must stay unconfigured/undeployed.
3. Incremental coverage planner and resumable worker adapter using the queue.
   Distinguish fetched page from complete series/date coverage, bounded shared
   provider rate budgets, retries/deadlines, empty vs unavailable vs failed data.
   Test interrupted/restarted collection reuses pages and gaps are not hidden.
   Review existing collector before rewriting; preserve settled-only and price
   provenance rules. Use official current Kalshi docs for provider behavior.
4. Versioned dataset/run membership and precomputed research summary storage.
   Atomically publish complete datasets, retain previous runs, never mix latest
   with cumulative or replace full-sample counts with an observed subset.
5. Authenticated read-only historical run/date queries with keyset pagination,
   indexed SQL and tests. Keep any owner mutations session+CSRF protected. Update
   gateway allowlist/response validation deliberately when adding API routes.
6. React/TypeScript research shell and historical browser may follow a stable
   API contract. Reuse familiar current table behavior. No live hosting required.
7. Measure representative local performance and record reproducible timings.
   Do not promise a speedup from code structure alone or synthetic tiny samples.

Prefer a complete tested milestone per continuation. Save code/checkpoint in the
remote draft branch so workspace expiration cannot erase it. Inspect PR diff and
CI; report verified outcomes, pending work and owner-only blockers honestly.

## Owner-only items to leave pending

Google Web OAuth client/public client ID, hosted resource/budget authorization,
secure runtime secrets, R2 bucket/access configuration, and real staging sign-in
acceptance. No need to wake owner or repeatedly ask for these during this build.
