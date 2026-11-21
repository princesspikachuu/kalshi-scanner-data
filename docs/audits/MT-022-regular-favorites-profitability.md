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

The Detailed rollup previously accepted **any** `return_events` entry, including returns without a verified outcome and old `return_policy=all_executions` cash records containing early exits. This could inflate held P/L and suppress useful known-outcome exits, or break on invalid costs.

PR #323 reconstructs *hypothetical held* returns in a **read-only derived view** for every regular Favorites table and research detail endpoint. When a confirmed outcome exists, it uses original entry quantity and entry cost including entry fees, **ignoring historical exit proceeds and exit fees**. Exact historical per-event fills are preferred. When only aggregate entry sizing remains, per-event quantity is conservatively estimated and the return is labeled `estimated`; malformed original costs are excluded. Unknown outcomes never enter the P/L or uncertainty denominators. Correlated/repeated fills are deduplicated and incomplete cohorts do not generate a falsely complete ROI. Source records are never deleted, reset or rewritten; actual realized `net` remains separate.

## Statistical interpretation and remaining limitations

- **Detailed and Wider 90% error** is the Wilson *binary outcome win-rate* interval, in **percentage points**. Its win-margin comparison uses estimated entry break-even. Neither is a confidence interval for cash P/L. Different entry costs or mixed thresholds can make win margin and event-level ROI disagree.
- **Single-bucket 90% P/L uncertainty** (owned by PR #322, merged independently) is an approximate Student-t interval over **distinct event returns**, not contracts or fills. The minimum of 20 event returns and mixed observed gains/losses is a display safeguard, not proof of IID observations or profitability.
- **Cross-market correlation:** Event ticker deduplication removes same-event pseudoreplication but does not prove independence of adjacent crypto intervals, concurrent related markets, or overlapping venue events. Narrow uncertainty must never be treated as a guaranteed edge. A cluster/time-aware uncertainty study is separate future work.
- **Estimated historical attribution:** Older cohorts without exact per-event quantity may report reconstructed, explicitly flagged estimated returns. These are not identical in evidentiary strength to exact fill-level attribution; retain this distinction when interpreting confidence.
- **Missing settlements:** An unverified/unknown market outcome is not a loss, win, or zero-ROI sample. It should remain uncounted until authoritative confirmation; never delete its original trading records.
- **Research limits:** The fixed-size in-memory observation maps and historical source completeness require separate archival audits before making claims of *exhaustive* statistics across all time. This PR does not alter retention or source files.

## Regression coverage

`services/api/tests/test_regular_favorites_profit_audit.py` checks fee-inclusive partial fills and event-equal ROI, deduplication, known winning exits, known losing exits, exact older entries, estimated multi-event old entries, missing outcomes, wider/single/detailed held consistency, malformed source values, stable identities and nonmutating source behavior.

**Release rule:** Full exact-head GitHub API/PostgreSQL and frontend CI must pass before merging or deploying PR #323. Any runtime validation should inspect only derived dashboard research; keep live orders disabled and all nonregular strategies paused.
