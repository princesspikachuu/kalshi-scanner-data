# Production-data paper execution

This release replaces the DEMO page's exchange-demo executor with a local,
durable paper ledger. It has not been published or deployed yet.

The existing single trading worker and exclusive fence remain in use. DEMO
selects `DEMO_ENGINE=production_paper` by default, while LIVE continues to use
its separate executor. Production paper HTTP requests are GET-only and have a
fixed market-data allowlist. Portfolio requests read the virtual ledger and
never reach Kalshi. Its WebSocket subscribes to books, public trades and market
lifecycle messages, not real account orders or fills. A production Read key is
required for the authenticated stream and is encrypted separately from LIVE keys.

Bot strategy and time-window rules are reused. Maker orders that cross the book
are rejected. Otherwise, later matching-aggressor public trades consume visible
queue depth and a shared volume budget across all simulated orders. Partial
contracts, duplicate messages, cancellation races, and an additional modeled
250 ms request delay are supported. Feed gaps stop fills, and a new snapshot
restores a conservative queue estimate. Hidden depth, exact priority and the
market impact of hypothetical orders remain unobservable. These are estimates,
not exchange-confirmed fills. Immediate depth-walking math is covered separately;
the current bot executor remains maker-only.

Fees use Decimal arithmetic, verified series/event schedules and the current
published centicent rounding of fee plus position cost. Unknown schedules pause
fills. Virtual deposits update cash and their cash-flow event atomically and do
not count as account profit. Production settlement metadata settles each virtual
position once. Cash, receipts, queue changes, fees and fills commit together.

The fenced transition cancels only owned, resting Kalshi Demo bids, verifies
their cancellation, and atomically moves old records under `kalshi-demo/`.
Existing configurations become fresh versions under `demo/`, with a starting
virtual bankroll equal to the last reported Demo equity. Old mock positions are
preserved in history; this release does not continue managing the retired Demo
exchange account. Previous records are owner-readable through `/demo/legacy`.
No real portfolio funds are transferred or used.

Local validation: 584 backend checks and 108 Node checks passed. 209 database
checks, including 11 new ledger/transition cases, require hosted PostgreSQL CI.
The desktop preview uses labeled sample data. API, worker and gateway deployment
must wait until the complete hosted test suite passes.

The user authorized publishing this release to the existing public repository
princesspikachuu/kalshi-scanner-data and deployment after database checks pass.
The target branch is build/google-auth-foundation (existing draft PR 9).

Publish the complete final local tree, run the PostgreSQL workflow, fix any
failures, then deploy the API and existing single trading worker. Frontend
changes deploy through the branch's existing workflow. Verify migration,
readiness, and the new worker's actual fence ownership; without a production
Read key the expected state is connection_required, with no simulated or real
execution until the data feed is verified. Do not enter real keys or place live
trades on the user's behalf.
