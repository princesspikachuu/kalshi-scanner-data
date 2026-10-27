# Pocket Analytics continuation checkpoint

## Current owner setup authorization (October 27, 2026)

This supersedes the earlier overnight prohibition ONLY for the separate staging
stack: owner selected the smaller API $7, research worker $7, Postgres $6 and
5 GB disk budget $1.50, approximately $21.50/month plus applicable usage/taxes.
Initial staging creation/deployment is authorized; no automatic upgrades.
COLLECTION_ENABLED stays false, service auto deploys off, DB private. No merge,
live Worker change or trading. Owner reports billing added manually. Browser plan
was reviewed at the old $52.50 size, but no resources were created; automatic
approval review blocked that attempt. Refresh the plan from this new commit and
verify the lower price before applying. Private email/config stays out of git.

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

## Smaller staging sizing checkpoint

Resumed from remote 858d943; CI 40533797897 passed. Owner chose smaller plans
after price review: worker 0.5c-512mb, database 0.1c-256mb; API unchanged.
Launch estimate updated to approximately $21.50/month including 5 GB disk budget.
No code/model/table/full-sample behavior changed. No capacity claim: benchmark
representative workloads before enabling collection or considering upgrades.

Resume: inspect newest remote CI, reopen Render Blueprint creation with development
branch and infra/render.staging.yaml, verify the new $21.50 estimate and private
settings, then apply initial staging only. Disable Blueprint auto-sync after creation
as well as existing service auto deploys. Inspect migrations/readiness and disabled
worker logs; record actual resource/deploy IDs. Google gateway acceptance, R2
read/write verification, runtime privilege hardening and collection enablement remain
separate pending steps. No resources or hosted collection created at this save.

## Applied smaller staging stack (October 27, 2026)

Owner authorized the smaller plan; Render review showed $21.50/month. Blueprint
exs-dbgcgusipgvc73f5pot0 created from 4fdc898. Auto Sync set No; UI confirmed
Sync paused. Service auto deploys remain off. No automatic paid upgrades.

Verified through Render connector:
- API srv-dbgcsb6c6qcc73f1j6n0, 0.5c-512mb, Oregon, one instance.
- Worker srv-dbgcsb6c6qcc73f1j6lg, 0.5c-512mb, Oregon, one instance.
- PG dpg-dbgcrl6c6qcc73f1hi1g-a, PostgreSQL 17, 0.1c-256mb, available,
  disk 5 GB, autoscaling false, ipAllowList empty, no replicas/HA.
- Project prj-dbgcrkuc6qcc73f1hhl0; environment evm-dbgcrkuc6qcc73f1hhlg.
- Worker deploy dep-dbgcsbec6qcc73f1j7n0 LIVE; logs say Migrations applied.
- First API deploy dep-dbgcsbec6qcc73f1j820 failed pre-deploy with sanitized
  migration error. Cause unconfirmed; database error-log query returned no errors.
  One retry dep-dbgcu16gekts738i4iq0 LIVE at 16:20:42 UTC, with Migrations applied.
- API URL https://pocket-api-staging.onrender.com, healthCheckPath /health/ready.
  Render live status confirms its configured deployment health gate passed.
  Independent HTTP verification was unavailable through the web fetch tool.
- CI 40538572583 passed on 4fdc898; offline YAML sizing/privacy/gating checks and
  git diff --check passed before committing. No application code changed.

COLLECTION_ENABLED remains false in applied source. Worker live startup validates
configuration format, not R2 permissions. No collection was enabled, no trading,
no live Cloudflare Worker modification and no merge. Private API configuration
was supplied only to Render; no owner email/credential values were committed.

The local/browser environment disconnected during verification. Connector monitoring
continued; no screenshot could be saved. Older dirty worktrees were preserved.

Exact resume: inspect latest branch/CI and Render deployment statuses using IDs
above. Do NOT create duplicate resources or blindly resync the Blueprint. Applied
runtime commit is 4fdc898; later documentation commits need no deployment. Verify
private env key names/group linkage without revealing values, independently test
HTTP readiness and unauthenticated access denial, investigate migration failure if
it recurs, harden DB runtime privileges, then separately configure/test the staging
Cloudflare gateway and real owner Google login. Tiny R2 integrity acceptance and
representative memory/throughput benchmarks remain pending. Keep collection off
until connection/privilege checks and explicit enablement; no automatic upgrade.


## Staging gateway manual deployment preparation

Resumed from actual remote bc897a7, preserving older dirty worktrees in a fresh
pocket-gateway worktree. Independently verified API /health/ready HTTP 200 with
status ready, and /auth/me without proxy secret HTTP 403 Request rejected. Render
API logs show Uvicorn listening and live state. No credentials were used for these
requests and no collection was enabled.

Prepared the existing deploy-pocket-app.yml workflow on this DEVELOPMENT branch:
production job now gated to main; new staging job runs only on workflow_dispatch
and exact build/google-auth-foundation ref. This uses the already-existing workflow
entry on main so no merge/new default-branch workflow is required. Push/PR do not
deploy staging. Staging deploy uses existing repository Cloudflare secrets and only
infra/wrangler.staging.json, pinned Wrangler 4.153.0 (npm registry verified), no
production GitHub Actions token, no secret creation/overwrite. Config explicitly
names the staging Worker, enables its workers.dev hostname, disables previews,
fixes public app/API origins and preserves Dashboard bindings with keep_vars.
Nothing was dispatched/published during this save; live Worker remains unchanged.

Added scripts/check_staging_gateway.mjs to guard exact target/asset/origin fields
and dispatch branch gates; CI runs it and now watches deployment changes. Added
credential-free scripts/check_staging_http.py for readiness, direct API denial,
CSP/no-store assets, unavailable trading route and unauthenticated session boundary.
503 is an unresolved connection, not verified login; scripts omit bodies/cookies.
All 19 gateway/client tests and offline configuration guard passed, Python compiled,
and git diff --check passed. No API/model/collector/full-cohort logic changed.

Browser timed out opening the GitHub dispatch page; connector has no dispatch tool.
No local Cloudflare or Render credentials were present and no extra account/token
was requested. Do not work around the unavailable browser by enabling push deploys.

Exact resume: inspect new head/CI, then dispatch existing Deploy Pocket Analytics
dynamic Worker workflow with branch build/google-auth-foundation. On this branch
ONLY staging job should run. Confirm new Worker URL and HTTP checks; never dispatch
main for this action. Owner securely copies existing Render API_PROXY_SECRET into
Cloudflare staging Worker's Secret of the same name, directly console-to-console.
No secret in chat/git/workflow inputs. apps/README.md has exact fields and checks.
Confirm existing Google client's Authorized JavaScript origin matches staging, then
perform actual Google popup/cookie/logout acceptance. Do not create a duplicate
OAuth client. Continue with runtime-role hardening/R2 acceptance and representative
performance before separately enabling collection. All Render paid sizes unchanged.

Gateway preparation saved at c15813d5143fdcc0fedbb926c6bd73f0a507d177. CI run
40541181548 PASSED, including gateway guards, API/real-Postgres tests and Blueprint
validation. A browser recovery attempt also timed out at focus emulation; manual
dispatch remains blocked in this environment. No Cloudflare deployment was started.


## Staging gateway published; private proxy-secret binding pending

After owner completed Google device approval and GitHub device verification via
secure browserAuth, verified signed-in GitHub UI and manually dispatched the
existing workflow from build/google-auth-foundation at af11bd8. Run 40543386602,
job 122327432008: 19 gateway tests/config guards and Cloudflare deploy PASSED;
production deploy job 122327434471 SKIPPED. Cloudflare version:
34461827-22a9-4975-a185-7cbb9fac18ce. Staging Worker URL:
https://pocket-analytics-staging.ezrealrose831.workers.dev/
No main merge/live Worker update, no collection enabled, no paid size changes.

