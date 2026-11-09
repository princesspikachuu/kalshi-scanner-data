# MT-011 — Money Tree systems-efficiency audit (initial measured baseline)

Measured: 2026-11-09, 16:00–22:30 UTC (Render), with detailed application logs around 22:27 UTC.

## Scope / safety

This is a measured initial audit, **not a completed remediation**. Do not reduce active Favorites or Market Maker monitoring, unpause other strategies, disable a worker, reset accounts, or delete research/history. MT-004 and MT-015 are concurrently owned by other implementation sessions.

## Render service map

| Service | Plan / capacity | Responsibility | Observed load |
| --- | --- | --- | --- |
| `pocket-processing-staging` (`srv-dbhcqr0473hc739kj4pg`) | 1 CPU / 2 GiB | Paper engine / quote ingestion, checkpoint and strategy processing | 15-minute CPU averages ~0.71–0.88 CPU (71–88%); peak sampled memory ~1.15 GB |
| `pocket-api-staging` (`srv-dbgcsb6c6qcc73f1j6n0`) | 0.5 CPU / 512 MiB | API/web gateway | CPU generally ~0.002 CPU, memory ~94–134 MB |
| `pocket-research-staging` (`srv-dbgcsb6c6qcc73f1j6lg`) | 0.5 CPU / 512 MiB | Research and historical collection | CPU ~0.001–0.004 CPU; memory ~96–183 MB |
| `pocket-db-staging` (`dpg-dbgcrl6c6qcc73f1hi1g-a`) | 0.5 CPU / 1 GiB | Postgres primary | ~0.29–0.33 CPU (~58–66% of quota), 6–10 active connections |

Both workers start the same Python module but have separately audited environment roles (MT-014); do not assume duplication or disable either one.

## Top measurable waste/pressure sources

1. **Large, recurring mutable paper checkpoint; paused scalper history contributes substantial payload.** A live `shadow_checkpoint_size` record at ~22:27 UTC reports **10,839,379 decoded bytes** and **2,184,288 stored bytes**. Segment breakdown: `scalper_research` **6,305,979 raw bytes** across 164 members (~58.2% of decoded checkpoint); `verified_exit_evidence` 1,653,015 bytes; `hot_and_small` 2,763,741 bytes. The active worker reports `shadow_status_cost`: 8,477,541 decoded / 1,869,832 stored bytes, 156.5 ms preparation, 232.3 ms write in one sample. **Do not delete historical scalper research; investigate loading immutable paused research lazily from canonical history while keeping settlements/inventory available.** Segment caching already exists (659 hits, 221 misses, 220 entries, 9,276,848 retained bytes / 16 MiB maximum); assess efficacy before introducing redundant caches.

2. **Database durability/write-path latency.** The same ~22:27 UTC worker sample reports 4 commits, 2 inline checkpoint commits, 55 bulk event rows, 58 audit/extra rows, 7 ordinary upserts. Timings: **612.3 ms preparation**, **1,949.6 ms upsert**, **1,970.2 ms total write**, 1,594.7 ms worst write, 7.4 ms pool wait; 4,370,984 checkpoint bytes. Thus DB write/upsert time dominates this sampled durability cycle; pool contention was not the dominant cause in this sample. Investigate write amplification from frequently changing checkpoint sections and safe incremental/delta persistence. Do not conclude a persistent p95 latency from one sample; collect distributions.

3. **Legacy research collection failures / retry overhead.** Between 22:00 and 22:03 UTC, `pocket-research-staging` repeatedly logged `collection_step_failed` (call paths through `services.research.report_jobs`). `collection_days_status_v1` shows many `provider_timeout` and `attempts_exhausted` jobs across crypto/BTC/ETH, sports, weather. A 22:03 log reports `storage_compaction_deferred` with `QueryCanceled` SQLSTATE 57014, **2,400 second** retry delay and 4 consecutive failures; originals retained. Backoff exists (MT-013); the remaining collection errors and repeated job status lookups need rate and cost measurement. Do not stop this worker without checking historical collection dependencies.

4. **Main processing worker CPU concentration.** Worker 15-minute CPU averages routinely 71–88% of its one CPU between 16:00–22:15 UTC; separate API and research services mostly idle CPU. Prior telemetry in the shared queue records ~13,770 input backlog (~245 seconds) and >600,000 filtered quote updates; MT-012 already implemented early quote coalescing. Measure fresh post-MT-012 queue and filtering counters before claiming it has fixed throughput.

5. **Inactive-strategy health/status work remains visible.** At 22:27 UTC the active worker logged four `volatility_scalper_health` records for paused scalper folders (each `monitored:17`, `fresh_books:0`). This does **not** prove those strategies are entering trades (they reported zero current orders) or consuming 17 dedicated slots each; inspect what expensive per-cycle computations remain for paused folders. Keep their state and settlement requirements.

