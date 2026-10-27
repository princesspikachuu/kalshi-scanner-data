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

## Fifth milestone: bounded read-only Kalshi inventory transport

Started from actual remote `a9cf2b1d0320559e9a855f1f0b2a621c6d1bfac1`;
**CI 40465419537 passed**. Previous checkpoint reported no worker active. Used
fresh `pocket-http` worktree; did not overwrite earlier saved dirty worktrees.

Added `services/research/kalshi.py` with an owned, credential-free HTTPX client:
fixed public HTTPS GET listing routes, no redirects/environment auth/proxies or
forwarded cookies, one read per worker step, zero internal retries, 8 MiB raw-body
cap, identity encoding, strict JSON/page validation, safe failure codes and stream
cleanup. Original prices and extra fields survive unchanged. Listing 404/errors
never become synthetic empty/unavailable success. No Kalshi call was made.

Retry-After handles seconds/HTTP dates; full shared provider cooldown can exceed
the queue retry limit without allowing early requests. The existing budget and
ProviderFailure contract gained a separately bounded cooldown (queue retries stay
<=3600 seconds). Rate limits and temporary service failures share the cooldown.
Added 14 HTTP-stub cases plus two actual-PG queue/adapter integration cases for
long rate-limit/reclaim/cursor reuse and invalid-page/404 failure without progress.

Local: 52 API/research, 7 owner-policy, 14 gateway/client tests passed; 28 PG cases
skipped without a disposable local database. Blueprint, compile, dependency and
diff checks passed. **CI run 40471009009 passed** on implementation commit
`39e2c3e9de01c13037706c0b400c4a7f83942d09`: 80 API/research tests, including all
28 actual PostgreSQL cases, 7 owner-policy and 14 gateway/client tests. No tests
skipped in CI: **101 automated tests plus Blueprint validation passed**. Job logs
confirm no deployment/provisioning ran. This session has finished writing code;
no worker process is running. README records exact wiring,
strict response assumptions, cooperative deadline limitations and shared-budget
scope. No runner, schedule, deployment, resource, hosted migration, owner email,
credentials, Google setup, infrastructure mutation or trading was introduced.

## Sixth milestone: verified settled-candidate normalization

Started from remote `0e919bd810d3204ccc988647612a6c664dc75208`;
**CI 40471155065 passed**. Checkpoint reported no active worker. Used fresh
`pocket-normalize` worktree without overwriting prior saved dirty worktrees.

Added `normalize.py` and `ResearchQueue.page_evidence()` (read-only committed
page/archive receipt join). Normalization requires complete succeeded recent and
historical inventory for each requested series/generation. Gaps remain explicit
and return NO candidate cohort. All selected objects are checksum/length verified
and their scope/checkpoint/cursor/count are checked against DB page evidence.
Cross-source/page duplicates retain confirming object/job/page/row references;
conflicting outcomes or market identities reject the whole batch. Multiple
complete jobs for a scope require explicit run membership selection.

Reviewed current collector and official current schemas. Eligibility preserves
result exactly yes/no and half-open UTC close day; offsets/fractional seconds are
handled exactly. No sampling, price conversion, quote selection, fill simulation,
ROI, dataset publication or dashboard change occurred. Original price strings and
other provider fields stay in immutable archives. Frozen records include a stable
versioned membership/provenance fingerprint. Row/page limits fail, never truncate.
README records integration, gap semantics and bounded in-memory scan limitations.

Local: 64 API/research, 7 owner-policy and 14 gateway/client tests passed; 30 PG
cases skipped without a disposable local database. Blueprint, compile, dependency
and diff checks passed. Added 12 pure and 2 real-PG cases. **CI run 40479071814 passed** on implementation commit
`f07425b35698f5e4269e56b4324ca6b983becf52`: 94 API/research tests, including all
30 actual PostgreSQL cases, 7 owner-policy and 14 gateway/client tests passed.
No skips in CI: **115 automated tests plus Blueprint validation passed**. Job logs
confirm no deployment/provisioning ran. This session has finished writing code.
No hosted requests/resources/credentials/owner email, deployment, live infra
mutation, Google setup or trading. No worker remains active after this run.

## Next independent milestones (complete in order, adjust to evidence)

1. Inspect newest remote head and CI; fix failures first. Existing queue/archive,
   R2, planner/worker, HTTP inventory transport and normalization are implemented.
   Do not redo them or overwrite newer work. Read research README contracts.
2. Add resumable candle/trade evidence scopes and bounded read adapters, using
   normalized candidate references and <=1-day strategy horizons. Preserve both
   source routing/fallback evidence, bid/ask price units, settled-only selection
   and maker-fill provenance rules. Review existing collector/execution model
   and current official API docs. Use stubs; no live collection is required.
3. Versioned dataset/run membership and precomputed research summary storage.
   Atomically publish complete datasets; retain prior runs. Never mix latest with
   cumulative or replace full-sample counts with an observed/execution subset.
   Normalize outputs are in-memory only; design durable schema/publication here.
4. Authenticated read-only historical run/date queries with indexed SQL, keyset
   pagination and tests. Owner mutations remain session+CSRF protected. Deliberately
   update gateway allowlists when routes are added. No hosting needed.
5. React/TypeScript research shell/history browser after stable API contract;
   preserve familiar current table. Measure representative local performance later,
   without promising speedups from structure or tiny synthetic samples.

Save independent code/checkpoint milestones to draft PR #9 and inspect CI. Main
has later live table fixes/automated data updates; reconcile only for a future
explicitly authorized integration. Do not merge, deploy, provision or trade.

## Owner-only items to leave pending

Google Web OAuth client/public client ID, hosted resource/budget authorization,
secure runtime secrets, R2 bucket/access configuration and retention policy, real
R2 read/write and staging sign-in acceptance. Further pure-code milestones need
no owner action. Do not add hosted credentials or the owner email to this repo.
