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