## Market Maker / Favorites throughput snapshot

At 22:27 UTC two maker folders each reported `monitored:2`, `fresh_books:0`, `orders:0`, `positions:0`, with cumulative:
- market_maker: 8,616 observations, 572 submitted entries, 15 fills, 9 completed.
- maker_competitive: 14,502 observations, 981 submitted entries, 39 fills, 30 completed.

These are cumulative counts, **not same-window fill rates**. Both cite "Waiting for fresh verified book". A `market_maker_scan` at 22:27 had 12 candidates and read-only verification with admission paused; active capacity is a current bottleneck under MT-004/MT-015. Favorites submitted paper-only orders in the same minute (real_orders_enabled=false).

## Database visibility constraint

Read-only Postgres SQL through Render connector was blocked: empty external IP allowlist (by design). Do **not** widen DB access or expose secrets for this audit. Use application-side safely bounded size/query telemetry, internal query tooling, or existing metrics to measure top JSONB rows, table/index growth and query repetitions.

## Recommended non-conflicting next engineering steps

1. Add bounded, sampled checkpoint-section byte and timing histograms (serialize, compress, write) with changes-since-last-write, to find repeated writes of unchanged cold/paused research state; preserve existing data and snapshots.
2. Add bounded durability upsert duration/row-count and checkpoint-write frequency aggregation (p50/p95) rather than relying on single-cycle log lines. Review possible chunk-level dirty tracking against current segment cache and checkpoint transaction semantics.
3. Quantify the research worker's failed collection cycles/min, provider timeout distribution, and `report_jobs` calls/min. Distinguish upstream timeout versus internal database error; honor its existing compaction backoff.
4. Recheck after MT-012/MT-015 deployments: monitoring backlog seconds, filtered/coalesced events per second, maker fills per slot-hour, Favorites accepted opportunity rate, and average CPU utilization in comparable windows.
5. Evaluate paused-strategy health loops for avoidable iteration while retaining settlement, accounting, history and diagnostics.
6. Revisit API/workspace payload profile and browser transferred bytes only after checking MT-008 and MT-009 fixes; avoid regressing lazy Favorites research views.

## Verification status

- Render service inventory: complete.
- Render CPU/memory/connection metrics: collected for 2026-11-09 16:00–22:30 UTC.
- Live worker + research logs: inspected around 22:00–22:27 UTC.
- Database table-level read-only audit: **blocked by secure network configuration**.
- Code fixes in MT-011: **not yet implemented**.
- Before/after proof of recovered capacity: **pending**.

Continue this task as IN PROGRESS. The audit itself has not yet met all acceptance criteria.

## Follow-up sampled worker baseline: 23:00–23:30 UTC (before PR #171 deploy)

The following sums cover 30-minute windows of **57** `shadow_durability_cost` records, **58** `shadow_pipeline_cost` records and **59** `shadow_checkpoint_size` records from Render. Window endpoints are aligned but different metric emitters may have small scheduling jitter; do not interpret individual sums as an exact causal breakdown.

- Durability telemetry: **1,286 successful commits**, ~**2,807,020,340 encoded checkpoint character-bytes** (~2.81 GB, mostly base64 transport) across 56 non-null reports; **7,580** audit/extra rows. This is cumulative write *traffic* reported by the application, not persisted database growth.
- Durability time totals: **321.17 s upsert**, **346.76 s total database write**, **242.17 s checkpoint preparation**, **4.85 s connection-pool wait** across the reporting interval. These are cumulative execution timings, not end-to-end wall time; individual 30-second reported window p50 was ~6.22 seconds of upsert time.
- Checkpoint size: 59 sampled records, median **10,979,476 decoded bytes**, **2,224,640 encoded text characters**, 95th-percentile sample ~11.04 MB decoded. The cached cold `scalper_research` section remains ~6.31 MB raw with 164 members; segment-cache hits were 60,678 at the most recent sample.
- Pipeline: **636,345 total processed inputs** across 58 sample windows; median reported queue backlog **41**, 95th percentile **1,695**. This is substantially better than earlier 13,770 backlog examples, so do not attribute old backlog figures to the current code without time alignment.
- PR #171 introduces counters `checkpoint_upserts`, `checkpoint_unchanged_skips` and `checkpoint_bytes_avoided` for genuine before/after savings measurement. It was not deployed during this baseline window.

This baseline shows the full-checkpoint persistence pipeline is a large recurring cost, but **does not prove how many snapshots are byte-identical**. Before claiming a material improvement, compare post-deploy skip ratio, checkpoint bytes, mean write duration/commit, CPU use and actual maker/Favorites throughput for similarly active market windows.
