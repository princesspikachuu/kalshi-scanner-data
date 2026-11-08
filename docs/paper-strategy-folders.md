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

## Updated market scope
Favorites retires its 28 fifteen-minute profiles from new entries. Their records remain in a collapsed retired section, with the same wallet, history, risk exits and settlement handling. Resume controls cannot reactivate retired entries. Its new 25 one-hour price-series profiles cover verified hourly crypto, commodity, FX, index and yield listings; discovery rechecks exchange frequency and restricts candidates to the final hour before close. Two hourly price contracts share the feed budget.

Sequential keeps its fifteen-minute profiles and adds the same eight hourly-weather, seven daily-weather and seven sports series as Favorites. A single weather/sports subscription is shared by both independent portfolios. Sports entry gates differ: Sequential can initiate pairs throughout verified live play, including overtime; Favorites still requires the final two estimated hours. Pregame, finished, stale and unverified states block new pairs. Sequential's initial sports bids expire with their live-data verification; after a first fill, exact residual hedges and protective exits continue, with at most a one-hour completion deadline per sports trial.

The shared admission ceiling is now twelve additional subscriptions / twenty-four active fee policies: four weather contracts, two sports contracts, two hourly-price contracts and up to four complete-set legs. Subscriptions for owned positions are retained. Portfolio resets are not part of this update.

## Compact summaries and incomplete quotes
Strategy folders start collapsed and keep their open/closed state across polling and page reloads. Each summary shows current balance, selected-period P/L and full-folder running counts. Folder time buttons select a local period; the master buttons set every folder back to the shared period. On mobile, the master table becomes stacked cards so names, balances and P/L fit without horizontal scrolling.

Period P/L now supports valuation bounds when a position lacks a quote, matching the All view. Minute samples retain equity lower/upper bounds and cumulative realized P/L; period bounds subtract added funds and remain within the current reset session. Older unpriced snapshots did not retain enough information for reconstruction: when necessary, coverage starts at the first new bounded snapshot and is explicitly labeled. No balances, trades, histories or reset sessions are rewritten.

### Sequential comparison

The original sequential wallet becomes **Sequential Spread · Baseline**, with its identifiers, balance, history and policy preserved. Two additional virtual accounts start at $1,000: **Sequential Spread · Flexible Completion** and **Sequential Spread · Adaptive**. Profiles retain the same markets, sizing and desired running/paused state as their baseline counterparts. All three consume the same read-only feed, including whole-game verified live sports; no real orders or extra market subscriptions are introduced. The workspace supports up to 400 bot records (254 after this migration); the other gateway response limits are unchanged.

Flexible Completion keeps the original entries and initially copies the baseline's learned entry model into an independent model. After a first fill, it checks full residual executable depth and can submit a taker hedge above the original second bid. A quantity- and fee-aware limit must preserve at least 2 cents per remaining contract at submission. Cancellation acknowledgements precede replacement. Latency, missing depth and partial fills can still leave unmatched inventory; profit is never booked before actual simulated fills.

Adaptive also searches quotes relative to each side's current bid, including asymmetric pairs. Entry evidence pools comparable category/time/movement/quote-distance states and requires at least 60 observations plus a positive conservative bounded-return score before larger sizing. Until then it rotates one-contract paper exploration. Continuation states include category, time remaining, held side, movement since first fill, spread, book imbalance and queued hedge quantity. A bounded continuation estimate is compared to depth-qualified net sale proceeds. The deadline is experimental: 35% of remaining time, reduced by recent movement, bounded to 60–900 seconds and always before the original close-minus-30-second limit. Existing dollar loss budgets, freshness gates and settlement rules remain in place. First-fill states are sampled at most once per attempt/state, capped at 24; only finished feed-valid attempts train these estimates. They describe observed outcomes of this policy, not counterfactual or guaranteed profits.

The master summary includes a collapsible, mobile-friendly comparison panel. It measures new attempts since the comparison start and excludes earlier baseline attempts. It reports net marked P/L, realized P/L, completed/first-filled finished attempts, unmatched losses, average start-to-completion time, approximate committed dollar-hours (reserved bids plus position cost), profit per dollar-hour and maximum observed snapshot drawdown. Unpriced positions make net P/L unavailable and mark drawdown coverage incomplete. Data-gap trades stay in financial results. Separate resets restart that variant's comparison window; differences in available capital, pauses, resets and eligible opportunities can affect comparisons. No variant is labeled profitable from this initial implementation; later events provide prospective evaluation.

### Monitoring and entry-search capacity

