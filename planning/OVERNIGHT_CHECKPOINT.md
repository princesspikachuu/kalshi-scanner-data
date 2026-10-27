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

Added reports.py and migrations 0007/0008: explicit immutable raw dataset membership,
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

Local: 109 API/research tests passed; 47 PG cases skip without disposable local PG
(the last PG rollback case was separately discovered). Seven policy and 14 gateway
cases passed. Compile, dependency and whitespace checks passed. Added 10 pure
report, 18 pinned model regression and 6 actual-PG cases. **CI run 40502592972 passed** on implementation commit
`c0b20bf4cf06123f9978f867beb6b585332a2c88`: all 156 API/research tests (including
47 actual PostgreSQL cases), 7 policy and 14 gateway/client tests passed without
skips. Total **177 automated tests plus Blueprint validation**. No deployment or
provisioning job ran. First CI run
40501966528 found a missing dataclasses.replace import in the new rollback test;
that test-only import is corrected in a follow-up commit. Remaining tests passed;
rerun 40502245909 passed all 176 tests plus Blueprint validation. Final review
added publication seals (migration 0008) and a late-child-insert regression: child
rows must share the parent publication xid, preventing later INSERTs as well as
UPDATE/DELETE. Final 177-test rerun passed, including rollback and late-child-insert protection. Local network Blueprint
validation was intentionally not rerun; unchanged CI performs its schema-only GET.
No owner email/credentials, hosted provider/object-store reads, Google account setup,
live infra changes or running worker. No speedup/real-hosted acceptance claim. This session has finished writing code;
no background worker remains active.

## Tenth milestone: authenticated precomputed history/result reads

Started from actual remote `7603ceb4b647c229d7bd9dcd5e629496a6b0847b`;
**CI 40502928319 passed**. Read this remote checkpoint before files. No newer head
or active collection/test worker was found (the Codex runtime itself is active).
Used fresh `pocket-history` worktree; older saved dirty worktrees remain untouched.
PR #9 remains draft/unmerged. Main has advanced to `9ede11b7` per PR metadata;
no live files were copied or merged. Reconcile main only in future authorized work.

Added separate HistoryStore SQL projections, closed versioned response models and
four authenticated GET routes: published raw dataset coverage pages, compact report
history, explicit historical/latest table cells and exact paginated dataset/hash/
UTC-date/latest membership. Existing stream/id and membership indexes serve keysets.
IDs are strings externally (safe beyond browser integer precision), numeric in SQL.
Cursors are signed/domain-separated with existing server key and bound to stream,
collection and parent result. Limits/unknown or duplicate queries/unsupported stored
versions fail closed. Unknown result/wrong stream is 404, empty cohort is explicit.

No GET fetches archives, scans observations or recomputes research. Raw coverage
and report metadata are projected without raw payloads/missing-slot lists; table
cells have bounded SQL and API validation. Original full-sample counts, assets,
entry grids and strict >50% loss labels are checked. Unknown latest cannot invent
rows/counts. Both proxy AND owner session required; login/logout CSRF unchanged.
Staging gateway deliberately allowlists only these GET routes, bounded queries and
responses; research cannot set auth cookies. Existing live Worker/table untouched.

Local: **115 API/research tests passed**, **51 PG tests skipped** without a local
disposable database; 7 policy and 17 gateway/client tests passed. Added 6 contract/
auth/cursor/full-sample tests, 4 real-PG history/membership/bigint cases and 3 gateway
cases. Compile/dependency/whitespace checks passed. **CI run 40510266525 passed** on implementation commit
`53b95f6c5d5a38e2090b0b55f30e30b2fb0aeb44`: all 166 API/research tests (including
51 actual PostgreSQL cases), 7 policy and 17 gateway/client tests passed with no
skips. Total **190 automated tests plus Blueprint validation passed**. Logs confirm
all four new PG history cases (including numeric bigint ordering across a digit
boundary) and schema-only validation; no deployment/provisioning job ran. Do not rerun the previously review-blocked local Blueprint schema request;
unchanged CI validates it read-only. No hosted requests, credentials, Google setup,
provisioning, infrastructure mutation, deployment or trading occurred.

Limitations: published dataset history only (not in-flight queue monitoring), no
arbitrary date-subset recomputation, no research shell yet. Keysets are independent
reads, not a cross-request transaction snapshot; a late commit of an older allocated
ID may require a fresh traversal. Key rotation invalidates cursors. Hosted acceptance
and representative performance are unverified. Exact API/SQL/gateway limits and
resume wiring are documented in services/api/README.md and research/apps READMEs.
This session has finished writing code; no collection daemon or background worker
remains active. Implementation and verified CI are durably checkpointed before UI work.

