# Money Tree worker resource audit — November 8, 2026

## A. Measured resource usage and architecture

This audit changes no service tier, instance count, trading settings, risk limits, retention policy or historical data. The existing paper worker was already upgraded separately to **1 CPU / 2 GiB** at 06:21 Pacific. Measurements from its previous 0.5-CPU / 512-MiB tier are not used to claim optimization savings.

The deployed processing service is `pocket-processing-staging`, running `python -m services.research.runtime` with the Demo role. That dispatches one fenced paper executor. The separate research collector and API have their own processes. Installed shadow mode returns directly into the shadow engine; the old Low Buy / High Sell execution loop does not also run. Its records are retained.

One process-lifetime PostgreSQL advisory lock prevents overlapping trading execution during deploys. The pool has at most three connections, including the lock connection. Wallet mutation, audit/checkpoint preparation and commit are serialized under one state mutex; cancellation waits for the outstanding database operation. Failures leave queue items unacknowledged and do not write a subsequent unaudited checkpoint.

### Baseline: 06:30–06:40 Pacific / 14:30–14:40 UTC

Render one-minute samples: mean worker CPU **0.644 cores**, peak **0.872 cores**, mean memory **391.0 MiB**, peak **439.3 MiB**; allocation **1 CPU / 2 GiB**. Twenty approximately 30-second pipeline windows processed **634,714 inputs**, averaging **31,736 inputs/window**.

| Pipeline measurement | Baseline |
|---|---:|
| Simulation wall time per 1,000 inputs | 231.7 ms |
| Preparation + commit wall time per 1,000 inputs | 418.9 ms |
| Preparation + commit wall time per 30-second window | 13.30 s |
| Mean last checkpoint preparation sample | 107.2 ms |
| Mean last database-write sample | 140.5 ms |
| Mean maximum queue delay per window | 3.16 s |
| Worst queue delay | 6.80 s |
| Worst measured event-loop lag | 385 ms |

These are wall-time pipeline measurements; database waiting is not CPU usage. The strongest measured bottleneck is repeated full-state preparation and commit, not a demonstrated Kalshi rate-limit problem. Admission logs explicitly paused discovery for processing lag while REST cooldown was zero. Other healthy intervals admitted new markets without configuration changes.

Before the already completed tier change, one older instance averaged 0.447 of its 0.5 available CPU cores and reached approximately 501 MiB of 512 MiB. That explains very limited headroom, but does not establish an OOM crash. Recent instance transitions correspond to deployments; an unplanned-crash count is unavailable.

Database Render samples at 06:00–06:30 Pacific averaged **7.43 active connections**, maximum **8**, and **0.373 CPU cores**. Memory ranged up to **879.5 MiB**. Existing storage telemetry reported **6,712,284,851 bytes** at 06:32 Pacific, **62.51%** of configured 10-GiB capacity. The latest five-minute growth sample was **3,579,904 bytes**; an earlier restart-period sample grew 71.7 MB. These short intervals are not a defensible daily growth forecast.

The API is a separate Render process. Between 06:00 and 06:35 Pacific it averaged **0.0076 CPU cores** and roughly **156 MiB RAM**. The metric series contained 34 successful responses, 33 HTTP 503 responses and one 499. Route-specific latency and the causes of those historical 503s were unavailable; previously database errors returned a generic 503 without structured diagnostics. They must not all be attributed to dashboard size or worker CPU.

Recent successful dashboard transport logs showed **6,675,615–6,677,872 decoded bytes** and roughly **1.16 MB on the wire**. The previous dashboard fix removes duplicated research evidence in metrics; it does not delete evidence. Native authenticated dashboard latency was not available before this audit.

## B. Confirmed waste and existing efficiencies