Position monitoring and entry-search allocation are now separate. Filled inventory, protective exits and verified live games awaiting the late Favorites window retain their subscriptions and do not consume category entry-search slots. They still count toward total monitored-market admission; existing exposure is never evicted when the ceiling is reached or reduced. Pending entry orders also prevent rotation until they expire or cancel.

The admission controller starts with 32 total targets, 12 entry candidates, and two entry candidates per weather/hourly/sports category (four complete-set legs). After each two minutes of continuously measured healthy processing it can grow to 40/16/3, then 48/20/4. Fresh measurements are required: a telemetry gap over ten seconds resets growth and stale telemetry prevents admission. Queue depth above 250, recent 95th-percentile processing lag above two seconds, per-input processing cost above 100 ms, or an active production-read cooldown pauses new discovery and resets expansion. Growth requires queue depth at most 50, lag below 0.5 seconds, and cost below 20 ms. These are conservative application settings, not exchange-imposed subscription limits. The shared three-REST-reads/second ceiling is unchanged.

External candidates with no position, protective order, active entry order or protected late-game interest rotate out after two minutes. A durable exclusion prevents selecting the same candidate again until its market closes. Empty candidates are compacted using existing history counters; flat previously filled attempts retain their financial and settlement evidence. Authoritative settlement recovery also visits parked markets. No account reset, position transfer or trade-history rewrite occurs.

The dashboard's Market monitoring panel and `paper_monitoring_capacity` logs show protected monitoring, entry candidates by category, total targets versus current admission ceiling, backlog, processing lag, rotated candidates, and admission status. Counts describe desired monitoring targets; WebSocket acknowledgement and quote freshness remain separately enforced by the feed engine.

### Individual bot P/L windows

Every bot, including experimental strategies, has independent All, 1h, 6h, 24h, 7d and 30d P/L controls in its collapsed market summary. The choice persists separately from the folder and master controls. Total P/L includes realized profit plus open-position value changes; each selected window shows the change in total, realized and unrealized P/L, after fees. Financial P/L includes all bot revisions and data-gap trades. Other trading statistics remain explicitly labeled as the full available period and follow their existing version filter.

The worker records compressed per-minute bot balance observations continuously, with owner-dashboard observations providing an initial fallback. Compression keeps the expanded workspace compact; minute history retains 35 days, with a small starting observation preserved per folder session. No share of folder cash is assigned to an individual bot. Existing cumulative P/L is preserved; new historical windows start with the first available bot observation and are labeled partial. Missing cutoffs or valuations are shown as unavailable or bounded ranges, never invented past values or zero losses. Reset sessions are kept separate.

### Favorites: actual entry price and event horizon

Favorites research now groups each actual maker fill by its own series, side, paid cent price and time remaining at purchase: <3m, 3–5m, 5–10m, 10–15m, 15–30m, 30–60m, 1–2h and >=2h. Daily weather, hourly weather, 15-minute prices, hourly prices and sports retain separate series evidence; there is no cross-market-type pooling. For sports, the estimated game end is explicitly distinguished from the legal market-close deadline, and both remaining times are stored. A fill ten minutes before close is never attributed to a bid's original one-hour horizon.

The new `entry-v2` calibration keys use actual cent prices and the event-time clock. Existing coarse submission-time keys remain in saved history but are not borrowed as matching new evidence. Explicit calibrated-maker mode checks its exact price/time cell after all fees and the existing edge buffer. Paper exploration continues using configured sizes and collecting unknown/weak states; no new confidence gate restricts it.

Entry cohorts persist through partial fills, exits, settlement and restarts. The dashboard's Entry price × time remaining cards show purchased/open quantities, distinct verified outcome events, conservative event win rate, fee-adjusted entry break-even, actual realized P/L, average holding time and net profit per dollar-hour committed. Financial P/L includes protective exits and entry/exit fees, allocated FIFO and proportionately across partial closes. Economically identical partial fills at the same timestamp are compacted; fills at different times or with different fee-per-contract costs remain separate for exact FIFO attribution; individual execution audits remain available. Outcomes require authoritative settlement, and forecast samples require fresh verified entry observations. Earlier pre-entry feed gaps do not erase a later verified entry/outcome pair; unverified entry fills remain in financial results but do not train forecasts. Multiple contracts or thresholds from one event do not inflate independent event counts.

Previously held inventory with no actual timing cohort is kept in the wallet and excluded from the new timing attribution. No old timestamp is guessed, no account is reset, and an early sample is not presented as an established profitable entry rule. The old price-only display is superseded once actual timing cohorts exist for a bot.
