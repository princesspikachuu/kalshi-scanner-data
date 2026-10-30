# Live paper trading: operation and service limits

Checked October 29, 2026. This system uses live Kalshi market data and simulated
money. It never places exchange orders. Historical replay remains separate.

## How to use it

Open **Live paper trading** from the statistics table or historical paper page.
Choose saved table strategies, a starting paper balance, and a fill model, then
start an account. It runs while the browser is closed. Only one account runs at
a time; its strategies share funds across categories.

The page shows the immutable setup, available cash, cash reserved by unfilled
bids, filled positions at cost, realized P/L, feed health, and order activity.
Prices and profits are before fees, as requested. The saved research yield is
an in-sample priority statistic, not a forecast of live returns.

**Conservative** needs an observed opposite-side trade through the bid.
**Estimated** also permits qualifying trades at the bid. Both share each trade's
volume across orders and include a two-second placement delay. Neither knows
actual queue position. **Optimistic** assumes every qualifying bid fills and is
explicitly labeled an assumption. A stop sale uses the observed bid and available
displayed size; unknown size does not become an invented fill.

Stop cancels unfilled bids immediately and prevents new bids. Filled positions
remain monitored until settlement. A projected close cancels bids but does not
credit winnings: a confirmed settled result is required.

## Limits and the approach implemented

| Service | Relevant limit or observation | Protection |
|---|---|---|
| Kalshi REST | Basic has 200 read tokens/second. Most calls cost 10 tokens, equivalent to 20 normal reads/second; actual costs and allowance come from the account endpoints. | Live discovery and collection use the same existing database rate limiter, currently targeting 90% of verified allowance. Live discovery makes at most one request every two seconds, and waits when the shared budget is busy. |
| Kalshi streaming | Basic allows 200 concurrent connections per user across Predictions and Perps. Subscription overflow, market-count and command-rate errors are also documented. | One connection, ticker/trade channels filtered to at most 100 selected markets, plus lifecycle notifications. Subscription commands are spaced by at least one second. Errors reduce the watch set or trigger backoff; no extra keys or accounts are used. |
| Render collection worker | Existing service: 0.5 CPU, 512 MiB RAM. Before this release, recent five-minute memory samples were about 293–366 MiB. These samples do not prove peak safety under live load. | Live feed is a small separate thread in the authenticated collection service. No historical evidence is downloaded into this lane. Socket queue is 16 frames, each capped at 256 KiB, compression disabled. Catalog, watchlist, orders, positions and recent activity are bounded. |
| Render paper worker | Existing separate 0.5 CPU, 512 MiB service. Large historical replay previously exhausted RAM. | Historical replay stays on that service. Live paper does not wait behind historical replay and does not share its dataset expansion. No additional service or compute upgrade is required for this release. |
| Render Postgres | Current 1 GiB compute plan supports 100 connections. Recent observed usage was 7–11. | Existing configured application pools total at most 11 connections: API 5, collector 4, paper worker 2. Live uses the collector pool. Transactions are short, idle heartbeats avoid unnecessary ledger rewrites, and no network calls occur inside ledger transactions. Deploy overlap and operator connections still need headroom. |
| Cloudflare Workers | If the account is on Free: 100,000 dynamic requests/day, 10 ms CPU/request, 128 MB memory. Billing plan and current account-wide usage were not verified. | Gateway only proxies bounded control/status requests; it does not run the feed or simulation. The new page makes at most two regular status requests per 10 seconds while visible, about 17,280/day for one continuously visible page; it pauses while hidden and backs off to 60 seconds on errors. Multiple pages and other Workers share the account allowance. |
| Cloudflare R2 | Object operations and storage have independent quotas; public r2.dev access has separate throttling. | Live operation does not use R2 at all. Historical data remains on the existing authenticated storage path. No polling or overwrite of one R2 object per market tick. |
| GitHub Actions | Build-time concurrency and included minutes depend on the account plan; account-wide balance was not verified. | Actions test and deploy code only. Live paper continues on Render after deployment and does not trigger a workflow for every market or trade. |

Sources: [Kalshi rate limits](https://docs.kalshi.com/getting_started/rate_limits),
[streaming protocol](https://docs.kalshi.com/websockets/websocket-connection),
[authentication and endpoints](https://docs.kalshi.com/getting_started/quick_start_websockets),
[trade feed](https://docs.kalshi.com/websockets/public-trades),
[ticker feed](https://docs.kalshi.com/websockets/market-ticker),
[Render database limits](https://render.com/docs/postgresql-creating-connecting),
[Cloudflare Worker limits](https://developers.cloudflare.com/workers/platform/limits/),
[R2 limits](https://developers.cloudflare.com/r2/platform/limits/).

## Recovery and bounded operation

- One active account and a 30-second database lease prevent two workers from
  spending the same simulated funds. Every checkpoint checks the lease token;
  a replaced worker cannot publish late changes. Restarts do not reset cash.
- Cash changes, orders, positions and audit events are committed together.
  Audit history is paginated in batches of 50; recent cards show 40 events.
  Price ticks are not accumulated as historical evidence.
- Network interruption or a sequence gap cancels unfilled simulated bids and
  clears cached quotes. Filled positions survive. Missing trades are not
  retroactively invented. Live results can therefore differ from uninterrupted
  trading, and every interruption is visible.
- Only quotes no older than 10 seconds can support entries or stop estimates.
  Reconnect waits grow from 2 to 60 seconds with jitter; a full clean minute is
  required before resetting the delay. REST 429s reduce the shared read pace.
- Default capacity is 20 saved strategies, 100 watched markets, 100 unfilled
  orders and 200 filled position records. Selection favors held markets, then
  saved statistical yield and nearer closing times. This is a selected market
  set, not exhaustive exchange coverage. Capacity protection is shown on screen.
- After 10,000 bids, an account stops opening new bids and drains through
  expiry/settlement. Start a fresh account afterward. Audit storage grows with
  actual paper actions; long-term retention and database storage should be
  reviewed before running many accounts indefinitely.
- The event cap includes pending reservations and filled cost for every
  contract in that event. Already-filled positions are not sold just to fund a
  higher-yield opportunity.

## Validation and practical limits

Tests cover money conservation, shared volume, partial fills, event caps,
cross-category priority, stop depth, stale data, gaps, idempotent starts,
owner/CSRF boundaries, restart recovery, old-worker fencing, audit pagination,
and stopping while positions remain open. Integration checks use disposable
PostgreSQL. A read-only hosted probe verifies a real streaming handshake and
fresh ticker without starting an account or sending any exchange order.

No service can guarantee uninterrupted market data. These protections prevent
quota errors or restarts from silently resetting balances or producing assumed
fills. An extended live soak and comparison against actual executable queue
behavior remain necessary before using these estimates to judge profitability.
