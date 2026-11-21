# MT-004 Market Maker throughput: first live funnel diagnosis (2026-11-09)

Status: **instrumented; not yet proven to increase fills**.

## Live observations

Render `pocket-processing-staging` was sampled at approximately 22:19–22:23 UTC.
- Both independent Market Maker paper portfolios were enabled (four running profiles each). Their latest sampled cash balances were approximately $998.80 (baseline) and $996.14 (competitive), with **zero open contracts** in both. This is an observed interval, not a lifetime fill-rate claim.
- Physical Maker subscriptions were **two** in the recent capacity samples. `maker_slots_free` alternated between **five** in an accepting window and **zero** while admission paused.
- Worker admission was often paused by processing health, even with no provider cooldown. Sample backlog ranged from zero to 1,611 and p95 lag from ~0.53 to 3.70 seconds; the precise health gate can also depend on processing/telemetry not fully included in these samples.
- The Maker scanner held 9–12 candidate markets. In the top ranked list, a previously admitted market had **19 recent trades/hour** and fee-aware expected net of $0.05 per modeled round trip. A second with ~15 trades/hour was rejected when current quotes became ineligible. Other candidates were rejected for insufficient executed trade frequency or unstable recent prices.
- Scanner's `expected_net_per_round` and turnover ranking are admission **heuristics**, not actual maker fills, guaranteed profit, or demonstrated execution probability.

**Initial diagnosis:** Opportunity discovery and monitoring allocation are major bottlenecks; a broad spread-threshold reduction without verified activity or maker fills could increase adverse selection. The worker's processing health and the number of monitored slots deserve correlation with quote/fill funnel before loosening trading settings.

## Instrumentation introduced

`maker_funnel_snapshot` returns bounded counts across *all retained scanner candidates*, not merely the top eight previously logged. Per scan it records:
- total candidate count;
- verified/inspected candidates;
- short-lived cached-admission candidates;
- rejection/admission reason counts;
- category counts.

It is computed entirely from in-process scanner state. It makes **zero new Kalshi reads**, changes no strategies, market subscriptions, simulated liquidity or risk settings, and retains candidate history. Counts reflect the scanner's current candidate cache, not cumulative attempts or actual fills; don't use them as a substitute for execution funnel data.

## Next experiments needed to complete MT-004

1. Over comparable active market windows, pair the new scanner reason histogram with physical Maker subscriptions, bid/ask quote placement, cancellations/requotes, partial/full fills, inventory turns and realized net.
2. Locate the dominant stage of attrition. If most rejections are `current_price_or_spread_not_eligible`, test fee-aware thresholds/price bands on verified fresh books, without crossing uneconomic spreads. If `insufficient_executed_trade_frequency` dominates, test better discovery sources and low-yield slot rotation. If admission is predominantly paused, coordinate with MT-005/MT-015 on measured queue capacity rather than simply raising slot caps.
3. Verify both baseline and competitive quote variants independently and preserve distinct paper wallets/history.
4. Demonstrate improved useful quotes and fills, not merely more scans, before marking MT-004 done.

This PR makes no claim of increased trading frequency or profitability.