Overall deploy workflow FAILED at HTTP smoke check: received 403 expecting 200.
Original message did not identify which endpoint. Improved checker diagnostics
now name the check without printing bodies, credentials or cookies. Local
independent probes: API readiness 200/no-store, direct auth/me 403/no-store;
Cloudflare staging root and auth/me return 403 text/plain to the Python client.
Browser opens the staging sign-in page normally; browser /api/auth/me visibly
returns Sign-in connection is not configured. No bot-block classification inferred
from a bare 403, no access-control changes or user-agent/network evasion attempted.
Do not call the smoke workflow green or real login verified. Browser screenshot
saved privately; no credentials/owner email added to git.

Cloudflare dashboard required sign-in. Owner selected Google via secure browserAuth;
account selection returned submission_failed. The next normal rendered-state check
was blocked by automatic browser approval review at dash.cloudflare.com: review
could not establish authority to observe the post-auth state and interpreted it as
retrying sign-in. Authentication result is UNKNOWN. Do not retry or use alternate
browser surfaces as a workaround. Ask owner to explicitly approve a dashboard
status check/recovery before continuing. No Cloudflare secret was entered.

Resume: first inspect remote head/CI, avoid redispatch/duplicate Worker creation.
After dashboard recovery is authorized, inspect actual login state; do not assume
failure or repeat credential entry. Navigate only pocket-analytics-staging Settings.
Owner must enter the EXISTING Render API_PROXY_SECRET as a Cloudflare Secret of
the same name, copying directly from private Render API configuration. Never put
it in chat/git or frontend assets. Verify gateway auth/me becomes 401 and challenge
works, existing Google JavaScript origin matches, then owner popup/cookie/logout
acceptance. Investigate client-specific smoke 403 without weakening protections;
new labeled diagnostics identify the exact failed check on a future authorized run.
Keep collection off, API/worker auto deploy off and Blueprint sync paused.


## Proxy binding verified; Google audience blocks owner login

Owner reports completing the Cloudflare secret binding. Browser root now displays
Google sign-in button using the expected public client ID; /api/auth/me visibly
returns Sign in required instead of connection-not-configured. This verifies the
gateway/API challenge connection without inspecting or recording the private key.
Actual sign-in launched Google popup. Owner selected the existing Google account
via secure browserAuth. Google then returned 403 org_internal: Pocket Analytics
can only be used within its organization. No login session was established; no
cookie/logout acceptance claimed. Do not retry the same Google flow until the
owner fixes the OAuth audience setting; this is a specific configuration error,
not evidence of bot detection. No application code/auth boundary was weakened.

Owner-only next step: in the EXISTING Pocket Analytics Google Cloud project,
Google Auth Platform > Audience, change Internal to External (Make external), keep
Testing if offered, save. Add the chosen owner account to Test users if applicable;
Google documents that basic openid/email/profile Sign in with Google does not
require trusted test-user listing. Do not create duplicate OAuth credentials,
request Gmail/Drive scopes, or publish the app to production. The API independently
remains owner-only even with Google's audience External. If an organization policy
blocks this setting, stop and record it instead of changing org policy.
Official reference: https://support.google.com/cloud/answer/15549945

After owner reports saved: start a fresh login challenge from staging root, verify
Google popup success, refreshed current-user session and logout, then continue
least-privilege DB/R2 acceptance before explicitly enabling collection. Credentials,
owner email and callback URLs/tokens are excluded from public source. Render sizes,
collection-off, automatic-deploy-off and live Cloudflare app remain unchanged.
CI 40544709439 passed on 6401c6f; only documentation updated in this checkpoint.


## External audience consent reached; final session result unknown

Owner reports adding the account as a test user. A fresh staging challenge and
Google popup no longer returned org_internal; Google displayed consent for only
name/profile picture/email. Owner explicitly authorized that disclosure to this
staging app after automatic browser review required action-time confirmation.
Clicked Continue once. The original app initially showed its existing login UI;
subsequent rendered-state verification timed out after 300 seconds. Immediately
attempted a fresh staging tab per browserAuth recovery guidance; it also timed out
after 300 seconds. Authentication outcome is UNKNOWN, not verified success/failure.
No repeated consent/sign-in attempt, credential inspection or bypass was performed.
Render request-log query for auth/google, auth/me and auth/logout returned no logs;
this is not evidence of either authentication result. Application access logs are
intentionally disabled. CI 40546898797 passed on 6af6725.

Resume: when browser control recovers, first load the canonical staging root in a
fresh tab and inspect current-user UI. Do not repeat sign-in blindly; an owner
session may already exist. If signed in, verify persistence on reload and perform
one normal logout, then verify current-user is unauthenticated. If signed out,
inspect visible non-secret error state; a new sign-in must use a fresh challenge.
The owner consent authorization above covers the same name/profile/email sharing
with this staging app, but browser security/access rules still apply to new steps.
Never store callback URLs, tokens, cookies, private email or proxy values in git.
Collection remains disabled; hosted roles/R2 integrity/performance acceptance remain
pending, with no changes to paid plans, automatic deploy settings or the live app.

## Owner login acceptance and private diagnostic preparation

Owner independently confirmed Google login, persistence after refresh and logout.
Record these as owner-verified acceptance, not an agent-observed cookie test. Latest
remote dfe1aad CI 40549661422 passed. Fresh pocket-acceptance worktree preserves
older dirty/saved worktrees. No other remote work observed.

Render connector's read-only SQL query was blocked by the intentionally empty DB
external allowlist. Kept it private. Browser recovery also timed out before Render
worker interaction. Prepared services/research/acceptance.py and a default-off
STAGING_ACCEPTANCE runtime gate: database-v1 performs one read-only catalog/checksum
privilege audit; r2-v1 performs two conditional PUTs/two bounded GETs of ONE fixed
non-market staging marker under 1 KiB, retained immutably. No Kalshi request, DB
write or collection. Errors sanitized; disabled worker idles after one attempt,
not an application retry loop. SDK retries remain bounded. Reset flag off after
recording a result because process restarts can repeat the idempotent test.

Prepared infra/runtime-roles.sql explicit transaction, NOT a migration/deploy hook:
fresh separate NOLOGIN API/research roles with explicit object grants. No history
update/delete/truncate/trigger-alter/ownership; worker cannot access auth state.
API owner-subject/session-material updates blocked. Revoke PUBLIC CREATE on public
schema and TEMP on database to prevent temporary-table shadowing of guard lookups.
No role/password/configuration changes have been applied to hosted DB. Separate
LOGIN credentials and runtime-only URLs, plus splitting operator migrations from
runtime configuration, remain mandatory before claiming actual privilege isolation.
Do not just SET ROLE on an operator URL; original credentials can regain ownership.

infra/STAGING_ACCEPTANCE.md contains exact diagnostic flags/commands, costs/scope,
permission boundary and remaining owner credential steps. Unit cases cover fixed
R2 probe/reuse/corruption, explicit write gate, disabled collection requirement,
cleanup and sanitization. New real-PG cases cover auth/campaign/queue/budget and
publication with limited roles, denied history mutations and read-only operator
recognition. Local actual-PG cases require a disposable DB; verify them in CI.

Next: inspect this commit's CI, fix any grant failures before deployment. Then
manually deploy ONLY the existing disabled research worker at the tested head,
set temporary STAGING_ACCEPTANCE=database-v1 and read JSON audit; repeat with r2-v1
for tiny already-authorized archive acceptance. Restore off and verify final worker
live with collection false. Never expose DB or create paid resources for the audit.
Record actual receipts/findings; successful deploy does not prove a test passed.
Only after owner-controlled credential/migration separation, privilege audit and
R2 acceptance should a tiny real collection be separately enabled. Preserve full
cohort/loss-prevention behavior; no live app changes, merge or trading.

Enabled worker startup also requires the read-only database privilege audit before
opening its pool/R2/Kalshi clients. Operator credentials or a migration mismatch
fail closed even if COLLECTION_ENABLED is manually set true. A new unit case proves
that this failure constructs no collection clients. Disabled mode remains no-I/O
unless a diagnostic flag is explicitly selected.

First diagnostic CI run 40552870658 exposed test-fixture read-budget state retained
from another suite, not a grant denial. Added explicit disposable test cleanup for
that row and a real direct-login audit test; operator remains rejected. No hosted
role or collection changes made while validating.

## Verified hosted diagnostics and final disablement (October 27, 2026)

