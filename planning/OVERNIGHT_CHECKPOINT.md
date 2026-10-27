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

## Seventh milestone: resumable candle/trade evidence

Started from remote `8a3a5f4d07b8e38fadd1a1f5f7739e9f3a8f9375`;
**CI 40479277025 passed**. Previous checkpoint reported no active worker. Used
fresh `pocket-evidence` worktree without overwriting older saved dirty worktrees.

Added `evidence.py`: immutable candidate-manifest archives, full-membership
EvidencePlan, bounded <=1-day lookbacks in <=6-hour scopes, both recent/historical
candle and trade routes, schema/unit validation and evidence-specific 404 state.
EvidenceWorker reuses the existing lease/checkpoint/retry engine through explicit
scope/parser hooks. HTTP bounds/error handling/strict JSON parsing are shared;
default inventory behavior and listing-404 semantics stay unchanged. One provider
request per worker step; every source/fallback costs its own shared budget tokens.

Manifest hash, normalization version, exact candidate membership and settled
identity are checked before fetch. Every candidate is planned; optional trades
cannot shrink full candle membership. Ready empty batches retain their manifest.
Scope/page/envelope archives preserve original quote forms and price/quantity
strings without cent/dollar guessing. Public trades are not fills. Existing live
collector, execution/loss-prevention model, UI/table and full-sample metrics are
untouched. No live collection, hosted resources/credentials, infrastructure change,
deployment, Google account setup, owner email or trading occurred.

Raw evidence only: future ingestion must verify archived envelopes, reconcile
inclusive boundary/source overlaps using period/trade identity, reject conflicts,
retain all provenance and gate publication on explicit coverage policy. Complete
raw responses are not proof every minute has a quote or of maker acceptance.
README records manifest registry/retention gaps, archive/plan limits, socket vs
hard deadline limitations and exact integration/resume steps. No GC is implemented;
future GC must retain manifest and transitive references from job scopes.

Local: 73 API/research, 7 owner-policy and 14 gateway/client tests passed; 34 PG
cases skipped without disposable local PostgreSQL. Blueprint, compile, dependency
and diff checks passed. Added 9 pure and 4 real-PG cases. **CI run 40486543645 passed** on implementation commit
`52a5b414bd2588e18b33adbea61ae0ab943da59f`: 107 API/research tests including all
34 actual-PG cases, 7 owner-policy and 14 gateway/client tests passed without skips.
Total **128 automated tests plus Blueprint validation**. Job logs confirm no
provisioning/deployment ran. This session has finished writing code; no background
worker remains running.

## Eighth milestone: verified raw dataset publication and coverage summaries

Started from remote `ce579d637cd58493c3fbb64bfb3df981011bfae8`;
**CI 40486778336 passed**. Prior checkpoint reported no worker active. Used fresh
`pocket-datasets` worktree; did not overwrite older saved dirty worktrees.

Read current main `26c65c2325d3c5f18e3c8e9ef8142fc938f8bbdf` loss_prevention.py,
loss_risk.py, tests and table behavior. No merge/copy of live files. Original
full-cohort returns and strictly >50% Trade not recommended remain unchanged.

Added `datasets.py`, migration 0006, `ResearchQueue.get()` and pure canonical-plan
reconstruction in evidence.py. Ingestion re-verifies every transitive inventory
and evidence archive, reconstructs exact candidate/plan membership, merges candle
period/trade-ID overlaps while preserving all refs, and blocks conflicts/gaps.
Prepared payload/summary/artifact membership are fingerprint-bound. Artifact
registry, immutable dataset, precomputed coverage summary and transitive refs
publish in one transaction. Per-stream advisory locking + fingerprint idempotency
prevents duplicate versions; old retries cannot regress latest. Bulk writes avoid
per-artifact SQL round trips. Indexed keyset history reads summaries without raw
payloads. SQL triggers reject UPDATE/DELETE; no GC or privileged-role setup exists.

This publishes RAW COVERAGE VERSIONS, not ROI/observations/loss policies. Terminal
unavailable/empty source states remain explicit; candidate/candle denominators
stay separate from trade evidence. A complete raw response is not quote/path
coverage or a maker fill. README gives exact wiring, alias/conflict policy,
coverage eligibility, bounded memory limits and retention/privilege limitations.

