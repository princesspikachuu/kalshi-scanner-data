# Pocket Analytics app plan

Status: working product plan. Planned features below are not claims about the current dashboard's capabilities.

Draft expansion: [remaining app build plan](planning/BUILD_PLAN.md), including SQL/data design, continuous engine, paper/live phases, screens, failure behavior, acceptance gates and the first backlog. This planning branch is not a deployment.

## Product goal

Run trading strategies automatically, with historical research supporting strategy selection and evaluation. The intended workflow is research → strategy testing → paper trading → live automation → performance review. The engine must keep operating when the phone app or browser is closed.

Markets remain limited to underlying outcomes lasting one day or less: hourly and daily weather, Bitcoin/Ethereum and pooled 15-minute crypto, sports game/match winners, and daily financial-index outcomes. Longer-horizon contracts are excluded.

## Required early-sale analysis

Determine the downside sale-price threshold for each original purchase-price category at which selling early produces a better expected net result than continuing to hold. The purpose is loss prevention/reduction only; profit-taking targets are outside this feature. This is a required strategy-testing feature with the previously requested on/off loss-reduction switch.

### Comparisons and controls

- Offer an on/off early-sale control. Off means holding the same entry positions to settlement; on applies the selected exit rules and recalculates outcomes.
- Estimate a separate downside exit threshold for each original purchase-price category: 50–59.9¢, 60–69.9¢, 70–79.9¢, 80–89.9¢, and 90–99.9¢. Record exact entry prices as well as their category.
- For each category, compare candidate executable sale-price thresholds with continuing to hold, conditional on the price reaching that threshold. The question is whether accepting the available sale now improves the expected net outcome, including later recoveries, rather than merely reducing the number of losing settlements.
- Display the suggested threshold as an actual sale price in cents, with its change from entry for context. Define whether the rule triggers at or below that price, and validate that trigger consistently.
- Analyze thresholds separately by market category/contract family and time remaining. Account for remaining time at the exit decision as well as time remaining at entry; do not imply a universal threshold when these change the result.
- A loss-reduction rule can still realize a loss; it must not be presented as guaranteed loss avoidance. If no threshold has adequate evidence of improvement, report that explicitly instead of inventing a threshold.
- Save exit rules with the strategy so backtesting, paper trading, and eventual live execution use the same definitions.

### Evidence and execution model

- Use the same entry sample and fill assumptions for the hold and early-sale comparison. Report entry attempts, fills or estimated fills, exited positions, and positions held to settlement separately.
- Evaluate triggers in time order using only information available at that moment. Never select an exit using knowledge of the eventual outcome.
- Model entry and exit fees, spread, available exit-side quotes, size/depth where available, slippage assumptions, order type, and non-fills. A last-traded price is not proof that an exit was available at that price.
- Distinguish an immediately executable sale from a resting maker exit order, including its wait time, partial fills, expiration, and fallback behavior.
- Handle missing paths, stale quotes, ambiguous intrabar ordering, and truncated history explicitly. Label coarse candle simulations separately from stronger order-book/trade evidence; show unavailable results where the evidence cannot support the requested test.
- Preserve collection provenance, data coverage, model version, and assumptions so each comparison is reproducible.

### Results to show

For each purchase-price category, show the recommended downside sale-price threshold (or no supported threshold), expected net proceeds from selling versus holding at that decision point, net profit/loss and ROI after modeled costs, improvement or deterioration versus holding, sample size and date coverage, frequency and timing of exits, realized loss reductions, later recoveries missed by exiting, and losing-period/drawdown measures. Include all qualifying trades and price paths, not just positions that eventually lost. Show uncertainty and performance on later or otherwise held-out data that was not used to choose the threshold.

Select the highest expected-net-improvement research candidate before confidence/validation gating. If that candidate lacks evidence, report no reliable threshold instead of falling back to a smaller low-variance salvage threshold. Prefer the higher sale price on an exact expected-outcome tie. Show the approximate percentage of entry price lost at the candidate; a small salvage benefit must not be presented as preventing most of a loss. Rank rules on consistent net outcomes, not win rate alone. The interface must distinguish historical simulations, estimated fills, forward paper trading, and actual execution.

### Acceptance criteria

1. Switching early selling off reproduces the hold-to-settlement baseline for the eligible matched sample.
2. Switching it on recalculates the results and states the exact rule, costs, and coverage used.
3. Each original purchase-price category has its own tested downside threshold or an explicit statement that no threshold is supported. No profit-taking targets are included.
4. The comparison includes both favorable and unfavorable effects of selling early, including positions that later recovered, with missing-data exclusions visible.
5. Suggested thresholds include supporting sample size and validation outside the data used for tuning.
6. Paper and live modes can express the same saved exit rule, with actual orders/fills recorded separately from simulations.