Implementation ebdde7b331008863f46f902bce77816284ae2c23 CI 40553521523
PASSED: 198 API/research tests including all 62 actual PostgreSQL cases, 7 policy
and 19 gateway/client cases = 224 tests without skips, plus Blueprint validation.
Local run: 136 API/research passed, 62 PG skipped without disposable DB; 7 policy
and 19 gateway passed, compile/dependency/diff checks passed. Earlier CI failures
were fixture-budget cleanup and test URI formatting; both corrected before deploy.

Used the existing worker's private environment; update_environment_variables merged
only COLLECTION_ENABLED=false and the temporary diagnostic flag, preserving all
credentials/group bindings. Render automatically deployed the tested branch head;
no duplicate manual deploy was triggered. Existing API/live Worker unchanged.

- Database audit deployment dep-dbge6mmc6qcc738gim8g LIVE. JSON receipt at
  17:47:26 UTC: migrations_match=true, migration_count=9, history tables found=12.
  privilege_boundary_ready=false as EXPECTED: operator owns DB/history and has
  CREATEDB/CREATEROLE/schema CREATE/TEMP/history mutation privileges. No memberships,
  superuser, replication or bypass-RLS. This verifies the boundary is still pending,
  not that hardening was applied. The enabled worker now refuses these credentials.
- R2 acceptance deployment dep-dbge7i0473hc73d7esng LIVE. JSON receipt at
  17:48:53 UTC: staging-r2-acceptance-v1, verified=true, created=true, 88 bytes.
  Exact marker key raw/v1/staging_acceptance/da/da11d92acfcd7e9ac37871a61b6645e4ea1aa890425696e9dda11339c330dcf2.json.gz
  SHA256 da11d92acfcd7e9ac37871a61b6645e4ea1aa890425696e9dda11339c330dcf2.
  Two conditional PUTs/two bounded GETs passed; reuse refused overwrite and returned
  identical bytes. The one tiny non-market object is intentionally retained. No
  archive deletion, market collection, DB write or new credential was performed.
- Reset STAGING_ACCEPTANCE=off and COLLECTION_ENABLED=false by merge; reset deploy
  dep-dbge858u01pc738na4pg started from the SAME tested ebdde7b runtime commit.
  Verified LIVE at 17:50:20 UTC. Final reset logs show only normal runtime startup;
  merged configuration is diagnostic off and collection false. API/worker plans
  remain 0.5c-512mb and both autoDeployTrigger values remain off.

Remaining owner-only boundary: securely establish separate LOGIN credentials and
runtime URLs for the proposed NOLOGIN roles, and remove operator credentials from
long-lived API/worker environments. Operator migrations need an isolated explicit
execution path; current preDeploy/runtime DATABASE_URL sharing is NOT isolation.
The role SQL has not run on hosted DB and no passwords were generated. Do not
claim production-ready/collection-ready or toggle collection until this separation
is implemented and direct-login audit passes. No paid upgrades/new resources,
main merge, live UI/table changes, trading or automatic-deploy enablement.

## Private non-login role preparation and API cutover gate

Resumed actual remote f02687c; CI 40554503924 passed. Fresh pocket-isolation
worktree preserves prior saved dirty worktrees. Owner asked to continue setup.
Next step uses no new credential: prepare only NOLOGIN roles using the existing
private operator connection, retaining collection disabled and current runtime URLs.

Added services/api/operations.py transactional role-plan application. It requires
matching migrations and DB ownership, limits target DB to pocket_staging/pocket_test,
serializes with migrations, checks final role attributes/no ownership/memberships,
and fails on existing role names rather than reusing them. Role creation/grants and
postcondition checks commit together. No password, LOGIN, URL cutover or new paid
resource. services.api.manage prepare-runtime-roles exposes the explicit command;
it is never a numbered migration or automatic preDeploy action.

Added default-off STAGING_OPERATOR_ACTION=prepare-roles-v1 to disabled worker.
Exclusive with collection/diagnostics. One bounded attempt then idle; errors omit
SQL/connection values and never retry automatically. Reset off after recording
receipt. Shared audit moved to services/api/db_privileges.py; v2 additionally
requires expected direct API/research role. REQUIRE_API_RUNTIME_DB=true opts API
startup into its own guard before opening a pool, with sanitized failures. Default
false preserves currently working operator-backed staging until coordinated cutover.
Research collection remains guarded mandatorily; no model/table changes.

Tests cover strict API flag, pre-pool rejection/allowance and secret-safe failures,
operator gating/one-attempt cleanup, actual role preparation/direct API login,
wrong-profile rejection and atomic rollback on name collision. The previous role
SQL is unchanged, and new helper is exercised by real PostgreSQL suite setup.

After CI passes: set temporary worker STAGING_OPERATOR_ACTION=prepare-roles-v1 with
COLLECTION_ENABLED=false and STAGING_ACCEPTANCE=off, inspect prepared=true receipt,
restore operator flag off and verify live. This prepares NOLOGIN roles only.
Then owner-only credential creation and coordinated migration/runtime separation
remain pending; no passwords should be generated or exposed in chat/public git.
Existing Blueprint operator references/preDeploy commands must be reconciled before
any future sync; leave sync paused. API credential cutover must enable its new gate.

Local validation: 142 API/research cases passed, 65 actual-PG cases skipped without
a disposable DB; 7 policy and 19 gateway cases passed. Compile/dependency/diff
checks passed. Hosted role preparation remains unapplied until actual-PG CI passes.

## Non-login roles prepared on staging (October 27, 2026)

Implementation 96f59f3428359daa438e89d6dd154d95e1179eea CI 40555906525
PASSED: 207 API/research including 65 actual-PG cases, 7 policy, 19 gateway =
233 tests without skips, plus Blueprint validation. No app/model/table changes.

After confirming unchanged tested head, merged only temporary worker operator flag
and explicit collection=false/diagnostics=off into existing environment. Deployment
dep-dbgee6rl550s73bnfgog LIVE from 96f59f3. At 18:03:16 UTC JSON receipt:
contract runtime-role-preparation-v1, prepared=true, login_enabled=false,
passwords_created=false, runtime_isolated=false. This confirms the transaction
created pocket_api_runtime and pocket_research_runtime NOLOGIN roles, applied the
reviewed explicit grants and PUBLIC schema CREATE/TEMP revocations, and verified
no privileged role attributes, memberships or object ownership for those roles.
No passwords were generated and existing service DATABASE_URLs were not changed.
No collected data/history was modified, no collection/R2 acceptance was started.

Reset STAGING_OPERATOR_ACTION=off, STAGING_ACCEPTANCE=off and COLLECTION_ENABLED=false.
Reset deploy dep-dbgeetqjnfac73a2iv40 started from the same tested runtime commit.
Verified reset LIVE at 18:05:14 UTC; logs show normal startup with operator/
diagnostic flags off and collection false. Independent API readiness returned
HTTP 200; no new API error logs were returned for the post-preparation interval.
API itself remains on existing 4fdc898 runtime until coordinated credential cutover;
its new strict startup gate is tested in source but is not yet enabled/hosted there.

Exact next step needs owner-controlled private credential entry, which this run
skips under the standing no-new-credentials boundary. Do NOT re-run role preparation
or silently replace these now-existing role names. Securely establish independent
LOGIN passwords for the two prepared roles. Preserve the generated DB operator
credential only in a separate explicit migration context, remove migration
preDeploy commands from API/worker before replacing their runtime DATABASE_URLs,
remove all operator credential variables from those runtime environments, set
REQUIRE_API_RUNTIME_DB=true, and deploy the tested API/disabled worker. Check
profile-specific direct-login audit and real login/logout again. Reconcile the
paused Blueprint so a future manual sync cannot restore operator URLs/preDeploy
migrations. No current Blueprint sync should be performed. Keep collection off.

Continuation boundary: ask owner whether the earlier no-new-credentials restriction
may be lifted specifically to create independent private API/research DB passwords
and store the corresponding runtime connections ONLY in Render. Do not generate
those credentials or perform the credential cutover without resolving that boundary.
This is an existing user instruction, not a requirement inferred from a skill.