| Finding | Evidence and cost | Treatment |
|---|---|---|
| Recursive copying of scalar execution records | `dataclasses.asdict` recursively traversed every field, Decimal and target list at each checkpoint | Replaced with shallow copies of flat records, copying mutable targets separately; restore-equivalence tests |
| Repeated shared halt lists | Every bot serialized the same fleet halt set; restore already unions those lists | Serialize the shared set once, retaining the old schema and old-reader restore behavior |
| Checkpoint preparation on the event loop | Baseline preparation samples averaged 107 ms; compression ran before entering the thread executor | Prepare and commit on the existing executor, retaining the state mutex and cancellation fence |
| Concurrent cold-series fee requests | Four fee verifiers could independently miss the same series cache | Per-series single-flight lock; existing 30-second series TTL, event overrides and 60-second schedule expiry unchanged |
| Repeated admission-flag assignments | Every delta assigned the same flag across all Scalper/Maker profiles | Preserved the transition-only implementation merged separately in PR #100 |
| Repeated full checkpoints during bursts | Baseline preparation + commit consumed 13.30 s/window | Preserved separately merged bounded 512-input / 80-ms burst batches; low-load bounds unchanged |
| Missing causal diagnostics | REST request totals, per-strategy CPU, and database failures were not fully attributed | Added bounded operational telemetry; unmeasured costs are identified below |

Existing efficiencies retained: one shared Kalshi subscription set; no independent stream per bot; read-only production adapters; one shared in-process 3-requests/second REST budget and shared 429 cooldown; cached verified fee schedules; unrelated lifecycle filtering; inactive portfolio feed suspension; incremental ordered book levels; unchanged-quote filtering; bounded shared causal tape; flat Momentum/Dislocation book reuse; bounded pending-order queues; terminal order pruning; batched opportunity records; gzip checkpoints; keyset event archival with verification before restoration/archival operations.

Independent wallets need independent simulated liquidity-consumption overlays and queue state. Removing these copies indiscriminately would let one experiment consume another experiment's hypothetical depth. This audit does not do that.

The separate research collector averaged **0.00326 CPU cores** over 06:00–07:00 Pacific, with mean memory **421.2 MiB**, peak **467.3 MiB**, against its existing 0.5-CPU / 512-MiB allocation. It is not a source of substantial measured CPU load in this interval, but its retained RAM leaves limited headroom. Source inspection found byte-bounded archive/evidence caches and a saved-data analysis thread; changing collection caching without measuring retained object growth would risk re-downloading useful evidence. No collector configuration changed. Its provider budget is separate from the paper process's budget; aggregate account headroom across services is not established by the paper-only request counters.

## C. Implemented changes and observability

1. Faster schema-compatible checkpoint encoding, shared halt-list deduplication, and off-loop preparation under the existing financial fence.
2. Concurrent fee-series request deduplication. Four same-series market refreshes use **6 requests instead of 12** in the controlled test: one series read, one series-change read and four separate event-change reads. Different series remain concurrent, and a failed refresh cannot publish a new cache entry.
3. Every approximately 30 seconds, the existing pipeline log now includes process CPU seconds/cores, current RSS and peak RSS, exact instrumented REST attempts by normalized endpoint/task/status, queue/loop delays, per-portfolio engine-and-fee-preparation CPU time, engine calls, monitored books, active orders, position lots, cumulative order generation, opportunities and round trips, plus committed audit row/transaction counts.
4. Request counters have bounded cardinality and retain no query parameters, response bodies, tokens, headers or raw market IDs. Task scopes distinguish discovery, fees, weather, sports, hourly, baskets and Maker; common feed requests cannot honestly be attributed to an individual beneficiary bot. Their cost remains shared.
5. Database catalog sampling runs on the existing maintenance cadence: largest ten relations, estimated live/dead tuples, sequential/index scan counters, commits/rollbacks, cache reads/hits, temporary bytes and deadlocks. These are cumulative/estimated PostgreSQL statistics, not per-request query plans.
6. Dashboard logs now distinguish request time from serialization/compression time and include decoded/wire sizes. Database exception logs report rate-limited error types, SQLSTATE and route templates, without error messages or SQL text.
7. The research-heavy codec now uses the already-installed MessagePack dependency before gzip. Binary floats avoid repeated float-to-decimal formatting, while Decimal money is stored as exact strings. Readers support legacy plain JSON, gzip JSON and the new versioned envelope. Checksums, bounded decompression, strict map keys and explicit container/binary/extension limits remain enforced. API readers deploy before the worker writer. **Rollback must retain the new decoder**; do not deploy a decoder that only understands the older gzip tag after binary checkpoints have been written.
8. The recurring dashboard response now sends the ten research-cell fields actually consumed by its cards and category summaries. Full totals, period statistics, group counts, dimensions, financial values and displayed trade details remain intact. Complete per-bot research remains available through a new owner-authenticated, GET-only endpoint and **Download full research** button. Neither worker state nor persisted evidence is projected or deleted. A synthetic 1,000-cell dashboard fixture shrank from **924,017 to 293,017 bytes**, a **68.3%** reduction; a live post-change response size is unavailable because this browser is not signed in.

