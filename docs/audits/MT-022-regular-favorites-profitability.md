# MT-022 — Regular Favorites profitability and uncertainty audit

**Scope:** Regular High-Probability Favorites (`favorites` portfolio) only. No Statistics-Backed Favorites, execution logic, account mutations, or historical rewrites.

## Evidence path audited

1. `favorite_timing.fill` records the actually filled quantity and price with the entry fee, remaining event time, verified book state and original event identity. Splitting or partially filling an order does not itself create an independent event.
2. `favorite_timing.settle` waits for `yes_payout_confirmed` to be binary, then derives hold-to-settlement research returns from original fill costs, not early exit proceeds or exit fees. Paper trading balances and any actual exits are separate.
3. `favorite_timing.rows(hold_only=True)` exposes confirmed `outcome_events` and fee-inclusive `return_events`. Historical returns reconstructed without exact event sizing carry `estimated=True`; unverified fill histories do not receive invented exact returns.
4. `favorite_collector_timed_totals` merges category/price/time rows into Detailed regular Favorites tables. `favorite_wide.summarize_wide` uses actual timed fill events where available and does not guess bin placement for ambiguous old times. `favorite_single.summarize_single` pools cost and net by event before taking an equal-event mean.

For each fully attributed event *e*, the reported held return is:

```text
cost_e = sum(filled quantity × execution price + entry fee)
net_e  = sum(filled quantity × confirmed settlement payout) - cost_e
ROI_e  = 100 × net_e / cost_e
average held P/L % = arithmetic mean of ROI_e across distinct events
```

A single event with multiple thresholds, fills or price/time observations contributes **one** return to a combined Single bucket, with those cash flows pooled before computing ROI. The same event may appear in separate Detailed/Wider cohorts, which must **not** be interpreted as statistically independent across cohorts.

## Confirmed and fixed reporting defect

The Detailed rollup previously accepted **any** `return_events` entry (even if the same source row had no verified `outcome_events` for that event) and accepted explicitly `return_policy=all_executions` historical returns. These can inflate held-P/L observations or substitute exit-based returns for settlement-based returns. Historical nonfinite or zero-cost values could also poison the aggregate.

PR #323 filters the **derived, read-only** regular Favorites Detailed rollup to events with a valid binary outcome in that same cohort; preserves the original event-level fee/cost/net when valid; omits explicit all-executions historical returns from held ROI; and avoids nonfinite/invalid event amounts. It normalizes event IDs without editing source maps. No existing records are deleted, reset or rewritten. Actual realized `net` remains separate.

## Statistical interpretation and remaining limitations

- **Detailed and Wider 90% error** is the Wilson *binary outcome win-rate* interval, in **percentage points**. Its win-margin comparison uses estimated entry break-even. Neither is a confidence interval for cash P/L. Different entry costs or mixed thresholds can make win margin and event-level ROI disagree.
- **Single-bucket 90% P/L uncertainty** (owned by PR #322, merged independently) is an approximate Student-t interval over **distinct event returns**, not contracts or fills. The minimum of 20 event returns and mixed observed gains/losses is a display safeguard, not proof of IID observations or profitability.
- **Cross-market correlation:** Event ticker deduplication removes same-event pseudoreplication but does not prove independence of adjacent crypto intervals, concurrent related markets, or overlapping venue events. Narrow uncertainty must never be treated as a guaranteed edge. A cluster/time-aware uncertainty study is separate future work.
- **Estimated historical attribution:** Older cohorts without exact per-event quantity may report reconstructed, explicitly flagged estimated returns. These are not identical in evidentiary strength to exact fill-level attribution; retain this distinction when interpreting confidence.
- **Missing settlements:** An unverified/unknown market outcome is not a loss, win, or zero-ROI sample. It should remain uncounted until authoritative confirmation; never delete its original trading records.
- **Research limits:** The fixed-size in-memory observation maps and historical source completeness require separate archival audits before making claims of *exhaustive* statistics across all time. This PR does not alter retention or source files.

## Regression coverage

`services/api/tests/test_regular_favorites_profit_audit.py` checks fee-inclusive partial fills and event-equal ROI, duplicate event deduplication, orphan/unknown outcomes, excluding explicit old exit-based returns, rejecting invalid historical values, stable event identity and non-mutating source behavior.

**Release rule:** Full exact-head GitHub API/PostgreSQL and frontend CI must pass before merging or deploying PR #323. Any runtime validation should inspect only derived dashboard research; keep live orders disabled and all nonregular strategies paused.