## Eleventh milestone: requested long-range backfills and rolling updates

User's next explicit request supersedes the shell-first order: enter historical
start/end dates, process a section at a time until finished, and automatically
update the preceding 24 hours. Continued from actual remote `e63e093` with passing
**CI 40510491073** in fresh `pocket-backfill`. Existing worktrees preserved; no
background collector was active. Full app stays undeployed.

Added migration 0009 and durable campaign/section/job membership, exact-window
normalization (separate WindowBatch leaves old batch fingerprints unchanged),
one-child-page coordinator, restart-safe manifest/job planning, completed-section
reuse and explicit recheck. Healthy yields do not exhaust failure budgets; targeted
child claims and parent/child fencing preserve retry/cancel semantics. Pause/resume
retains immutable pages. A finished campaign requires every raw section AND a
combined precomputed report with exact membership. Report publication streams raw
sections one at a time; existing pinned full-cohort math has a pre-refactor golden
hash regression. Missing coverage never shrinks denominators or becomes success.

Added owner-session/proxy/CSRF collection controls and a separate development date
form/progress page. Inputs support <=3660 inclusive UTC days, today clipped at
creation. Latest/cumulative report membership is this explicit requested range,
not overlapping historical refreshes. Hourly refresh setting starts OFF. Injected
runner coalesces due work, prevents concurrent rolling campaigns per category and
freezes exact [now-86400s,now) windows across midnight/DST; old versions stay intact.
No scheduler/process was started, no resources/credentials/live requests were used.

Local: 122 API/research cases, 7 owner-policy and 19 gateway/client cases passed;
58 actual-PG tests skipped without a local disposable database. Compile, dependency
and diff checks pass. Seven new PG campaign tests cover multi-day completion,
combined counts, historical-index reuse, cursor recovery/pause/fencing, retry/
cooldown, exact section reuse/recheck, scheduler concurrency, 24-hour exclusion,
idempotency across midnight and empty cohorts. **CI run 40515434701 passed** on implementation
`d7ed9beaa8c1c88d404ff7f39de5a15507d4cdef`: all 180 API/research cases (including
58 actual PostgreSQL tests), 7 owner-policy and 19 gateway/client tests passed with
no skips. Total **206 automated tests plus Blueprint validation passed**. Inspected
all seven new PG campaign results and logs; no deployment/provisioning job ran.
The golden streamed-report fingerprint matches the unmodified e63e093 model.

Limits/remaining: dense ranges can exceed explicit report entry/path/output bounds;
then raw sections stay saved and the combined report fails explicitly, never samples.
Only settled markets enter research; older late settlements require backfill recheck.
Current page is collection/progress, not the complete research table/history shell.
The finished result_id is readable through the authenticated research API under
stream campaign-{UUID without hyphens}. Next UI work should render saved cells
from that exact report and dataset membership; do not recompute in GET or browser.
The worker loop requires injected configured adapters and must eventually run as a
server process. Hosted resources, runtime budget, least-privilege/retention/secrets,
Google OAuth and real acceptance remain pending owner steps. Full details and exact
runner/API wiring are in services/research/README.md and services/api/README.md.
No merge/deployment/provisioning/live infrastructure alteration or trading occurred.
This build session has finished writing; no background worker is left running.
Auto settings remain OFF in the schema by default; no hosted setting was changed.

## Twelfth milestone: owner-created secret group and concrete staging wiring

Owner provided a public Google Web client ID privately, enabled R2, and reports
creating the private archive bucket/credentials plus an unlinked Render environment
group named pocket-r2-staging. No secret values were retrieved. Render repository
build access was explained but still needs confirmation if the repo is not visible.
Resumed from actual remote `5eb069c`; CI 40515944133 passed. Used fresh pocket-runtime
worktree and preserved the older dirty kalshi-data-pipeline worktree.

Added services/research/runtime.py: exact R2 environment names, private DB config,
explicit read budgets, no ambient credentials/alternate exchange host, secret-safe
errors/repr and an offline --check-config mode. COLLECTION_ENABLED defaults false;
disabled mode opens no DB/R2/HTTP clients and does not schedule work. Enabled mode
wires the verified archive, shared budget, targeted page workers, campaign scheduler
and publication loop. SIGTERM/SIGINT stop accepting work and close clients/pool.
No process was started here. Six new unit cases verify gating, safe configuration,
resource cleanup, signal restoration and actual adapter-constructor wiring via mocks.