No raw data, observations, orders, fills, account records or completed-market history were deleted. No archival or retention settings changed. No migrations, service upgrades or new paid components were introduced.

## D. Benchmarks

Local reproducible benchmark: `PYTHONPATH=. python tools/benchmark_worker_resources.py --baseline-ref 71eb09c`. Same generated state: 53 profiles, 28 markets, 280 orders, 21 iterations, median process CPU time.

| Synthetic measurement | Before | After |
|---|---:|---:|
| State encoding CPU | 2.223 ms | 0.118 ms |
| Complete encode + gzip checkpoint CPU | 3.638 ms | 1.086 ms |
| Decoded checkpoint bytes | 169,001 | 122,782 |
| Stored JSON envelope bytes | 11,695 | 10,447 |
| Concurrent four-market cold-series fee reads | 12 without single flight | 6 with single flight |

The checkpoint benchmark shows **70.1% lower CPU time for this fixture**, not a prediction of production CPU savings. A second fixture uses 5,000 seeded research buckets shaped like the production research counters:

| Research-heavy synthetic codec | Gzip JSON | Gzip MessagePack |
|---|---:|---:|
| Median codec CPU, 11 iterations | 81.909 ms | 30.142 ms |
| Raw encoded bytes | 5,013,791 | 3,690,013 |
| Stored base64 bytes | 1,501,868 | 1,069,244 |

That is **63.2% lower codec CPU** and **28.8% fewer stored bytes** for the generated research fixture. Both decode to the same values; no financial precision is discarded. These fixtures contain no user trading data. Database wait time, market message rates and trade frequency are workload-dependent.

Production follow-up measurements and final verification are recorded after deployment below.

### Production comparison

Baseline is 06:30–06:40 Pacific, one 1-CPU / 2-GiB worker. Follow-up is nine approximately 30-second windows from **07:12:15–07:16:17 Pacific**, one worker instance running the binary codec. This is a short observational comparison, not a controlled replay: incoming traffic, positions, market phase and monitored categories changed. The final release also preserves independently merged burst-budget and current-wall-time admission fixes. Do not attribute the whole difference to one function.

| Metric | Baseline | Follow-up |
|---|---:|---:|
| Inputs processed / approximately 30 s | 31,736 | 42,741 |
| Simulation wall ms / 1,000 inputs | 231.7 | 210.5 |
| Preparation + commit wall ms / 1,000 inputs | 418.9 | 243.2 |
| Preparation + commit wall s / window | 13.30 | 10.39 |
| Mean sampled checkpoint preparation | 107.2 ms | 61.8 ms |
| Mean sampled database-write duration | 140.5 ms | 127.2 ms |
| Mean window maximum queue delay | 3.16 s | 4.22 s |
| Worst observed queue delay | 6.80 s | 8.21 s |
| Worst observed loop lag | 385 ms | 328 ms |
| Render sampled CPU cores | 0.644 mean / 0.872 peak | 0.615 mean / 0.801 peak |
| Render sampled peak RAM | 439.3 MiB | 404.2 MiB |
| Completed instrumented paper REST reads | Not recorded | 705 in 271.3 s, about 155.9/min |
| REST 429s in instrumented follow-up | Not recorded | 0 |
| Total database queries/min | Unavailable | Unavailable; commit/row counters are separate |
| Five-minute database growth sample | 3,579,904 bytes | 3,735,552 bytes |
| Live dashboard decoded / wire bytes | About 6.68 MB / 1.16 MB | No signed-in request observed after final deployment |
| Route-specific dashboard response time | Unavailable | Instrumented, but no signed-in sample observed |
| Unplanned crash / timeout rate | Unavailable | Not established by this short sample |

The follow-up Render CPU average excludes its startup-skewed 07:12 sample and uses four mature one-minute points. The process was younger, so lower RAM cannot establish a leak fix or steady-state reduction. Process-local CPU counters use different aggregation boundaries from Render. The first non-binary rollout also encountered 12.5-second queue delay before the final codec; the 8.21-second figure is restricted to the stated final sample.

