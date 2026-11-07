# Paper strategy experiments

The existing Convexity bots move into **Convexity · Paused**, preserving their wallet,
open-position risk management, and results. **Sequential Spread Trading** and
**High-Probability Favorites** each have one bot per existing 15-minute series.
**Complete-Set Arbitrage** has a same-day multi-market scanner. These are virtual
portfolios with independent $1,000 starting deposits over a shared production
read-only feed. No exchange order routing is added.

Sequential Spread Trading tests complementary maker bid pairs. Existing public
L2/print execution modeling, 150ms latency, queue estimates, fees, cancellation
races and partial fills apply. One-contract trials bootstrap empirical estimates;
the UI explicitly labels those as exploration and shows unknown probabilities.
The learned model separates first-fill probability from completion conditional on
a first fill and includes failed-attempt P/L. A minimum 20 samples and positive
approximate lower mean-profit estimate are required before scaling up to the
configured size. This is exploratory paper selection, not a validated predictor.
No-fill observations count; data-gap cycles do not train the model. Remaining
unmatched inventory attempts depth-limited exits 30 seconds before close and
otherwise remains financially accounted for through actual settlement.

Complete-Set Arbitrage searches paginated open events. For distinct markets in an
API-verified mutually exclusive event, buying NO on n outcomes pays at least n-1,
even when none of those outcomes wins. This first version searches NO pairs and
baskets of up to four markets per event. It does not infer exhaustive YES coverage
from titles, or assume cross-event correlation implies coverage. Each market must
be active and close within 24 hours. It checks depth, actual current fees and a
1-cent-per-set execution margin. Purchases are simulated taker IOCs with 150ms
latency and individual leg limits; this is not atomic basket execution. Incomplete
packages attempt to unwind; all losses remain visible. Completed packages stay
held until authoritatively settled. The scanner is bounded to eight subscribed extra
markets (reduced when the legacy feed consumes the verification budget), rotates
untraded groups after five minutes and at most two new event groups per discovery pass.

High-Probability Favorites posts passive entries between 70 and 95 cents with at
least 60 seconds remaining, cancels unused quantity after a fill, and manages filled
inventory with evidence-based exits or settlement. Price is a market-implied probability, not an assertion
of fair value. Reports compare settled win rates with fee-adjusted break-even
rates in 70–79, 80–89 and 90–95 cent bands. This is a direct test of favorite bias
in 15-minute markets; the longer-market literature does not prove this strategy.

**Reset funds** is scoped to one folder, owner/CSRF protected and request-ID
idempotent. The worker archives that session, clears virtual positions/orders,
resets deposits/cash to $1,000 and P/L/fees/model evidence to zero, and checkpoints
the reset and command receipt atomically. Current cycles are halted until a new
market so pre-reset fills cannot reappear. Other portfolios retain their funds
and inventory. Archived session JSON remains available through Previous reset
sessions. A reset is never represented as an execution or trading gain.

Legacy summary time filters retain their behavior. New experiment cards label
current-session results rather than misrepresenting lifetime totals as hourly
returns. Separate portfolios are counterfactual experiments and must not be added
together as a claim that the same liquidity could support every strategy live.

## Risk exits for sequential pairs and favorites

Each new attempt allocates a configurable-policy test loss budget of the smaller
of $5 and 1% of that folder’s current virtual cash. This is an explicit experiment
risk limit, not an empirically optimal stop. Partial positions receive the
proportional budget. Loss is measured using actual executable depth net of
taker fees, compared with remaining acquisition cost including entry fees. A
breached budget latches an IOC exit; price gaps and unavailable liquidity can
exceed the intended limit. Missing depth is unknown, never a fictitious zero fill.

For evidence-driven exits, current state buckets use series, held-side bid and
time remaining. Only one label per market per bucket is trained after confirmed
settlement/attempt closure, with interrupted cycles excluded from evidence. A
bounded-recovery empirical Bernstein upper estimate is available after 30
markets. A position exits if its net executable sale value exceeds even that
upper continuation estimate. Favorites train on settlement payouts; sequential
pairs train on their actual net recovery proceeds under the defined completion
policy. These estimates are policy/regime-dependent, are not proven optimal,
and remain unknown during cold start. All monetary losses remain in accounting.
Complete sets already acquired in full retain coverage; only incomplete
packages are unwound. Session resets clear the evidence models as well as P/L.

## Weather favorites
High-Probability Favorites also includes eight hourly-weather series and seven daily-high-temperature series from the existing weather inventory. They share its current $1,000 session, contract sizing and 70–95¢ maker-entry / risk-exit rules; adding them does not reset the portfolio. Each series has its own bot, pause and size controls and outcome calibration. No forecast model or assumed favorite edge is introduced.

Weather discovery rotates through those series and their API pages, selecting active contracts closing within 24 hours. At most two hourly and two daily weather contracts are subscribed concurrently, alongside up to four complete-set legs, with twenty-two total active fee policies as the shared ceiling. Unfilled weather candidates rotate after five minutes; filled inventory remains managed until confirmed exchange settlement. Individual threshold contracts may have multiple winning outcomes across an event, so weather favorites never treats a collection of thresholds as a guaranteed complete set.

## Folder overview
The top table keeps current cash-plus-position balances visible and has one shared rolling P/L selector: All, 1h, 6h, 24h, 7d and 30d. All uses the current-session wallet P/L. Other windows compare minute equity snapshots and subtract changes in deposited funds. Missing valuations stay unavailable, and periods beginning before tracking or after a reset are labeled with their actual coverage. Snapshots are compact (all folders in one row per minute), retained for 35 days; session origins preserve reset boundaries. The overview is independent of bot search and version filters.

## Late-game sports favorites
Seven game/match winner series (NBA, NFL, NHL, MLB, college football, ATP and WTA) join Favorites without resetting its balance or history. New sports entries require linked exchange milestone metadata, a game that has started, an explicit live status with a provider update within 45 seconds, and 1–120 minutes until the market's expected expiration time. The market close timestamp is never used as a game-end estimate. This is a final-two-estimated-hours window, not a claim to know the actual remaining game duration; games lacking reliable timestamps are skipped. Closed, delayed, pregame, unknown and stale live states block entries. Unfilled entry bids expire with the live verification lease. Existing positions retain protective exits and confirmed settlement recovery.

Up to two sports contracts share the GET-only read budget alongside four weather contracts and four complete-set legs (ten extra subscriptions, twenty-two total active fee policies at admission). Filled inventory is preserved when candidates rotate.