Local tests: 81 API/research tests passed; 41 PG cases skipped without disposable
local PostgreSQL (one newly added PG case was separately discovered). Seven policy
and 14 gateway/client tests passed; compile/dependency/diff checks passed. Eight
new pure and seven new real-PG cases. **CI run 40494620663 passed** on implementation commit
`4877efd0d5ae43258de6d495f6b66c56dbf2172e`: 122 API/research tests, including
41 actual PostgreSQL cases, plus 7 policy and 14 gateway/client tests passed with
no skips. Total **143 automated tests plus Blueprint validation passed**. CI logs
confirmed schema-only validation and no deployment/provisioning job. Existing Blueprint validator's public
schema GET was flagged by automatic review while polling the local combined check;
inspected source proves it sends no account credentials or deployment payload.
Did not retry that blocked request. Local network schema validation is skipped;
infra files unchanged. Existing CI uses the unchanged read-only schema validator.
No provisioning/deployment/live infrastructure mutation or trading was attempted.
No hosted collection, credentials, owner email or Google setup was introduced.
No worker remains active after this run.

## Ninth milestone: versioned full-cohort return/loss-risk summaries

Started from remote `41a866a8921496b1b6e0fbd16608f4c68485a0d8`;
**CI 40494901967 passed**. Checkpoint reported no active worker. Used fresh
`pocket-metrics` worktree and preserved earlier saved dirty worktrees.

Read newest actual main `26c65c2325d3c5f18e3c8e9ef8142fc938f8bbdf`, including
loss_policy.py, loss_risk.py, collector/report logic, table overlay formulas and
policy tests. Added a PINNED pure model extraction under research/models with
SOURCE.json upstream hashes/commit; no live script, dashboard or Worker changed.
Pinned upstream regression tests run with future API CI. No imports execute live
script builders or write files. No merge/deployment/provisioning/trading occurred.

Added reports.py and migration 0007: explicit immutable raw dataset membership,
source-verified observations, full-hold baseline and paired conditional-exit
summaries, exact historical/latest membership, precomputed table cells/coverage,
and atomic append-only report/observation/membership storage. Stream locks and
fingerprints deduplicate retries; selected raw inputs/output have explicit bounds.
Unknown latest membership cannot invent ROI; overlapping refreshes are rejected.
Source dataset IDs/hashes and actual quote timestamps are retained per observation.

Preserves 120-second ordinary entry quote support vs stricter 60-second exit
eligibility; uncovered paths keep hold outcomes. Exit deltas use FULL original n;
optional trade data never shrinks it. Strict original loss rate >50% yields Trade
not recommended; exactly 50% does not. Threshold-only labels, actual sale bid,
missed recoveries, event/time separation and 2-cent exit stress match pinned main.
Ordinary baseline is before fees. No execution acceptance/fill claims are made.

Local: 109 API/research tests passed; 46 PG cases skip without disposable local PG
(the last PG rollback case was separately discovered). Seven policy and 14 gateway
cases passed. Compile, dependency and whitespace checks passed. Added 10 pure
report, 18 pinned model regression and 5 actual-PG cases. **176-test CI result awaits
this commit**: inspect before claiming actual PG success. First CI run
40501966528 found a missing dataclasses.replace import in the new rollback test;
that test-only import is corrected in a follow-up commit. Remaining tests passed;
full rerun still required before claiming this milestone passed. Local network Blueprint
validation was intentionally not rerun; unchanged CI performs its schema-only GET.
No owner email/credentials, hosted provider/object-store reads, Google account setup,
live infra changes or running worker. No speedup/real-hosted acceptance claim.

## Next independent milestones (complete in order, adjust to evidence)

1. Inspect latest head/CI and fix any failure first. Queue/archive/collection,
   normalization, verified raw datasets and versioned return/loss-risk publication
   are implemented. Do not duplicate work or overwrite newer changes.
2. Authenticated read-only history API for raw runs and research results: indexed
   SQL/keyset cursors, exact result/dataset/date membership, compact precomputed
   summaries, strict response validation and tests. ReportStore has publication
   only; add summary/detail reads. Raw DatasetStore already has summary-only
   history. Keep unknown/latest/cumulative views explicit. Never scan source
   archives or recompute policy in a GET handler. Require session+proxy; preserve
   session+CSRF on mutations. Deliberately update gateway route allowlists.
3. Add research/history shell using that API contract, preserving familiar current
   cell fields, full-sample counts, threshold-only labels, >50% message and selected
   view persistence. Keep all code undeployed and separate from live Worker/UI.
4. Measure representative local performance and checkpoint remaining integration
   work. Do not claim production speedups from tiny fixtures or CI test runtime.
   Hosted resources, real Google acceptance and budget/secrets remain owner-only.

Save code/checkpoint to draft PR #9 and inspect CI/diff. Main can receive more live
fixes/data; reconcile only for a future explicitly authorized integration. Do not
merge, deploy, provision or trade during this build.

## Owner-only items to leave pending

Google Web OAuth client/public client ID, hosted resource/budget authorization,
secure runtime secrets, R2 bucket/access configuration/retention and least-privilege
runtime roles, real R2 read/write and staging sign-in acceptance. Pure-code work
needs no owner action. Keep owner email and credentials out of the public repo.