The measured improvements are **42.3% lower sampled preparation time** and **42.0% lower preparation/commit wall time per 1,000 inputs**. More messages were processed, but this does not prove a 34.7% increase in sustainable market capacity because incoming load was not controlled. **Burst latency is not resolved.** Discovery admission and existing freshness protections still pause when overloaded. No thresholds were loosened to hide that fact.

Adjacent live checkpoint observations were 1,270,924 stored base64 bytes with the old gzip-JSON codec at 07:11:11 and 1,083,228 with the binary codec at 07:11:26. The states are close in time but not identical; use the synthetic identical-input benchmark for a causal byte comparison. Logical database growth did not demonstrably fall during this short audit; a smaller hot checkpoint does not remove old database pages or erase ongoing research growth.

### API and strategy attribution

All 705 measured completed requests in the follow-up returned HTTP 200. Request latency includes application pacing/queue wait plus network/response time; it is not isolated provider latency.

| Normalized endpoint | Completed requests | Requests/min |
|---|---:|---:|
| `/events/fee_changes` | 210 | 46.4 |
| `/series/:series` | 125 | 27.6 |
| `/markets` | 106 | 23.4 |
| `/series/fee_changes` | 102 | 22.6 |
| `/markets/:ticker` | 88 | 19.5 |
| `/milestones` | 38 | 8.4 |
| `/live_data/milestone/:id` | 27 | 6.0 |
| Other allowed metadata/trade routes | 9 | 2.0 |

By task: fee maintenance 357 requests, hourly discovery 160, sports 75, weather 57, rolling discovery 47, Maker 9. The common data and fee costs are shared by beneficiary strategies; they are not duplicated as a separate request for each bot. No artificial per-bot API allocation is reported.

| Strategy / portfolio | Mean measured engine + fee preparation CPU / window | Loaded markets at sample end | Fresh books | Activity status |
|---|---:|---:|---:|---|
| High Probability / Favorites | 1,649 ms | 27 | 23 | Running; new orders and holdings observed |
| Volatility Scalper | 1,237 ms | 18 | 15 | Running; cumulative 1,125 round trips |
| Fixed Scalper | 1,004 ms | 18 | 15 | Running; cumulative 767 round trips |
| Grid Scalper | 1,036 ms | 18 | 15 | Running; cumulative 1,203 round trips |
| Momentum Scalper | 527 ms | 18 | 15 | Running; cumulative 329 round trips |
| Dislocation Scalper | 461 ms | 18 | 15 | Running; cumulative 223 round trips |
| Sequential baseline | 50 ms | 19 | 0 | User configuration paused; no new entry activity expected |
| Sequential flexible | 45 ms | 19 | 0 | User configuration paused |
| Sequential adaptive | 45 ms | 19 | 0 | User configuration paused |
| Complete Set | 1.7 ms | 0 | 0 | User configuration paused |
| Market Maker | 241 ms | 0 | 0 | Enabled; two submitted entries historically, no fills confirmed |
| Competitive Maker | 190 ms | 0 | 0 | Enabled; two submitted entries historically, no fills confirmed |
| Convexity | Not separately instrumented | 9 selected | 0 | Paused, zero open exposure; idle depth processing suspended |
| Low Buy / High Sell | Not in active shadow execution path | N/A | N/A | Legacy execution state/history retained |

Loaded market counts include retained unsettled/closed execution state and are not subscription counts. Round trips are cumulative retained evidence, not trades all completed during this sample. These CPU figures exclude shared checkpointing, reporting, outer dispatch and operational maintenance. Retained per-strategy RAM and exact per-strategy SQL cost are unavailable because shared state and atomic transactions cannot be accurately assigned by these counters.

## E. Remaining bottlenecks and unavailable measurements

Full financial/research checkpoints remain expensive and atomically rewritten on dirty batches. This audit preserves durability rather than dropping observations or loosening commit guarantees. If these writes remain dominant, the next design should separate unchanged research/discovery segments from hot financial state using versioned, atomic references and tested recovery.

Before the final projection, the authenticated dashboard returned several megabytes of evidence every refresh and repeatedly queried performance history. Collapsing a card does not suppress its backend computation. Lazy research-detail loading, with complete exports and reconciled summaries, is a justified next improvement; arbitrarily truncating evidence is not.