Initial implementation: the current dashboard now integrates the on/off downside-exit comparison into the main time-by-price heatmap and its cell details with saved minute-close bid paths, per-family/time/cost-band thresholds, chronological training/validation, matched hold outcomes, and explicit missing-coverage handling. The main table retains the full holding dataset in both switch positions and adds only the measured exit-minus-hold difference from covered validation positions. Missing/training-only paths stay at the holding baseline; coverage is shown separately. Entry fees remain excluded consistently with the original table, and incremental exit costs use a fixed fee-stress scenario. Quote fills are assumed. Actual fees, depth/latency/slippage replay, finer exit-time rules, and paper/live execution remain planned; this implementation does not activate trading.

## App areas

| Area | Purpose |
| --- | --- |
| Home | Engine state, funds, positions, recent performance, and issues needing attention |
| Strategies | Define, test, save, enable, and pause entry/exit rules and spending limits |
| Research | Collect data, inspect latest and cumulative history, filter dates, and browse previous collections |
| Trading | Orders, fills, positions, intended exits, and completed trades |
| Performance | Compare historical testing, paper trading, and actual outcomes after costs |
| Activity and settings | Decision logs, job progress/errors, connections, notifications, and preferences |

Remember the selected page, category, strategy, dataset, metric, and filters across reloads. Every background job should identify what it is running and what it added when finished.

## Strategy and execution requirements

Each saved strategy defines eligible markets, entry conditions/timing, maker bid offset, order size, wait/cancel/replace behavior, exit rules, and limits per trade, category, strategy, and across all open positions. Once enabled, it executes within those rules without individual approval for routine trades.

The engine needs reconnect/reconciliation behavior, durable order identifiers and records to prevent duplicate submission after restart, stale-data handling, configurable pause conditions, and a clear manual pause control. Changes to an enabled strategy must be versioned so positions can be traced to the rules that opened them.

Whether newly discovered strategies or automatic rule changes can activate without review remains an open product decision, separate from automatic execution of enabled rules.

## Proposed technical stack

| Component | Proposed choice |
| --- | --- |
| Main database | PostgreSQL for collections, market metadata, strategy versions, orders, positions, and results |
| Interface | React + TypeScript with Vite, hosted on Cloudflare |
| API | Python + FastAPI, hosted on Render |
| Trading engine | Separate continuously running Python service on Render |
| Research | Separate Python worker, isolated from trading workloads |
| Large raw archives | Compressed files in Cloudflare R2 |
| Code and deployment | GitHub; move operational data out of GitHub CSV files as the database migration is completed |

Use exact decimal/fixed-point representations for money and contract quantities. Keep current market state in memory for evaluation and persist changes without blocking the trading decision path. PostgreSQL is the durable source of truth; large raw data belongs in archive storage with links/provenance in the database.

## Speed requirements

- Receive live market events continuously and evaluate only affected strategies.
- Keep live trading independent of historical downloads and recalculations.
- Target under 100 ms for internal strategy evaluation and under one second from receipt of a qualifying update to order submission, subject to exchange limits. These are unverified engineering targets, not guarantees of end-to-end latency or fills.
- Update order/position status in the interface within seconds.
- Save reusable historical inputs, fetch missing periods, and calculate strategy variations against stored data.
- Measure latency distributions, queue depth, stale-data incidents, and workload interference before selecting larger hosting plans.

## Hosting budget

Working estimate discussed: approximately $58/month base ($7 API, $25 engine, $7 research worker, $19 PostgreSQL), with a $60–$80/month starting budget for modest storage/usage overhead. Static interface hosting can start free. Prices and workload sizing require rechecking before provisioning. This excludes trading funds, exchange fees, paid external datasets, and redundant failover infrastructure. No purchase or migration is represented as completed by this plan.

## Delivery sequence

1. Define strategy records, exit rules, data requirements, and execution controls.
2. Finish reliable research ingestion and implement the early-sale comparison above using adequate price-path evidence; preserve the existing latest-versus-cumulative distinction.
3. Introduce PostgreSQL, raw archives, the API, and the structured app interface incrementally.
4. Build the independent engine in paper mode, recording live data and execution evidence for forward validation.
5. Add live automatic execution using the same strategy definitions and controls, then expand supported categories and comparisons.
