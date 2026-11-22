# MT-030 — Regular High-Probability Favorites: November 21, 2026 low-throughput investigation

**Status:** In progress. **Owner:** MT-030. **Scope:** Only regular `favorites`. Statistics-Backed Favorites, Convexity, Market Maker and every other strategy must stay paused; real orders remain disabled.

**All times:** November 21, 2026, Pacific Standard Time (PST, UTC-8), unless a UTC timestamp is explicitly shown. Raw Render observations came from `pocket-processing-staging` logs. This is a targeted sampling audit, **not a complete SQL ledger or a claim of exact daily filled order totals**.

## Established source-level cause (P1, MT-018 owns actual fix)

The hosted 15-minute scanner `ForwardRun.discover_once` was gated by `legacy_discovery_required(series)`, which examined the **paused Convexity bot** but not the enabled regular Favorites bot. The 15m scanner therefore skipped future contracts when Convexity stayed paused, even with 75 regular Favorites bots running. No alternate regular Favorites 15m scanner exists in the hosted run path. This is a code defect; it does not justify turning Convexity back on.

**Repair ownership:** [Issue #333](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333) and [draft PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335), MT-018. That PR tests legacy OFF / regular Favorites ON, active 15m market discovery and subscription only after fee verification and fresh snapshot, guarded measured admission, weekend/DST entry timing and preservation of legacy held risk. MT-030 must not edit its `runner.py` or test files or claim its deployment.

## Sampled November 21 throughput/gating baseline

| PST time | Regular Favorites eligible / fresh markets | Available paper cash | Open bids | Hourly scan (listed / eligible / subscribed) | Interpretation |
|---|---:|---:|---:|---:|---|
| 01:57 | 26 / 26 | **$0.2036** | 2 | 600 / 1 / 1 (01:55 scan) | Funds nearly exhausted even while fresh books exist |
| 05:58 | 41 / 41 | $298.96 | 3 | 347 / 1 / 0 (05:55 scan) | One candidate deferred by the measured capacity gate in that scan |
| 09:58 | 36 / 36 | $5,375.30 | 4 | 0 / 0 / 0 (09:55 scan) | Finance/commodity hourly markets unavailable in that sampled weekend window |
| 13:58 | 22 / 22 | $5,415.87 | 6 | 69 / 0 / 0 (13:56 scan) | Listed hourly contracts, none satisfying admission/70–95c criteria |
| 17:51 | 14 / 13 | $5,433.77 | 6 | 0 / 0 / 0 (17:48 scan) | Fewer fresh monitored markets; some scheduled entry windows sleeping |

**Semantics:** `favorites_trading_diagnostics.active_markets` is eligible tracked markets, **not** independent filled/settled outcomes. `paper_hourly_scan.listed_markets` counts returned contract rows, **not** independent events; zero qualifying market is not proof of an algorithm bug. Snapshots came from nearby minutes and are **not** transactionally joined. The 75 running bots are configured profiles, not 75 simultaneous trading opportunities.

### Cash-restoration source clarified at 08:06 PST

The ~5,000 rise later in the day is **not** proven to be settlement-released cash. Read-only Render `favorites_trading_diagnostics` samples show:
- **08:06:10 PST**: wallet cash $391.6271, available $384.7571, 125.50 open contracts.
- **08:06:40 PST**: wallet cash $5,390.2271, available $5,384.0571, 127.50 open contracts.
- Within the same interval, `shadow_durability_cost` reported **2 processed command rows** (16:06:19Z) and then **1 command row** (16:06:51Z). Code in `services/paper_demo/shadow/host.py` has explicit idempotent paper `refill`/reset commands.
- This ~$4,998.60 net change while contracts increased by 2 is **strongly consistent with a $5,000 paper refill**, not a normal release of nearly that much collateral. The available logs do not expose the exact command type, so treat a refill as **likely, not independently confirmed**; don't infer direct live-money deposits or manipulate financial state.
- The earlier 01:57 PST shortage remains real. It can temporarily prevent 70–95¢ bids from funding one contract. Do **not** use the later $5k snapshot as evidence that earlier settlement delays resolved themselves; inspect actual official settlement confirmations separately if that matters to future allocation decisions.

### Confirmed paper collateral starvation at 01:57 PST

- `favorites_trading_diagnostics`: paper cash **$19.2036**, available/unreserved **$0.2036**, 515.01 open contracts, two resting orders.
- 401.38 contracts still open in 17 markets; 113.63 contracts in 3 expired markets still awaiting official settlement. No expired settlements were recorded for those markets in that sample.
- The regular collector quotes **70–95 cents** and `favorite_entries.quote` returns no new order if available cash cannot fund at least **one contract**. This makes a concrete inability to submit orders until legitimate settlement/refunding returns paper collateral. Later $5k available shows the bottleneck was time dependent. Do **not** force official results or sell held positions against the user's hold-to-settlement instruction.

### Maker order churn is a separate observed bottleneck

- `favorite_paper_entry` is logged on a **submitted pending/resting maker order**, not on a confirmed fill or independently settled event. Counting those lines as trades is incorrect.
- A selected `favorites_quote_lifecycle` five-minute window near **13:44 PST** contained **29 submitted bids, one first-filled order, and 39 canceled without fill**. Submissions/fills/cancels occur on different temporal order cohorts, so **1/29 is NOT an authoritative fill probability**.
- Existing MT-026 evidence from roughly 56 staggered five-minute snapshots similarly reported high unfilled cancellation volume, with cohort/censoring warnings. `favorites_quote_lifecycle` does not yet expose why a canceled order was canceled.
- **Draft [PR #336](https://github.com/princesspikachuu/kalshi-scanner-data/pull/336)** (MT-030, separate from MT-018) adds fixed, bounded, **regular-Favorites-only** canceled-unfilled reason categories to the existing ephemeral observer. It does **not** change any order price/size/lifetime, fee, capital limit, settlement, market subscription or persisted history.

## Recent outcome and operational checks

At **17:59 PST**, `favorites_collection_quality` reported **4 newly verified outcomes in its preceding one-hour timestamped window, all weather**, and zero in 15m, hourly-price, sports or daily-weather. These rolling counts are documented **lower bounds** because historical observations with missing timestamps are excluded. They cannot substitute for a full day-level filled/settled market ledger.

Selected `paper_monitoring_capacity` measurements had admission on, backlog approximately zero to 30, memory around 47–52% of its 2 GiB worker limit and sub-10ms sampled input lag. Those points do not support general CPU/memory saturation as the primary cause, though per-market admission deferrals still occur.

## Data limitations and causality boundaries

1. The hosted Render read-only SQL connector cannot reach staging Postgres because its external IP allowlist is intentionally empty. **Do not weaken database networking or request credentials** for this audit.
2. The maker lifecycle observer was introduced mid-November 21 and resets on worker restart, so exact November 20 vs November 21 *first-fill* counts are not available from that observer. Earlier `favorite_paper_entry` data are submissions, not fills. Do not publish an invented day-over-day fill rate.
3. Hourly price, weekend cash-index, daily-weather windows, maker fees, book freshness and risk thresholds may intentionally suppress trading. Label zero opportunities separately from rejected/expired/canceled orders and from filled and independently settled events.
4. Only the authoritative exchange final outcome settles held research positions. Preserve all original observations, cached price/time cohorts, paper cash, open and expired lots, R2 roots and audit history.

## Ranked next actions

1. **MT-018 / issue #333**: Finish exact-head CI on PR #335, deploy through normal checks-pass, verify regular-only 15m subscriptions, first fills and later independent venue-confirmed settlements. Do not enable legacy Convexity or Statistics-Backed Favorites to bypass the discovery gate.
2. **MT-030 / PR #336**: Finish full API/PostgreSQL CI, safely merge/deploy ephemeral canceled-unfilled cause counts. Compare cancellation reasons/market types and first fills across nonoverlapping windows, distinguishing still-open orders and censored/restored orders.
3. With verified fills restored, inspect whether available cash routinely falls below one 70–95c contract because of long-lived positions and pending settlement. Any allocation change requires separate risk/funding tests and must honor hold-to-settlement; do not manufacture capital or rush settlement.
4. Measure hourly/weather/sports rejection and availability across comparable active time windows, including closed cash-index sessions. Improve actual eligible event discovery without reducing healthy 15m evidence, relaxing fee/risk controls or counting contracts as independent samples.

**Queue source of truth:** [WORK_QUEUE.md](https://github.com/princesspikachuu/kalshi-scanner-data/blob/main/WORK_QUEUE.md), task MT-030, U1 URGENT.


## Post-merge runtime verification — November 22 02:08 UTC

- [MT-030 PR #336](https://github.com/princesspikachuu/kalshi-scanner-data/pull/336) merged as `ce0765c902c4b37a6a8d3c9404210a317551b2c4`; targeted/full exact-head tests and both post-merge workflows ([push 44974058622](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974058622), [PR 44974063291](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974063291)) passed. The exact Render deploy `dep-dc14s2vb9u1s73ftuibg` became `live` on `pocket-processing-staging` at **2026-11-22 02:06:47 UTC**.
- The old instance temporarily emitted older telemetry while the replacement emitted `demo_lock_wait`; the replacement then emitted `shadow_worker_start_recorded` and `demo_worker_ready` at **02:08:48 UTC**, indicating successful singleton-lock handoff **without** forced restart or data reset.
- First new worker `favorites_quote_lifecycle` at **02:08:57 UTC** contained the newly deployed `unfilled_cancel_causes: {}` and `observer_errors_total: 0`. The 02:11:00 UTC snapshot had **four submitted weather maker orders, zero first fills, zero unfilled cancellations, and four still-open orders** over the 5-minute restart-local window; reason histogram remains empty because no confirmed cancellations were observed, *not* because all cancel causes are zero or resolved.
- `paper_strategy_health` remained **75 regular Favorites bots, 0 Statistics-Backed bots, all other strategies paused, `real_orders_enabled=false`**. Worker feed reported `ready`, four fresh strategy books, low input backlog and available admission shortly after startup. Cumulative `favorites_collection_quality.unique_verified_outcomes` remained **4,637** before and after handoff; this verifies preserved aggregate observed history, **not** an independent byte-for-byte R2/SQL restore.
- [MT-018 PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335) remains **draft and unmerged** while its exact-head full suite runs (at last check head `ac414bf6ea6b73865a436d29dbb6110aa454e881`); the 15-minute discovery defect is therefore **not yet repaired in the live worker**. Do not claim a throughput improvement based on this diagnostics-only release.
- Next: after valid 15-minute discovery is merged/deployed, measure market-type availability, independent *first-filled events*, held-to-authoritative-settlement event outcomes and the fixed cancellation-cause breakdown across nonoverlapping windows. Maintain read-only scope, risk/fee/finality protection and no LIVE orders.


## Post-deployment maker cancellation evidence — November 22 02:13 UTC

The verified post-PR #336 worker emitted a five-minute **non-disjoint** `favorites_quote_lifecycle` sample at **2026-11-22 02:13:34 UTC / November 21 18:13:34 PST**:

| Metric | Count |
|---|---:|
| Submitted maker orders | 7 |
| Independently attributed submitted events | 4 |
| First-filled maker orders | 2 |
| First-filled independent events | 2 |
| Canceled without fill | 2 |
| Currently open orders | 3 |

- Both confirmed unfilled cancellations were tagged `quote_unavailable`, not `same_bucket_reprice`, `crossed_quote` or `fee_guard`; both rested at least 120 seconds, median 143.14 seconds.
- All observed orders in this window were **hourly weather** (regular Favorites portfolio only); the full case remains weather-specific, not evidence of overall market/15m cancellations.
- Observer had `observer_errors_total=0`. This sample is useful for per-cancellation cause attribution but its seven submitted bids and two first fills are **NOT** a daily success rate or independent market-win count; first fill is distinct from eventual venue-confirmed settlement.
- During that window the separate trading diagnostics showed **75 regular Favorites bots, zero Statistics-Backed, $5,439.93 available virtual cash**, at most eight current active/fresh markets, with 35 lots (~33.09 contracts) in nine expired markets still awaiting official recorded settlement. Latest processing capacity reported admission open, zero backlog, memory under 40% at that moment, and real-money orders disabled. Do not force settlements.
- At the same checkpoint **both exact-head PR #335 GitHub Actions runs** (full [44974770656](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974770656) and focused [44974770666](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974770666)) **passed** on `ac414bf6ea6b73865a436d29dbb6110aa454e881`, but the PR remains **draft/unmerged** and therefore **not deployed**. MT-018 has exclusive scanner-fix ownership. Do not claim restored 15m throughput until merged and proved live.