The final dashboard projection reduces recurring cell payloads and adds complete per-bot downloads, but repeated history aggregation and rendering every group remain. Lazy folder rendering and incremental financial aggregation remain useful future work. The actual final owner-session payload/latency must be measured on the next authenticated dashboard load.

The hosted PostgreSQL query connector is blocked by the database's empty external IP allowlist. No allowlist or privilege was weakened. Live `EXPLAIN`, exact per-query frequency/latency, table-level historical storage attribution and lock inspection were unavailable before the internal sampler deployed. Existing unique idempotency-key, queue and history indexes were inspected in source; no speculative indexes were added.

The internal sampler subsequently measured **3,829,022,720 bytes** for `research_job`, estimated **2,244,028 live tuples** and **15,067 dead tuples** at 07:00 Pacific. Other large relations: `research_dataset` 1,344,348,160 bytes, `collection_page` 440,188,928 bytes, `raw_archive` 284,426,240 bytes and `research_campaign_work` 274,685,952 bytes. These are relation totals, not disposable-record classifications. PostgreSQL reported zero cumulative deadlocks in both samples. Across 529 seconds, total database commits increased by 3,583, about 406/minute across all services; that is not a query count or paper-worker-only rate.

Total database queries/minute are unavailable: new commit/row counters cover the audit persistence path, while catalog transaction counters cover all clients and cannot be labeled as query counts. Per-strategy retained RAM cannot be separated accurately from shared books, caches and Python allocator overhead without intrusive profiling. New process RSS and object counts must be used before claiming a memory leak. Render HTTP latency was empty; bandwidth data was too coarse to derive Kalshi request volume. Before-rollout endpoint request rates were not recorded and cannot be reconstructed exactly.

The 3-reads/second application budget is distinct from Render CPU/memory and from provider account limits. No provider-limit increase or more aggressive retry policy was applied. Do not infer an API bottleneck from processing lag with zero cooldown.

## F. Ranked next optimizations

| Priority | Opportunity | Benefit | Complexity / risk |
|---|---|---|---|
| 1 | Resolve intermittent sports metadata `KeyError` with sanitized frame/field diagnostics | Restores reliable sports discovery and avoids repeated failed work | Low–medium / low if unknown metadata remains blocked |
| 2 | Use new checkpoint/strategy/request counters to target the dominant measured path | High; avoids optimizing an inactive code path | Low / low |
| 3 | Lazy dashboard research details with pagination and full exports | Lower API serialization, response size and repeated history work | Medium / medium; preserve exact summaries and mobile layout |
| 4 | Atomically persist only changed checkpoint segments | Potentially large CPU, network, WAL and database savings | High / medium-high; replay/recovery and audit atomicity require careful tests |
| 5 | Query-plan-guided indexes or incremental historical P/L materialization | Potentially lower dashboard database latency | Medium / medium; requires measured plans and accounting equivalence |
| 6 | Prune only expired, unreferenced operational caches after object-growth measurement | Lower retained RAM | Medium / medium; raw research stays persistent |
| 7 | Add priority/fairness to the shared REST scheduler if scope counters demonstrate starvation | More timely fees/risk management and fair discovery | Medium / medium; no reason yet to increase requests |

## G. Trading verification and activity interpretation

Pre-rollout live configuration: High Probability/Favorites had **75 enabled profiles** and open holdings; each of five Scalper variants had **53 enabled profiles**; the two Maker portfolios each had **4 enabled profiles**. The three Sequential portfolios and Complete Set had **zero enabled profiles**. This audit does not resume user-paused strategies. Legacy Low Buy / High Sell is not in the active shadow routing path; its historical data remains stored.

Before rollout, Scalpers had durable orders, fills and completed round trips; High Probability held 160.33 contracts in a sampled health log. Maker initially had no monitored contracts, then obtained a shared monitoring slot as processing health recovered. Its earlier inactivity was at least partly discovery/admission delay; a monitored market alone does not guarantee executable orders or profits.

Tests cover causal book updates, public-depth/partial-fill execution, independent portfolio overlays, fee expiry and scheduled changes, duplicate requests, wallet/lots/order checkpoint equivalence, shared halt restoration, FIFO processing and batch bounds, responsive socket tasks during slow preparation, cancellation waiting for database completion, unacknowledged failed commits, settlement recovery, P/L accounting, dashboard transport and browser/gateway behavior. Local suite: **1,255 backend tests passed, 245 PostgreSQL-dependent tests skipped; 209 browser/gateway tests passed**. PostgreSQL CI and live post-deployment results are recorded below rather than assumed.

