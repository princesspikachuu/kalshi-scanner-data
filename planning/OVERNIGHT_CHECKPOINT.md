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

Queue milestone saved at commit `dc3f8a6d7f913cc7655a3abbdb3d96d3cd2701de`.
**CI run 40453754645 passed**, including the 10 new real-Postgres queue cases,
6 existing PostgreSQL auth cases, other API/policy tests, 14 gateway/client tests,
and Blueprint schema validation. No deployment job ran.

## Second milestone: immutable archive codec

Added `services/research/archive.py` and 8 archive tests. Canonical parsed JSON,
deterministic gzip timestamp, SHA-256 object keys, immutable conditional upload
contract, bounded reads/decompression, and readback integrity verification before
returning a checkpoint receipt. Duplicate keys/nonfinite JSON/corrupt gzip and
receipt mismatches fail. Prices encoded as decimal strings preserve their units.
Documentation distinguishes parsed JSON archives from exact HTTP-wire captures.

No actual object-store/R2 adapter or hosted bucket exists. Tests use an in-memory
adapter; missing credentials are not blocking pure codec work. Archive unit tests
pass locally. Archive milestone saved at commit
`e341359ea0054585374f0a49979182f6346430fa`. **CI run 40453964106 passed**:
36 API/research tests (including all 16 actual PostgreSQL cases), 7 owner-policy
tests, 14 gateway/browser-client tests, and Blueprint validation. No tests skipped
in CI and no deployment ran. Total: 57 automated tests plus schema validation.

The draft diff was reviewed: no existing live collector, table, backtest or Worker
files changed. A local `git merge-tree` against main `26c65c2` was conflict-free;
no merge was performed and the draft remains unmerged. Main can receive automated
research data updates, so recheck its current head before eventual integration.

This initial build session has finished writing; no overnight worker process is
running in the local workspace. The scheduled continuation may start its next
independent milestone after reading the current remote checkpoint. Local worktree
`kalshi-data-pipeline` is dirty because source was published through GitHub tools;
its saved content is already remote. Do not treat those files as unpublished new
changes or reset an unrelated dirty worktree.

## Third milestone: unconfigured R2 SDK adapter

Resumed from remote head `01b1a4e7e79cd10ce641c4d4cde3441f8563fb4b` in a fresh
clean clone. The latest existing CI run **40454107348 passed**. The checkpoint
reported no active worker; no newer remote work was present before this milestone.

Added `services/research/r2.py`, twelve real botocore stub tests and pinned SDK
requirements. Conditional create-only PUT, explicit runtime credentials, fixed R2
endpoint, Content-MD5, bounded timeouts/retries, streaming size limits, stream
cleanup and SHA-256 read verification are implemented. The archive codec now
exports shared key validation. Current official Cloudflare/AWS references and
limitations are recorded in the research README. No hosted requests occurred.

Local verification: 32 API/research tests passed, 16 PostgreSQL tests skipped
because no disposable local PostgreSQL was configured; 7 owner-policy and 14
browser/gateway tests passed. Blueprint validation and diff whitespace checks
passed. The new 12 SDK cases are included in those counts. Full PostgreSQL
verification remains CI's responsibility. Inspect the workflow on this milestone's
commit before treating the full 69-test CI suite as passed.

This milestone changes only research code/tests, SDK dependencies, documentation
and this checkpoint. Existing live collector, loss prevention, table/full-sample
metrics, Worker and hosting configuration are untouched. No merge, deployment,
provisioning, credentials, Google account setup or trading occurred.

## Next independent milestones (complete in order, adjust to evidence)

1. Inspect newest remote head and its CI first. The queue, archive codec and R2
   adapter are implemented: do not redo them. If CI fails, fix that before new work.
   This run finishes after saving and inspecting its CI; no worker stays running.
2. Incremental coverage planner and resumable worker adapter using the queue.
   Distinguish fetched page from complete series/date coverage, bounded shared
   provider rate budgets, retries/deadlines, empty vs unavailable vs failed data.
   Test interrupted/restarted collection reuses pages and gaps are not hidden.
   Review existing collector before rewriting; preserve settled-only and price
   provenance rules. Use official current Kalshi docs for provider behavior.
   Develop with a fake provider/object adapter; no new account connection needed.
3. Versioned dataset/run membership and precomputed research summary storage.
   Atomically publish complete datasets, retain previous runs, never mix latest
   with cumulative or replace full-sample counts with an observed subset.
4. Authenticated read-only historical run/date queries with keyset pagination,
   indexed SQL and tests. Keep any owner mutations session+CSRF protected. Update
   gateway allowlist/response validation deliberately when adding API routes.
5. React/TypeScript research shell and historical browser may follow a stable
   API contract. Reuse familiar current table behavior. No live hosting required.
6. Measure representative local performance and record reproducible timings.
   Do not promise a speedup from code structure alone or synthetic tiny samples.

Prefer a complete tested milestone per continuation. Save code/checkpoint in the
remote draft branch so workspace expiration cannot erase it. Inspect PR diff and
CI; report verified outcomes, pending work and owner-only blockers honestly.

## Owner-only items to leave pending

Google Web OAuth client/public client ID, hosted resource/budget authorization,
secure runtime secrets, R2 bucket/access configuration and retention policy, real
R2 read/write acceptance, and real staging sign-in acceptance. No need to wake
owner or repeatedly ask for these during this build. The adapter's SDK tests do
not establish hosted R2 access, durability policy or network timing.