## Authorized credential isolation cutover preparation (October 27, 2026)

Owner explicitly approved the prior question to create separate private API and
research DB passwords, keep corresponding connections only in Render, and switch
staging services to limited direct-login users. This lifts the original no-new-
credentials boundary only for these two staging DB roles. Collection stays false;
no paid upgrade, main merge, live Cloudflare change or trading is authorized.

Resumed actual remote 52c4dc9; CI 40556899902 passed. Existing API 4fdc898 and worker
96f59f3 were live, no deployment in progress. Fresh pocket-credentials worktree
preserves all prior dirty/saved worktrees; no other branch writer observed.

Added one-time activate-roles-v1 disabled-worker operator action accepting only
private libpq SCRAM verifiers for the two prepared NOLOGIN roles. Matching schema,
DB ownership, dedicated staging/test name, fixed role attributes/no memberships/
ownership are checked under the migration lock. Both LOGIN changes are atomic;
already-active or partially-active roles reject the entire action, with no rotation.
Plaintext passwords never enter SQL/logs. Flags are exclusive with collection and
diagnostics; output/failure messages contain no secret values. No hosted activation
has occurred at this preparation checkpoint; verify actual-PG CI before mutation.

PreDeploy compatibility: manage migrate with RUNTIME_DB_PROFILE=api/research now
performs the same read-only strict direct-role/checksum audit and NEVER calls the
migrator. The paused Blueprint source instead uses explicit verify-runtime commands,
private sync:false DATABASE_URLs and strict API gate, removing fromDatabase operator
references. Existing hosted command is safe only after the explicit profile merge;
future Blueprint sync remains paused, sync:false does not overwrite existing URLs.
Future migrations must use an isolated explicit operator context, not app runtime.

Exact resume after passing CI: create independent high-entropy passwords privately,
use libpq to calculate SCRAM verifiers, persist each pending runtime password on
its own existing Render service before activation. The activation receipt returns
only the actual host/port/database from its DB connection; use these verified
nonsecret fields to build private runtime URLs with sslmode=require.
Merge temporary verifier JSON/operator flag only on the still-disabled worker;
inspect nonsecret activation receipt. Then replace API DATABASE_URL and enable its
strict API/profile gates, inspect read-only preDeploy audit and health. Replace
worker DATABASE_URL/profile, clear temporary verifiers/pending-password fields and restore
flags off; inspect research profile audit and live disabled startup. Do not print
secrets or raw env responses; do not reopen public DB or rerun role preparation.
If activation receipt is uncertain, inspect it before any retry/credential generation.
Finish with verified deploy IDs/results, CI and limitations in a new checkpoint.
Owner must retest real browser login after cutover; representative performance,
complete history/research shell and separately authorized tiny collection remain.