### Final deployment and verification

- Resource changes and diagnostics: [PR #102](https://github.com/princesspikachuu/kalshi-scanner-data/pull/102). Concurrent discovery freezing: [PR #103](https://github.com/princesspikachuu/kalshi-scanner-data/pull/103). Versioned binary checkpoint: [PR #104](https://github.com/princesspikachuu/kalshi-scanner-data/pull/104). Dashboard summary projection and complete research download: [PR #105](https://github.com/princesspikachuu/kalshi-scanner-data/pull/105).
- Final integrated local suite: **1,266 backend tests passed with 246 database-dependent tests skipped**, and **210 browser/gateway tests passed**. The PostgreSQL CI suites passed before each runtime release, including full experiment checkpoint round trips and the authenticated full-research endpoint.
- API readers were deployed and returned readiness HTTP 200 before the binary writer deployment. Render confirmed the final worker deployment live; fee warmup verified all 24 restored markets before feed processing. Subsequent logs confirmed the new checkpoint encoding and continued order submissions, maker resting orders, partial/taker exits and completed round trips.
- The final dashboard API deployment is live and `/health/ready` returned `{"status":"ready"}`. Cloudflare published gateway version `76f2f9e0-536d-4891-b1a1-a3554afcb06d`. Its deploy step succeeded; the subsequent unauthenticated CI smoke step returned HTTP 403. This is a remaining verification limitation, not a successful smoke check. Chrome loaded the owner sign-in screen; this browser has no signed-in owner session. Authenticated page rendering, the new download button and live response latency therefore remain unverified visually, although route and rendering tests passed.
- New 15-minute market contracts were discovered across rollover, and the final health sample reported **77 active strategy books** with state `ready`; paused legacy Convexity books are intentionally not counted as a feed failure. Scalper samples had 12–15 fresh books each. Orders, fills, risk exits and round-trip counters continued increasing; examples include a fractional 2.87-contract taker liquidation and a later one-contract maker profit exit with zero reported maker fee under its verified schedule. The simulated execution model continues to record actual worker delay, spread, depth and fees.
- No historical records were reset or deleted. Exact Decimal wallet values, lots, fees, order fields, RNG state, shared halts, research cells and discovery state survive encoding/recovery tests. Accounting and settlement/recovery tests passed against PostgreSQL. Live legacy wallet identities reconcile in the emitted account snapshot. **A full independent live reconciliation of every portfolio and all historical settlements was unavailable** because external SQL inspection is blocked and the browser is not signed in. Do not describe this audit as a complete independent financial audit.
- Sequential variants and Complete Set remain paused by their existing configuration; their live fill paths could not be exercised without changing user settings. Convexity also remains paused. Their execution/recovery paths retain test coverage. Low Buy / High Sell remains in preserved legacy history, not a concurrently running loop.
- Maker discovery found **39 candidates** in a later sample. Several were rejected for insufficient verified trade-print frequency; some were submitted for shared monitoring. Two historical submitted entries per portfolio had no confirmed fills, and later discovery waited for healthy processing. Thus Maker remains low-activity, with both market eligibility and processing admission contributing. This audit does not claim its fills have been verified live.
- Sports discovery is **intermittently degraded**: repeated `paper_sports_retry` / `KeyError` messages continued through 07:15 Pacific. Later scans successfully recognized a live NFL event and submitted it for shared monitoring at 07:19, so it is not wholly stopped. Existing retry logs do not reveal the failing field/line, and the precise malformed metadata case remains unresolved. Unknown live status continues blocking entries rather than allowing unverified trades.
- Processing bursts still delay inputs by seconds, and disconnect/stale-book gaps were observed during earlier rollout intervals. Freshness gates, admission pauses, queue simulation and unavailable-liquidation records remain active. The next performance priority is reducing repeated unchanged checkpoint work and diagnosing sports metadata failures, rather than buying more compute or weakening checks.

No additional Render services, instances or paid tiers were created or enabled. No real-money execution was enabled. The observed improvements reduce known waste, but do not establish that the current configuration can sustain unlimited market growth or that any trading strategy is profitable.