Updated the UNLINKED Blueprint with one research worker, referencing only the
owner-created R2 group, explicit development branch and internal database connection.
API gets no R2 group. Auto deploys/previews remain off, collection remains false,
DB public access stays disabled and disk autoscaling is off. Proposed plans: API
0.5c-512mb, research worker 1c-2g, DB 0.5c-1g with 5 GB storage, all Oregon. This is
a costed sizing proposal, not measured capacity or a claim all dense ranges fit.
CI schema guard now enforces collection-off and credential-group separation.

infra/STAGING_LAUNCH.md records the exact branch/file/commands, secret prompt fields,
private-network/deploy sequencing, startup checks, outstanding privileges and real
connection acceptance, and a current official-source budget: about $52.50/month
Render compute+5GB disk, plus taxes/workspace/usage as applicable and Cloudflare/R2
overages. No trading service. Markdown docs were unreadable by the web fetch tool;
read the official HTML alternatives. Local network schema validation was not retried;
CI performs the existing read-only schema GET. No deployment or resource mutation.

Verification: six runtime cases pass locally after correcting an adapter class-name
import found during development. Clean local rerun: 128 API/research cases passed, 58 PG cases skipped without a
disposable local DB; 7 policy and 19 gateway cases passed. Dependency/compile/diff
checks pass. **CI run 40533487349 passed** on implementation commit
`6d501a35b32fa0facfe9843406b48535391643f2`: all 186 API/research tests (including
58 actual PostgreSQL cases), 7 policy and 19 gateway/client cases passed without
skips. Total **212 tests plus updated Blueprint validation passed**. No resource
creation, deployment, hosted migration or collection occurred. Do not claim hosted keys,
group contents or connection tests passed: the Render connector has no env-group
inspection tool and only the owner has entered the values. No secrets in source.

Next: present the exact paid staging
proposal before asking owner to authorize resource creation/initial staging deploy.
Do not sync/create a Blueprint merely because the owner finished an environment
group. The group's contents/linkability, owner login and tiny R2 read/write acceptance
still need verification after authorized staging creation. Harden DB runtime roles
before enabling collection. Full table/history shell and performance work remain.

## Next independent milestones (complete in order, adjust to evidence)

1. Inspect latest head/CI and fix any failure first. The user-requested date-range
   campaign/rolling-refresh milestone takes priority over the old shell-first plan. Queue/archive/collection,
   normalization, verified raw datasets and versioned return/loss-risk publication
   are implemented. Do not duplicate work or overwrite newer changes.
2. Authenticated published dataset/result history API is implemented in the tenth
   milestone. Inspect newest CI first. Read services/api/README.md and history.py
   contracts before adding clients; use exact result ID/stream and source membership,
   explicit view and opaque keysets. No GET recomputation or source archive reads.
3. Expand the collection controller into the research/history shell using that API contract, preserving familiar current
   cell fields, full-sample counts, threshold-only labels, >50% message and selected
   view persistence. Keep all code undeployed and separate from live Worker/UI.
4. Measure representative local performance and checkpoint remaining integration
   work. Do not claim production speedups from tiny fixtures or CI test runtime.
   Hosted resources, real Google acceptance and budget/secrets remain owner-only.

Local resume: fetch actual branch into a fresh worktree; create a new Python venv,
install services/api/requirements-dev.txt; run `python -m unittest discover -s
services/api/tests -v`, `python -m unittest discover -s tests -p test_auth_policy.py
-v`, `node --test tests/test_login_bridge.mjs`, compileall, pip check and git diff
--check. Actual PostgreSQL tests require an explicitly disposable /pocket_test DB;
otherwise verify all PG cases in CI. No hosted migration or provision is authorized.

Save code/checkpoint to draft PR #9 and inspect CI/diff. Main can receive more live
fixes/data; reconcile only for a future explicitly authorized integration. Do not
merge, deploy, provision or trade during this build.

## Owner-only items to leave pending

Public Google client ID received and R2 group creation reported by owner. Still pending:
hosted resource/budget authorization,
secure runtime secrets, R2 bucket/access configuration/retention and least-privilege
runtime roles, real R2 read/write and staging sign-in acceptance. Pure-code work
needs no owner action. Keep owner email and credentials out of the public repo.