Implementation ff13f87 CI 40561269120 PASSED: 212 API/research including all 67
actual PostgreSQL cases, 7 policy, 19 gateway = 238 tests without skips, plus
Blueprint validation. A default-off worker deployment dep-dbgeu26i0phs73ekqj4g
was triggered from this tested head; no credentials or activation flag was set.
Render env-update response contains only deployment metadata, not existing URLs.
Small follow-up adds the nonsecret connection target to the activation receipt so
cutover uses the actual connected host without retrieving operator credentials.
Pending-password storage (each service's private PENDING_RUNTIME_PASSWORD) ensures
recoverability before activation; clear to empty with the final runtime URL merge.
No plaintext password, SCRAM verifier, private host or DSN belongs in this checkpoint.

## Staging database credential isolation verified (October 27, 2026)

Latest implementation ae1736663a8053f78726e50975f375d604210625 CI 40561689699
PASSED, job 122392096620: 212 API/research including all 67 actual PostgreSQL
cases, 7 policy, 19 gateway/client = 238 tests with no skips, plus Blueprint
schema/guard validation. Local: 145 API/research passed, 67 PG skipped without
local disposable DB; policy/gateway/compile/dependency/diff checks passed. The
follow-up tested receipt contains only host/port/database, never passwords/users.

Owner's explicit approval covered generating two independent high-entropy staging
DB passwords, private Render storage and limited-user cutover. Passwords were
generated in ephemeral process memory and sent privately through Render tools;
never printed, written to local files or committed. Each pending password was
saved on its own existing service before activation, ensuring recoverability.
libpq produced SCRAM-SHA-256 verifiers locally; only verifiers entered ALTER ROLE.
No Render/Cloudflare account credential or new OAuth client was created.

Activation deploy dep-dbgeve142hec738tdskg LIVE from ae17366. Receipt at
18:39:54.463190767 UTC: runtime-role-activation-v1, activated=true, roles=2,
passwords_returned=false, runtime_isolated=false (activation alone is NOT cutover).
The receipt's actual connected target was verified against the existing private
DB before building separate TLS-required runtime URLs. No operator URL/password
was retrieved. Do not rerun activation or regenerate these active credentials.

API cutover deploy dep-dbgf07gm7kps7388ooe0 LIVE at 18:41:57.017183 UTC from
ae17366. Replaced only DATABASE_URL with its independent pocket_api_runtime
connection, RUNTIME_DB_PROFILE=api, REQUIRE_API_RUNTIME_DB=true; cleared private
PENDING_RUNTIME_PASSWORD to empty. Existing preDeploy command remains named
manage migrate, but the explicit profile selects read-only verification only.
At 18:41:24.759938650 UTC, hosted staging-database-audit-v2 returned profile=api,
privilege_boundary_ready=true, direct_login/expected_role=true, migration_count=9,
migrations_match=true, history found=12. Every elevated/membership/schemaCREATE/
TEMP/DBownership/historyownership/historymutation flag was false. Strict startup
then passed before opening the API pool. Independent readiness returned 200/no-store;
direct auth/me without proxy remained 403/no-store. This is not a browser login test.

Worker cutover deploy dep-dbgf13avcj2c738hdkng from ae17366 replaces DATABASE_URL
with its independent pocket_research_runtime TLS connection and sets
RUNTIME_DB_PROFILE=research. Merged COLLECTION_ENABLED=false, STAGING_ACCEPTANCE=off,
STAGING_OPERATOR_ACTION=off, and cleared STAGING_RUNTIME_VERIFIERS and
PENDING_RUNTIME_PASSWORD to empty. At 18:42:59.765554048 UTC, hosted read-only
preDeploy audit returned profile=research, privilege_boundary_ready=true, matching
nine migrations/twelve history tables, direct expected-role login, and all unsafe
flags false. No owner alias was introduced; the known operator DATABASE_URL has
been replaced on both services. Actual final worker LIVE status is recorded below.

Both long-lived runtime connections now use separate limited users and do not
migrate. Future migration commands require a separate explicit operator context
using the managed DB's private operator credential, never an app env alias. Source
Blueprint has no fromDatabase operator references; sync:false runtime URLs and
explicit verify-runtime commands preserve this boundary on future reviewed sync.
Actual hosted legacy command names are safe because RUNTIME_DB_PROFILE is set.
Blueprint sync remains paused; never sync an older revision or roll back to an
operator-backed deployment. No automatic deployment, collection or paid upgrade.

Exact resume: inspect actual remote head/CI and service deploys, preserving dirty
saved worktrees. Do NOT recreate roles, repeat activation or rotate credentials.
Keep operator/acceptance flags off and collection false. Owner should recheck
Google login, refresh persistence and logout on the existing staging gateway after
this API cutover (prior acceptance was before cutover). Next independent build
work is representative synthetic full-cohort performance/memory acceptance for
the selected small stack, then the unfinished research/history UI. Real collection
needs separate authorization for a tiny bounded run; no market requests were made
here. Do not solve client-specific gateway smoke 403 by weakening access controls.
Existing loss-prevention table/full-sample metrics, main/live Worker and trading
remain untouched. Existing R2 immutable acceptance marker remains the only probe.

Final worker verification: dep-dbgf13avcj2c738hdkng LIVE at
18:43:20.889830 UTC. Logs show only normal research.runtime startup after the
successful read-only research-profile audit; no operator/diagnostic action or
collection startup. Post-cutover API readiness again returned 200/no-store.
Temporary secret values were cleared from ephemeral orchestration memory after
both Render runtime configurations were saved. All credentials remain private;
none were written to workspace files or public repo. No other writer/worker is
active in this session; local pocket-credentials remains dirty only because these
changes/checkpoints were saved through GitHub tools. Preserve it on continuation.

## Usable staging research dashboard (October 27, 2026)

Owner confirmed sign-in and sign-out still work AFTER runtime credential cutover,
then pointed out the staging page still exposes only authentication. Prioritize
connecting the visible app now. Resumed remote d6293ec, CI 40562842838 passed;
fresh pocket-dashboard worktree preserves previous saved dirty worktrees. No
other writer observed. This update targets existing staging only; no main/live
Worker changes, paid resource, credential rotation or enabled collection.

Root now redirects an authenticated owner to /collection.html. Replaced the old
unlinked controller with a responsive workspace: category/date requests, clear
collection-paused banner, hourly-refresh preferences, server-backed saved campaign
list with older-page navigation, section progress/pause/resume and immutable saved
reports. Dashboard has sign-out. Category/display/selected campaign persist across
reloads; no identity/session data in browser storage. Signed-out/expired sessions
show a sign-in link and hide private workspace. Request retry keys still prevent
duplicate ambiguous submissions. No live collection request was submitted here.

Added authenticated bounded GET /collection/campaigns?asset=...&before=UUID&limit=N.
Metadata keysets order by created_at/id, count only each chosen page's sections,
and survive new inserts without skipping older rows. Cross-category boundaries
return empty; strict query/session guards and closed gateway envelopes apply.
No archive/observation scan, new table, migration or new grant. Existing runtime
API SELECT permissions are exercised by actual-PG tests. For large campaign counts,
an (asset,created_at,id) index is a follow-up explicit operator migration; not
claimed benchmarked/index-backed ordering today.

Saved report client selects exact campaign stream and string bigint result ID.
Displays existing precomputed full-sample cells: average P/L/ROI/win rate, original
n/days, threshold-only loss labels and cell-detail exit coverage. Toggle selects
saved rows without recomputation, sampling or denominator shrink. Missing exits
keep hold outcomes; original losses >50% remain Trade not recommended (50% does
not reject). Existing production table/model/source files are untouched. Reports
combine only the selected campaign's sections; a deduplicated category-wide
cumulative report across campaigns is STILL pending and is not falsely labeled
as available. Empty history/reports are explicit; no fake sample data is shipped.

Tests add gateway bounds, listing auth/query pagination, actual-PG keyset insertion
and category isolation, actual limited-role listing, report identity/error safety,
full-cohort loss/minimum behavior, safe DOM rendering and signed-in/signed-out
workspace flows with preference restoration. Existing auth/gateway and Blueprint
guards remain enabled. Local: 214 API/research (146 pass, 68 actual-PG skip without
local disposable DB), 7 policy and 26 gateway/dashboard tests pass; compile,
dependency, Blueprint schema/guard and whitespace checks pass. CI must prove all
68 actual-PG cases before staging API/gateway publication.

Exact resume: inspect this implementation CI; after green, deploy only existing
staging API at tested branch head (same private runtime profile/gates, no secret
changes or migrations). Then manually dispatch existing deploy-pocket-app workflow
from build/google-auth-foundation; verify production job skipped and staging Worker
updated. GitHub connector lacks dispatch; authorized browser fallback uses existing
signed-in GitHub tab. Keep COLLECTION_ENABLED=false and all diagnostic/operator
flags off. Verify actual dashboard after login, empty/history/request states and
no console errors. Browser session/secret rules still apply. Record actual commit,
deploy/run receipts, any HTTP smoke 403 and remaining limits. Representative
performance and a separately authorized tiny collection remain before enabling
real worker; do not imply all app setup is finished merely because UI is deployed.

First dashboard implementation 434a06b CI 40564856050 PASSED: 214 API/research
including all 68 actual-PG cases, 7 policy, 26 gateway/dashboard = 247 tests with
no skips, plus Blueprint validation. Existing API manually deployed only after
CI green: dep-dbgf9bou01pc73cel2tg LIVE at 19:02:18.686543 UTC, strict API audit
again returned privilege_boundary_ready=true with unchanged nine migrations.
Independent readiness 200/no-store; direct no-proxy collection history 403/no-store.
No environment value, credential, worker deployment or collection flag changed.

Manually dispatched existing staging workflow via signed-in GitHub UI, run
40565477453 from 434a06b; production deploy job 122405474007 SKIPPED, staging
job 122405471724 published version 12e7904c-cf00-4f71-b32b-f0e08e18280d.
Workflow overall FAILED at known automated HTTP smoke 403; publication step passed.
A real signed-in browser refresh then caught a separate UI routing error:
Cloudflare Assets canonicalizes /collection.html to /collection, which the static
allowlist omitted. The browser reached JSON Not found at /collection. Do NOT
claim first publication usable. Added explicit canonical alias support, root
redirect/link to /collection, gateway regression coverage for both forms with CSP,
and CI path coverage for the new dashboard tests. Republish only staging after
this corrective commit's CI passes; API does not need redeploy for the alias fix.

## Dashboard published and browser-verified after canonical route fix

Corrective implementation 2c3047d7652e669ae290232d0638dd1bba2f43b8 CI
40565839212 PASSED, job 122406725622: 214 API/research including all 68
actual-PG cases, 7 policy, 27 gateway/dashboard = 248 tests without skips, plus
Blueprint validation. Only static alias/redirect and regression/path guards changed;
API remains on tested 434a06b deployment above; worker remains ae17366, disabled.

Automatic browser approval review initially rejected corrective publication because
it had not recognized connector evidence that corrective CI passed. No bypass was
used. Opened the exact CI run in browser, visibly verified Status Success for
2c3047d, rechecked the unchanged staging branch selection, then repeated the SAME
publish action successfully. No extra owner confirmation was needed once the
explicit prerequisite was visibly proved.

Corrective staging workflow run 40566210897 from 2c3047d, staging job
122408040068: tests/config/connection/deployment steps passed; published Cloudflare
version 15fe62d6-b113-42e4-b265-1e0270ac144a. Production job 122408042606 SKIPPED.
Overall workflow still FAILED only at labeled HTTP smoke: Staging sign-in assets
unexpected HTTP403, expected200. This client-specific limitation remains unresolved;
no retry loop, fingerprint/network evasion or access-control weakening was used.

Real existing signed-in browser now loaded the canonical /collection dashboard.
Verified category/date controls, Save collection request, server-backed empty
collection history, automatic-refresh preference OFF, collection-paused banner and
Sign out. Selected Daily weather, reloaded, and observed Daily weather remained
selected with the authenticated workspace. Restored original Bitcoin selection.
Opening original staging root also redirects into /collection successfully.
No new sign-in/consent flow or credential handling was necessary. No collection
request, pause/resume mutation or hourly preference change was submitted. History
is genuinely empty for the observed categories; no production history was imported,
no fabricated fixtures published, and populated hosted report acceptance is still
pending. Full table/coverage/toggle behavior has DOM/client and real-PG API tests,
not a claim of a real collected hosted report.

Resume from newest remote checkpoint/CI, preserving pocket-dashboard dirty worktree
whose contents are already saved remotely. Keep collection false, auto deploy off,
Blueprint paused and private DB boundaries. Next prepare representative synthetic
performance/memory acceptance and an explicit campaign-scoped, read-count/time-
bounded real-collection acceptance before asking to enable a tiny live read test.
The existing worker rate limit alone is NOT a total test-size cap; enabling the
whole worker could process other queued work, so inspect queues and bound it first.
Category-wide cumulative deduplication and large-history metadata index remain
independent follow-ups. Existing main/live UI/full-sample metrics remain untouched.

Final browser observation: root redirects to authenticated canonical dashboard;
BTC history empty; daily-weather selection survived reload, then BTC restored.
No application request/script error was observed in the current error log slice;
six browser-extension metadata transport errors were present and are not claimed
fixed by app changes. A private verification screenshot was captured outside git;
no owner email or credential appears in the dashboard screenshot. Owner-only
Google/setup action is no longer pending for this milestone. Approval for an
explicitly bounded real collection remains a separate future step after preparing
its caps; no such approval is requested by this checkpoint itself.

## Owner-authorized activation and continuing app implementation

Owner explicitly instructed: unpause collection, implement the other app parts,
save progress incrementally, skip steps needing assistance, and has granted blanket
permission to deploy. This supersedes the earlier collection-off/deploy approval
boundaries for this app. Keep existing paid sizes/private runtime roles, secrets
out of git, and no trading or contacting others. No main merge is needed for staged
implementation; work remains on draft PR9 branch with leased updates.

Resumed actual remote 7be2e6d; CI40566763839 passed; fresh pocket-active worktree
preserves earlier saved dirty worktrees. Merged only worker COLLECTION_ENABLED=true,
STAGING_ACCEPTANCE=off, STAGING_OPERATOR_ACTION=off into existing private Render
configuration. Worker deployment dep-dbgfjad9fdbs73c6qj1g LIVE at
19:22:24.630598 UTC from tested 7be2e6d. Research direct-login audit again passed
with 9 exact migrations/12 protected history tables, no unsafe privilege flags.
Existing shared budget remains 1 read token/second, capacity1, endpoint cost1.
No additional resource/paid upgrade, trading credential or live production UI edit.

Next code milestone adds a real owner-only GET collection/status and worker
heartbeat, rather than the stale hardcoded collection-paused banner. The marker
is one fixed terminal operational research_job record, updated only by ENABLED
workers; it cannot be claimed as campaign/provider work and contains no market
sample or credential. Existing worker/API queue grants suffice; no migration,
operator credential or privilege expansion. State expires after 90 seconds without
an idle/step heartbeat; waiting is not falsely called healthy. Collection progress
also returns committed-page totals from existing child progress (deduplicated job
membership), finished/total work items, retry time and safe child error codes.
UI shows those counts while section count remains unchanged; this prevents long
inventory work from looking frozen. Root/table/history/full-sample metrics unchanged.

Source Blueprint now records owner-authorized COLLECTION_ENABLED=true; its guard
checks this new intended state. Auto-deploy and Blueprint auto-sync remain off.
After actual-PG CI green, manually deploy existing API+worker and publish staging
gateway from the same tested head, verify online heartbeat in browser and a small
real one-day BTC collection. Do not leave blocked account/credential work pending
as a reason to stop independent app work. Save receipts before next milestone.
Then implement precomputed category-wide deduplicated history/this-load views,
coverage/source inspection and representative performance acceptance incrementally.

## Collection online; cumulative report engine prepared

92ec64d CI40568930140 PASSED: 217 API/research including 70 real-PG cases,
7 policy, 28 gateway/dashboard =252 tests without skips, plus Blueprint validation.
Worker deploy dep-dbgfm8mi0phs73c9ljh0 LIVE19:28:40.940628 UTC; API deploy
dep-dbgfm9nf3r2c73eg7600 LIVE19:28:46.646215 UTC. Both at92ec64d with existing
private profiles; worker COLLECTION_ENABLED=true. No new grants/migrations/secrets.
Staging gateway workflow40569704728 from92ec64d published version
16543600-bbdb-45dc-aa76-ac1d27502529; production skipped. Workflow overall still
fails only known automated assets HTTP403 smoke; browser works. No bypass/weakening.

Browser verified Worker online / collection enabled. Owner has already queued a
year-long BTC campaign (2025-10-27 through current2026-10-27 cutoff). Observed
12/366 sections collected,38 committed pages,14/14 current child tasks finished.
Do NOT create a duplicate acceptance campaign; use this real running work. No
pause/resume or automatic-refresh setting was changed by agent. Work continues
server-side while other app parts are built. These are observed progress counts,
not a claim of completed data/report or provider coverage for the whole year.

Fresh pocket-cumulative worktree starts from saved92ec64d; preserves prior dirty
saved pocket-active. Next independent engine adds CategoryReports using existing
queue/result/history tables. Each completed campaign atomically enqueues a local
category-report job with its result association. Worker builds category reports
between collection steps; no HTTP/archive calls or request-time recalculation.
Frozen job-progress snapshot survives crash/reclaim. Greatest immutable dataset
version ID wins overlapping half-open close-time coverage; partial rolling windows
overlay only their own interval, an explicitly complete empty newer interval removes
stale membership inside it, and outside history/gaps remain intact. Reused identical
windows deduplicate. Original raw datasets/fingerprints and previous reports never
change. A sweep-line selects disjoint intervals; only surviving source versions
are loaded one at a time, with explicit segment/input/output caps and no sampling.

Report builder accepts an internal candidate selector while verifying original raw
integrity; default hold/model path remains unchanged. Category policy/ROI is rebuilt
on the complete canonical selected cohort, never averages of earlier report cells.
Published selection includes frozen intervals/revision for audit; category latest
membership stays explicitly unknown because the selected campaign view is separate.
Stream lock rejects older frozen revisions finishing after newer category reports.
No schema/role changes or new resource. Large over-cap history fails visibly for
explicit future partitioning instead of silently dropping data.

Pure cases cover partial/empty replacements, close-time boundaries, disjoint gaps,
exact replay, missing inputs and intact full-cohort denominators. Real-PG tests add
recheck deduplication/retained old reports and stale frozen retry suppression. Local
224 API/research:152 pass,72PG skipped without local disposable DB. CI must prove
all actualPG cases before deploying this engine. Next connect dashboard This load /
All saved history choices, source membership/coverage and measured performance.
Keep current running collection online; deploys resume fenced saved pages.

## Cumulative engine verified; research views and source inspector prepared

03d752e CI40570248523 PASSED:224 API/research including72actualPG cases,
7policy+28gateway/dashboard=259 tests without skips, plus Blueprint validation.
Cumulative worker deploy dep-dbgfpve7bikc73bf8fi0 LIVE19:36:28.422541 UTC.
Existing active year collection remains running; no duplicate job, data reset,
operator credential, schema migration or role expansion was used.

Fresh pocket-research-views from03d752e adds This load / All saved history choice,
remembered on reload. Cumulative GET reads only published category reports; while
none is ready, it explicitly says completed collection required. Selected-load
progress remains visible separately. Views fetch saved cells, never rebuild model
or call provider. CSV exports ALL saved cells with hold/loss rows and original n,
regardless of UI minimum/display metric. Bigint result/source IDs remain strings.

Lazy Sources and collection coverage inspector pages exact immutable dataset
membership with existing raw coverage summaries and SHA fingerprints. Explicit
text says raw source totals can overlap and are not report sample totals. Category
selection revision/version is available in detail; owner-only /research/results/ID/
coverage returns signed, query/parent-bound pages of exact half-open close-time
windows. API validates closed aware-time intervals; no archives/raw observations
are fetched in requests. API uses only existing SELECT grants, including direct
limited-role tests. Source/member pagination works for reused cross-campaign data.
No new table, migration, grant, secret or paid resource. Root/live production UI
and pinned return/loss model remain unchanged.

Local tests add coverage-window auth/cursor isolation, actual limited-role source
reads, same-origin cumulative/client pagination, exact IDs and complete CSV output.
Run actual-PG CI before deploying API/worker and publishing updated gateway. Next
measure representative performance/memory, inspect running collection for explicit
provider/coverage issues, and continue independent improvements. Owner's blanket
deploy/collection authorization remains active; no repeated approval is required
for these existing app services. Skip account/credential blockers if encountered.

Research-view CI40571459104 exposed one existing real-PG test asserting the old
exact source-member shape without the newly added coverage summary. All other
API/PG/browser tests passed, including new limited-role coverage/window reads.
Updated that expected contract to include the fixture's exact summary, preserving
strict field checking rather than dropping the assertion. No failed build deployed.
The currently active worker/source report engine and year-long collection continue.


## Small-plan performance and collection retry milestone

1d58cfa CI40571997503 passed the corrected source-member integration contract.
Current local work continues from that exact remote head (no other writer observed).
Added synthetic benchmark CLI and infra/PERFORMANCE_ACCEPTANCE.md with measured
30/330/366-day receipts and explicit limits. 366 synthetic days retained35136
markets/175680 observations,19.272s,426880KiB peakRSS; not a hosted capacity claim.
Avoided duplicate canonical JSON hashing/parsing, removed unused diagnostic risk
snapshots while retaining all checkpoint coverage and EMPTY policy cells, released
paths sooner. Exact compact/full-report regression and existing goldenfingerprint
checks protect metric/denominator/loss-table behavior. Raised explicit output cap
64->96MiB and path cap500k->1M for measured year case; no sampling. Batched inserts
1000rows in SAME publication transaction; realPG tests cover all rows and rollback
across failed later batch. Worker idle wait follows durable ready times (0.1..5s)
without increasing conservative providerbudget. Browser errors sanitized; successful
collection polling clears stale timeout notice. No secrets/DDL/new resources.

Local verification:229 API/research (155pass,74PG skipped without disposable DB),
7policy,32JS allpass; Blueprint validation and diffcheck pass. Run real-PG CI next
before deploying. Current hosted API/gateway92ec64d,worker03d752e; existing user
BTC2025-10-27..2026-10-27 job last observed34/366sections,59pages35/36tasks.
It remains enabled; do NOT duplicate it or reset progress. No live report completion
or dense hosted memory acceptance claimed. Current views not yet published.

Exact resume: inspect actual remote head/CI; deploy green head to existing manual
Render API+worker (auto-deployoff), publish dev-branch deploy-pocket-app workflow
(production mustskip), inspect signed-in UI/progress/views/sources/CSV; record exact
receipts. Known automated staging assetsmoke HTTP403 remains unresolved; browser
works; do not weaken access. Keep source/main production unchanged and PRdraft.
Owner authorized collection+existing service deploys; no repeatapproval needed.
Owner-only: any future Google/credential/account issue, larger paid capacity or
operator migration remains pending only if actually needed; skip blocked work.
Next independent need: partitioned cumulative reports beyond explicitcaps; actual
hosted large-report memory and populated source/export acceptance afterloadfinishes.


## VERIFIED deployed milestone:7235d31 (2026-10-27 19:56 UTC)

Exact head7235d318ff084c4d3e7a339aa263b88eb2a33d15 passed CI40572924816,
job122431630696:229 API/research with74actualPG,7policy,32JS=268tests,
no skips/failures, plus Blueprint checks. Corrected prior1d58cfa runreceipt above:
actual API run40571997503;40572387629 was not a valid receipt on reinspection.

API dep-dbgg26nf3r2c73eh7740 LIVE19:54:22.056174UTC from7235d31.
Worker dep-dbgg27ks728c739mn5ug LIVE19:53:53.618299UTC from7235d31;
startup says Collection enabled; worker ready. Both runtime privilege audits again
passed9exactmigrations/12historytables with no elevated/historymutation privileges.
Predeploy remains read-only verification through runtimeprofile; no DDL/credential
changes. Existing plans/cost and auto-deployoff/pausedBlueprint remain unchanged.

Gateway workflow40573204003 stagingjob122432612936 publish stepSUCCEEDED;
Cloudflare version5aff0179-df3f-465a-a470-d0b2eb0a7c26 at19:54:15UTC.
Productionjob122432615376 SKIPPED. OverallrunFAILED known assets HTTP403 smoke
only. Signed-in actualbrowser loaded new reportselector and collection controls;
no access-control weakening or alternate-client workaround. API/worker arelive.

Browser verified originalyear BTCload kept44/366sections and86savedpages,
62/78tasks afterworker restart; sectioncount currentlyunchanged whilepagesadvance.
No duplicate historicalrequest. Owner's requested BTC hourly24h refresh nowENABLED
through signed-in UI; persistedstatuschecked, automaticrollingwindow26Oct19:54:51
through27Oct19:54:51UTC createdby scheduler,0/2sections and8pageslastobserved.
Othercategories' automaticpreferences unchanged. Explicit userauthorization is
latestblanketdeploy/unpauseinstruction; earlierOFF restrictions are superseded.

Browser All saved history selector returned correct explicit no-completed-report
message (no fabricatedresults). Returned toThisload and originalyearprogress.
Progressnotice clears stale abort diagnostics aftersuccess. Occasional10sclient
requesttimeouts stillobserved and automaticallyretry; savedworkerpagescontinued.
Do not claimnetworklatencyresolved. Report/source/CSV codepassesCI, but populated
hostedreport/export notyetverified because no observedcampaignfinished.
PR9descriptionupdated tocurrentcapabilities,enabledstate,tests andlimitations.

Resume fromremoteactualhead; doNOTreplayactivation, provisionresources, duplicate
runningyearload, resetDB, or merge main. Inspect runningcampaign+hourlywindow,
workerheartbeat andnewlogs. Whenreportcomplete, verifyfulln/pinnedlosstable,
source/coveragepagination, CSV andcategorydedup inactualUI. MeasureliveworkerRSS
andDBgrowth beforebroadeningcategories. Next independentengineering milestone:
explicit partitionedprecomputedreports beyond250kentries/1Mbars/96MiB, preserving
full-samplepolicytraining and immutablehistory. Do notsilentlysampleorraisecaps
withoutmeasurement. Investigate boundedAPIlatency iftimeoutscontinue; documented
HTTP403smoke remainsunresolved. Owner-only blockers: anynewGoogleconsent/credentials,
paidcapacityexpansion oroperatorDDL; noneisrequiredforcurrentenabledstack.


## Collection speed milestone prepared (2026-10-27)

User explicitly requested removing the app's one-read/sec bottleneck and larger
requests. Continued from actual remote 938f8ed in isolated pocket-speed worktree;
pocket-resume has an unrelated untracked data temporary file, left untouched.
No other branch writer/deploy was observed. Existing worker is still7235d31.

Added recent-candle batches: up to100 market tickers, with a conservative9000
worst-case inclusive minute-bar bound below Kalshi's10000 response limit. Reads
only documented public GET /markets/candlesticks. Original batch request/response
is archived immutably with verified receipt; each market retains its own fenced
checkpoint and linked batch receipt. Omitted/truncated members retry individually,
never become invented empty candles. Foreign/duplicate/malformed batches fail;
429/backoff remains shared. Cached batch members do not charge another HTTP read;
acknowledged members leave the cache. Lost process caches only cause re-fetches,
never lost checkpoints or duplicate raw/report publication. Archived candle API
remains per market; no undocumented historical batch request is invented.

Added up to4 concurrent non-batch evidence reads (archived candles/trades) within
one leased parent step, same shared cross-process read budget, bounded futures,
per-child leases and immutable receipts. Inventory remains serial. Existing small
pool and plans unchanged. Cached verified candidate manifests (8MiB serialized
budget) avoid repeated R2 downloads per evidence page. No observations are removed;
both requested source routes and all candle/trade pagination remain intact.

Application public-HTTP pacing target is now5reads/sec,capacity5 in source. This
is NOT a verified authenticated Kalshi account allowance (no new credentials).
Runtime budget reconfiguration explicitly updates only rate/capacity, clamps old
tokens and preserves cooldown/clock; default callers still reject conflicts.
Need patch ONLY KALSHI_READ_RATE=5 and KALSHI_READ_CAPACITY=5 on existing worker,
replace=false AFTER actual-PG CI passes, then inspect triggereddeploy (avoid extra
trigger). Blueprint sync remains paused; source mirrors intended hosted pacing.

Local238API/research:162pass,76PG skipped without disposableDB;32JS+7policy pass,
Blueprint validation/compile/pipcheck/diffcheck pass. Added100markets/oneHTTPtest,
missing/truncation/foreign/duplicate/bounds/429/cache tests; realPG cases cover
runtime cooldown preservation and full15-observation publication after losing
batch cache, with barrier proving4 simultaneous I/O operations. Await CI before
deploy; do not claim measured hosted speedup from stub tests. Live year+hourly
campaigns must resume in place, no new duplicate collection or reset. No schema,
credentials, paid resources, trading, API/UI deployment or main merge needed.

Resume: inspect actual remote head+CI, fix any realPG regression, then patch the
two public pacing keys and observe worker live/readiness/logs/continued pages.
Measure before/after page/task throughput on the same job and record limitations;
section counter advances only after a full day. Actual upstream batch acceptance,
provider429 frequency and small-plan memory are still to verify. Larger history
partitioning, collection latency/progress UI and populated reports remain pending.


b368f32 CI40587065371/job122481251777 passed277tests including76actualPG.
Patched ONLY the two public pacing keys to5 via replace=false on existingworker;
this triggered dep-dbghfhuk1f9s738q026g fromb368f32 (no duplicate trigger). Runtime
privilege audit passed again. Follow-up hardening: batchHTTP400/404/422 must fall
back to existing single-market requests (older/archived tickers may be rejected
by the recent batch route); 429/5xx still use sharedbackoff. Added directtests
for each rejection; await follow-upCI before final workerrevisiondeployment.


2a1269a CI40587608924/job122483131112 passed278tests (239API/research,
76actualPG,32JS,7policy). Triggered follow-upworker dep-dbghhaec6qcc73bvahmg.
Browser afterfirstupgrade:486pages/462tasks,still46/366sections; originalrun
continues. Found expected batch-to-single fallback was labeled provider_unavailable
and consumed one retry; changed it to a healthy deferred step (no false error,
no cooldown or consumed attempt). Genuine429/5xx behavior unchanged. AddedactualPG
case verifying no checkpoint/failure and a refunded healthy lease; CI pending.
Do not claim fixed end-to-end ETA or upstreambatchacceptance from UI counts alone.


## VERIFIED collection speed deployment — October 27, 2026, 2:37 p.m. PDT

Final worker code: 11dfd442011cd15ca4509961b744cce0ceb45b28.
CI 40588014557, job 122484549308, PASSED: 240 API/research tests,
including 77 actual PostgreSQL cases, plus 32 JavaScript and 7 policy tests:
279 total, no skips/failures. Blueprint validation also passed. Earlier speed
commits b368f32 and 2a1269a passed their respective CI before deployment.

Final Render worker deploy dep-dbghiigu01pc73ea9qvg became LIVE at
2026-10-27T21:37:00.905585Z (2:37 p.m. PDT). Runtime logs explicitly confirm:
"Collection pacing: 5 public reads/sec, burst 5; recent candle batching enabled;
evidence concurrency 4". Runtime privilege verification again passed nine exact
migrations and twelve history tables without owner/elevated/history-mutation
privileges. No DDL, secret, role, Google setup, or paid-plan change was required.

Hosted configuration changed ONLY KALSHI_READ_RATE and KALSHI_READ_CAPACITY to5,
with replace=false. Existing worker service is srv-dbgcsb6c6qcc73f1j6lg, workspace
tea-dbfv1fl9el5s73bcuefg, plan0.5c-512mb. Source Blueprint reflects5; auto-deploy
remains off and Blueprint sync paused. No API/gateway deployment or main merge.
API and gateway keep their previously verified revisions. No trading/contacting.

Actual signed-in browser observations on the SAME historical collection:
- Before upgrade, about21:29UTC: 46/366 sections,429 pages,405/560 tasks.
- During/after speed deployments:460,486,519 and finally545 saved pages;
  final observation521/560 tasks, still46/366 whole daily sections.
- Worker remained online, hourly refresh enabled, original collection queued/
  running rather than replaced. No duplicate request, data reset or pause.
- UI still displays a last provider_unavailable issue from a saved child attempt;
  progress continues. Do not claim every upstream/network issue is resolved.

These observations prove resumed work, not a controlled sustained-speed benchmark
or completion ETA. Day counts move only when all requested daily evidence finishes.
Recent batch acceptance against the real upstream is not independently exposed by
these UI counters;100 markets/one request is verified with stub HTTP and full
pipeline/restart tests. Listings and trade pages already request1000 records.
Archived candle endpoint remains per market; its speedup uses concurrent I/O.
Expected unsupported/missing/truncated batch fallback now yields healthy work
without an error, shared cooldown, or consuming an attempt. Real429/5xx continue
shared cooldown/backoff. All requested trades, candidates and metrics remain.

Exact resume: inspect actual remote head and this final code CI/deploy receipt.
Keep original year/hourly jobs running in place. Compare page/task throughput
across comparable evidence phases after deploy overlap settles; inspect any new
provider failures and worker memory. Verify a completed daily source and then the
full saved report/source coverage/CSV with the owner when available. No new
credentials are needed. Do not reset read budgets/cooldowns to force speed, infer
an authenticated Kalshi allowance, or increase paid resources without a concrete
need. Further candidates: reduce per-page database overhead, add explicit worker
throughput telemetry and better partial-day/ETA UI, then partition oversized
precomputed histories without changing full-sample policy training. Existing
HTTP403 automated gateway smoke and large-report live RSS acceptance remain open.
Owner-only future blockers (new credentials/Google consent/paid capacity/operator
DDL) should be skipped until needed; the user authorized current collection and
existing-service deployments. Code/checkpoint progress is committed incrementally.


## Progressive research milestone prepared

User expects seven days near the old five-minute run and usable data during a
long collection. Comparison found the old collector bounded execution diagnostics
to60markets/day and2tradepages; new immutable collector fetches ALL requested trade
pages from both routes and gated reports on the whole campaign. Return/loss tables
use candles, not those trade diagnostics. No claim that the current exhaustive
workload matches the old five-minute timing; no observations/tradepages dropped.

Isolated pocket-progressive from actual remote1153ed6. Prioritize candles, produce
verified candle-only immutable daily raw versions, and move to next day's candles
before returning to unfinished trade enrichment. Operational parent progress maps
candle-ready day/source IDs, preserving existing full-section dataset associations
and eventual full enrichment. At section boundaries enqueue a durable progressive
report snapshot with frozen source IDs/revision. Bootstrap existing active jobs so
the current year load's already collected sections become visible without restart
or duplicate collection. Source hash/membership/coverage verification remains.

Save report cells and exact source membership as immutable versions; skip repeated
observation-row copies ONLY in explicitly marked progressive reports (all raw
inputs and full-sample metric computation retained). Final complete report still
stores every observation. This avoids quadratic DB growth while reports update.
Stream lock prevents stale partial snapshots replacing newer/final reports.
Cumulative snapshots now use latest published campaign source membership, including
candle-ready progress, with monotonic result-ID revisions and existing overlap rules.

API returns publication completeness/section coverage and selected preview ID;
UI automatically reloads report when ID changes and marks In progress / XofY
sections available. Full-sample refers to available source sections, explicitly
not the still-uncollected date range. CSV includes completeness/section fields.
No schema, role, secret or paid resource change; backend query reads saved data.

Local242API/research (163pass,79actualPG skipped),32JS,7policy; compile/Blueprint/
diff checks pass after fixture correction. Added realPG tests for reports before
trade completion, multi-day expansion, crash/restart/final identical full-sample
cells, no quadratic preview observation copies and stale/final publication guards.
Run actualPG CI, resolve regressions, deploy tested API+worker then gateway on dev
branch only. Verify actual existing year/hourly job tables/sources while running;
no need for owner action or new credentials. Record exact receipts and limitations.

1408cf5 CI40590164616 passed241/242 API/research plus32JS+7policy; new
realPG progressive test showed a final enrichment transition problem after an
artificial continuing empty trade-page fixture. No failed revision deployed.
Added fixture-only diagnostics to identify the exact integrity check; preserve
strict final-completion assertion and all source/denominator checks.

6b2ba52 CI40590529719 isolated transition to a succeeded parent whose selected
report still carried partial publication metadata. No enrichment integrity error.
Strengthened final-publication precedence so partial revision ordering can never
block a verified completed report; kept version diagnostics in the fixture.
Failed revisions remain undeployed; current worker continues11dfd44.

Root cause verified by b0e5357 CI40590834188: final immutable report14 was
correct/complete, but new CampaignStore.get selected preview8 because ORDER BY
id resolved the id::text output alias (lexicographic). Qualified rr.id fixes numeric
ordering without changing exact string IDs returned to the browser. Removed
temporary fixture wrapper; preserved final/full-sample/version assertions.
The final-precedence guard remains valid defense against stale preview revisions.
