# Volatility Scalper (paper only)

Three independently funded $1,000 portfolios reuse the existing authenticated,
read-only Kalshi WebSocket subscription, fee cache, discovery scheduler, order
engine, fenced atomic PostgreSQL checkpoint, balance histories, and dashboard.
No exchange order endpoint or real-money strategy is added or changed.

| Folder | Entry | Profit execution | Stop / max hold / liquidation |
| --- | --- | --- | --- |
| Volatility Scalper | Volatility-relative mean reversion; maker or fee-qualified taker | Partial IOC and trailing exits | 7¢ / 90 sec / 30 sec before close |
| Fixed / maker entries | Fixed 2¢ displacement, maker entry | Passive complementary maker netting; IOC protection | 5¢ / 60 sec / 60 sec before close |
| Adaptive Range / Grid | Support/resistance with volatility-scaled spacing | Partial IOC and trailing exits | 9¢ / 120 sec / 45 sec before close |

These are explicit, unproven hypotheses. Parameters do not learn automatically.
Five chronological days are labeled training and the following two validation,
using each market's opening day. Sides and variants of an event share that split.
There is no fitted reversal probability; the dashboard does not manufacture one.

## Discovery and resources

The installer adds 28 fifteen-minute and 25 hourly profiles to each portfolio,
with five contracts per order. Existing registry rows and wallets are untouched.
Fifteen-minute markets use the existing rolling inventory. Hourly candidates use
the same bounded scans and scheduled session backoff as Favorites. Scalpers may
also admit two-sided hourly markets outside the 70–95¢ favorite band; Favorites'
entry policy is unchanged. Inactive series remain subject to shared backoff.
Other market categories can be added through the profile registry; unregistered
sports, weather and long-duration markets are not scanned by this release.

Each strategy evaluates at most once per ticker every two seconds. Windows hold
at most 60 samples over 120 seconds and require five fresh samples. New entries
pause under measured worker backlog/lag; held inventory retains protective exits.
Per-portfolio public-book copies provide isolated hypothetical depth overlays;
there are no additional sockets or independent polling loops. Portfolio snapshots
use bounded recent trade summaries and durable cumulative research cells. Full
records live in the existing journal and archive path.

## Execution and accounting

Maker buys clear displayed queue plus seeded 5–35% unknown competition using
actual aggressive trade prints, never quote touches or cancelled public depth.
Takers wait for execution latency (and measured worker delay), then sweep only
observed available depth within the order's limit. Partial IOC remainders cancel.
Fees come from the shared verified current series policy, including maker fees.

A passive sell of YES at p is equivalent to a maker buy of NO at 1-p, paired
with the held YES contract to release $1 collateral. The fixed portfolio uses
that existing netting path for passive profit exits. The dashboard presents it
as a sell and labels complementary maker netting; cash needed to post it remains
reserved. The fixed comparison uses maker-only discretionary executions; timed
liquidations and stops may still take liquidity. This is not a strict all-maker
safety policy.

Both sides are scored independently; only one entry direction per portfolio and
market is selected at a time. No entry is stacked over a pending cancellation,
exit or held position. Remaining partial entries are cancelled before exits.
Independent portfolios intentionally model counterfactual fills against the
same market, not the aggregate capacity of deploying every variant together.

Stops and timed exits override minimum holding time. Liquidation uses an IOC
limit up to 2¢ below the current bid, retrying remaining inventory. Missing or
stale bids and closed-market failures are recorded. Confirmed settlement still
reconciles stranded contracts, labeled carryovers rather than completed scalps.
Partial profit-taking raises the remaining target; a net-of-fee trailing exit
protects the remaining quantity. Wallet identities and realized P/L include all
trades, including losses and data gaps.

## Research records

- `SCALPER_OPPORTUNITY`: causal bid/ask, depth, volatility, reversals, movement
  frequency, support/resistance, spread, target, fees, selection/rejection reason,
  duration, asset, horizon and chronological split. Identical unchanged decisions
  are coalesced; counters still count each evaluation. Decisions from all
  variants on one tick are persisted together as `SCALPER_OBSERVATION_BATCH`
  to reduce database row overhead.
- `SCALPER_ENTRY_DECISION`: selected order, configuration, causal recent price
  samples and expected profit at observed resistance (not a probability forecast).
- `SCALPER_QUEUE_ESTIMATE`, normal order/fill/IOC/cancellation records: actual
  simulated lifecycle, queue, worker delay, slippage, partials and fees.
- `SCALPER_EXECUTION`: submission-to-fill and profitable-exit timing.
- `SCALPER_EXIT_DECISION`, `SCALPER_LIQUIDATION_BLOCKED`, `SCALPER_UNFILLED`:
  exit reasons and explicit execution failures.
- `SCALPER_ROUND_TRIP`, `SCALPER_SETTLEMENT_CARRYOVER`: full entry/exit data,
  costs, realized net, duration, favorable/adverse excursion and coverage flag.

Cumulative research groups separate category, asset, duration, entry horizon,
training/validation and maker/taker entry. Financial histories retain existing
1h/6h/24h/7d/lifetime controls, including marked unrealized changes. Detailed
recent records and cumulative groups appear inside each collapsible market.
Full older records remain in the existing PostgreSQL audit/archive system;
the current UI shows bounded recent samples rather than exporting all history.

## Verification and limitations

Deterministic acceptance covers both sides, maker queue uncertainty, actual print
fills, partial execution, complementary maker exits, partial profit-taking,
repeated trips, fee/cash reconciliation, stops, liquidation failures, restart
recovery, isolated portfolios and processing-backlog gating. A disposable-DB
integration test verifies additive installation, controls and persisted research.
Existing strategy and dashboard/gateway tests remain required.

Two-second sampled features are not submillisecond high-frequency execution.
Queue competition is an estimate and cannot prove live fill probability. Current
movement/fee filters can reject activity without asserting that an edge exists.
Equity drawdown is sampled; capital efficiency uses filled entry cost and full
holding time (conservative for partial exits), not exact capital-time integration.
No automatic fitting, promotion, real-money execution or hard performance
profitability claim is implemented.
