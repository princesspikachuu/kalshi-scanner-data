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
passed. The new 12 SDK cases are included in those counts. **CI run 40459061835 passed** on implementation commit
`6af4f5efc284e72ceac32ad31d75db962ab162e1`: 48 API/research tests (including all
16 actual PostgreSQL cases), 7 owner-policy tests and 14 gateway/client tests.
No skips in CI: **69 automated tests plus Blueprint validation passed**. Logs
confirmed no deployment job ran. Local dependency consistency check also passed.

This milestone changes only research code/tests, SDK dependencies, documentation
and this checkpoint. Existing live collector, loss prevention, table/full-sample
metrics, Worker and hosting configuration are untouched. No merge, deployment,
provisioning, credentials, Google account setup or trading occurred.

## Fourth milestone: incremental inventory planner and page worker

Started from actual remote `8f35906444ecd682423e245d2c0042c0c32298b7`;
**CI 40459196934 passed**. Prior checkpoint reported no active worker. Used fresh
worktree `pocket-incremental`; did not overwrite previous saved dirty worktrees.

Added `inventory.py`, `budget.py`, migration 0005 and inventory tests. Scopes are
series/source/day/generation identities; one historical index is shared by all
days per series/generation. Planner explicitly returns every requested scope as
fetch/resume/complete/empty/unavailable/failed. Contiguous terminal evidence AND
job success are required for complete inventory. Completion is never quote
coverage, normalized data, a published dataset or proof of a provider snapshot.

A one-page provider-injected worker ties the queue to verified immutable archive
receipts, resumes committed cursors, rejects page gaps/cycles/caps, fences stale
leases and finishes terminal checkpoints after crashes without refetching. Shared
PostgreSQL read-token reservations/cooldowns bound concurrent application reads.
Endpoint costs and budget configuration are explicit; no account tier is assumed.
No provider HTTP transport, daemon or account connection was added. Fake provider
and archive storage make this milestone testable without credentials.

Reviewed `scripts/collect_backtest.py` and official current Kalshi docs (research
README links). Historical market lists have no close-date filter; their cutoff
uses SETTLEMENT time, not close time. Therefore new plans retain both recent and
historical sources and do not infer routing from close-day alone. The old collector
is untouched. Raw inventory retains all provider fields and price strings; settled
selection/normalization and cross-source ticker deduplication remain future work.

Local verification: 38 API/research, 7 owner-policy and 14 gateway/client tests
passed; 26 PostgreSQL cases skipped without a local disposable database. Blueprint
validation and diff checks passed. The new tests are 6 pure and 10 actual-PG cases.
**CI run 40465273241 passed** on implementation commit
`f7f0a83a6728e890e2696105fba304096566988a`: all 64 API/research tests (26 actual
PostgreSQL cases), 7 owner-policy and 14 gateway/client cases passed without skips.
Total **85 automated tests plus Blueprint validation**. Job logs confirm no
provisioning/deployment job ran. Compile and dependency consistency checks passed.
This run has finished writing code; no worker remains active. README records integration contract, retries, deadlines, archive
orphans, shared-budget scope and provider snapshot limitations. No deployment,
provisioning, infrastructure mutation, owner email/credentials or trading occurred.

## Next independent milestones (complete in order, adjust to evidence)

1. Inspect newest head and CI. Queue/archive/R2 and inventory planner/worker are
   implemented; do not redo them. Fix any CI failures before adding features.
   No background worker remains running when this run finishes.
2. Add a read-only Kalshi HTTP provider adapter (one bounded request per worker
   step) with stub tests, strict schema/error handling, Retry-After mapping and
   no credentials or live collection required. Verify official current API docs.
   The injected provider contract is in `InventoryWorker` and the research README.
   Keep historical-series index reuse and both-source inventory planning.
3. Normalize inventory to settled yes/no candidates by exact UTC close day;
   deduplicate cross-source tickers without losing immutable provenance. Add
   resumable candle/trade evidence collection with <=1-day strategy horizons.
   Never call inventory empty/complete a full-sample return result. Preserve
   original settled-only, bid/ask price-unit and maker-fill provenance rules.
4. Versioned dataset/run membership and precomputed research summary storage.
   Atomically publish complete datasets, retain previous runs, never mix latest
   with cumulative or replace full-sample counts with an observed subset.
5. Authenticated read-only historical run/date queries with keyset pagination,
   indexed SQL and tests. Keep owner mutations session+CSRF protected. Deliberately
   update gateway allowlists when adding API routes.
6. React/TypeScript shell/history browser after a stable API contract. Preserve
   familiar table behavior. No hosting required. Measure representative local
   performance later; no speedup claims from tiny synthetic samples.

Save code/checkpoint in the remote draft branch; inspect PR diff and CI. Main has
later live table fixes and automated data updates: recheck/reconcile before any
future authorized integration. Do not merge or deploy during this build.

## Owner-only items to leave pending

Google Web OAuth client/public client ID, hosted resource/budget authorization,
secure runtime secrets, R2 bucket/access configuration and retention policy, real
R2 read/write and staging sign-in acceptance. No owner involvement is needed for
the next pure-code milestones. No hosted credentials or owner email belong here.
