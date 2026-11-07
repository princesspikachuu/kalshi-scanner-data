# 28-market production shadow deployment

This integrates the standalone convexity strategy and frictional execution model into the existing single fenced trading worker. The DEMO entry redirects to `/shadow` once the one-time migration completes. The original bot records, previous paper wallet and exchange Demo history remain readable through `/bots?history=1`; current shadow results use their own namespace and versions.

The 28 profile families come from the existing market registry. Each has a separate strategy instance and state; feed subscriptions, trade-volume budgets and virtual cash are shared. LIVE bots remain paused. No real order-routing method exists in the new engine. The initial **virtual** bankroll is $1,000, enabling 28 paired 100-contract 10-cent quotes without claiming to allocate real funds.

Worker startup pauses old paper entries and cancels their resting virtual orders. An old paper position prevents handover until the old executor closes or settles it. A completed handover is idempotent and logs `shadow_cohort_initialized` with `bots: 28` and `real_orders_enabled: false`. If the production Read key has not been connected, the verified expected state is `shadow_connection_required`; deployment does not imply fills or an active authenticated feed.

Hosted checkpoints and all audit rows for each bounded input batch commit in a single PostgreSQL transaction. Batches preserve receipt order and every event's cash value, take at most 32 inputs and stop adding inputs after 5 milliseconds of processing, and flush before waiting for another input. Backpressure cannot reorder producer timestamps. Restarts retain cash, inventory, lot arming flags, versions and RNG state, cancel uncertain virtual submissions, and exclude interrupted cycles. Completed execution state is removed from the hot checkpoint after its durable report is saved. No per-tick database history is written. Existing monitoring, verified archive and backup facilities remain in use; shadow mutable state and bot controls are included in backups. Failed archive verification retains original records.

The standalone core still provides full event capture/replay for local tests. The hosted worker stores trading audit and reports, **not every raw L2/spot update**; the local replay workflow must be used to capture a complete replay tape. Browser CSV exports explicitly identify the shown latest 100 audit rows rather than claiming to export all history.

Known modeling assumptions: 150ms configured action latency; FIFO estimated from public L2 and subsequent matching prints; volume-bounded trade-through and probabilistic toxic-fill stress; depth-limited IOC with partial/unfilled remainder; current verified series/event fee schedules and centicent rounding. BTC remains a shared external stress proxy, not a calibrated native spot feed for the other assets. No IOC fill guarantee or exact hidden-queue reconstruction is claimed. Win-rate and PnL analysis excludes incomplete-data cycles; the virtual wallet still retains all simulated cash flows.

Owner-authenticated API paths `/demo/shadow/workspace`, `/events`, `/bots/{asset}`, `/bulk`, and `/funds` retain the existing gateway and CSRF controls. Settings changes increment the bot revision and stop new entries in the current cycle; existing inventory continues its original policy. Lifetime, 1h, 6h and 24h buttons require no dropdown. Prior versions remain available via the full-history checkbox. Virtual refill request IDs are idempotent and commit with wallet state.

Validation includes the existing API/browser suites plus pure execution/replay tests and actual-PostgreSQL rollout, metrics, refill and authorization cases. Deployment must follow a passing hosted PostgreSQL run. Verify API readiness and worker fence acquisition after Render reports live, and retain the real-source frontend deployment receipt. Do not enter keys or activate real trading during deployment verification.

Favorites maker entry policy (v2): initial purchases remain strictly post-only;
there is no automatic taker fallback. Each bid expires within 15 seconds and is
reassessed inside the original maximum 60-second entry window, with earlier
sports-verification and market-close cutoffs. Replacements wait for the previous
order to become terminal, never bid above the original entry ceiling, and stop
after any fill. Stale/invalid data, ineligible live status, changed fees or an
insufficient value estimate cancel the outstanding entry. Cancellation still has
modeled latency, so fills racing a cancellation remain possible and accounted for.

Entry evidence is learned only from filled trials with confirmed settlement and
valid data, separately by series, side, 5-cent bid bucket and remaining-time band.
At most 500 recent event outcomes are retained per cell; correlated thresholds
from one event count once, keeping the adverse outcome if they disagree. Starting
at 30 distinct events, a Wilson lower estimate must cover actual maker fees plus
a default 2-cent uncertainty buffer. This is an exploratory historical estimate,
not an independent forecast or an out-of-sample proof of profitability. With less
evidence, the bot joins the bid with one clearly labeled demo contract; profile
`paper_exploration: false` disables these trials. Existing balances, inventory,
exits, settled history and paused controls are preserved. Evidence shares the
existing durable checkpoint and is cleared by an explicit session reset.

Favorites activity/recovery update: valid maker bids now retain their queue
position. Each fresh value/fee/eligibility check renews a maximum 30-second safety
lease, bounded by the final-minute cutoff and current sports verification. If
checks stop, the lease expires. Cancelled/expired unfilled attempts can retry when
conditions recover, beyond the former one-minute lifetime; replacements retain
the original price ceiling. Any fill still ends entry accumulation for that market.

A fresh full book snapshot may restore current entry eligibility after a gap;
previous gap flags, cash flows and exclusions remain unchanged, and gap-affected
history is not used to train entry estimates. Restart-only halts may be cleared
after verification, while explicit halts, pause state and session-reset guards
remain effective. An ordinary delta or heartbeat cannot restore eligibility.

Shared discovery supports up to 12 hourly-price, 8 hourly-weather, 7 daily-weather
and 4 sports candidates. Owned markets retain subscriptions without consuming
candidate slots. Discovery prioritizes unrepresented series; idle unfilled
candidates rotate after five minutes while active maker orders keep their queue.
All experiments share a maximum 48 extra/64 total subscription budget. Requests
still use the existing provider pacing, fee TTL and verified live-sports rules.
Per-event fee checks cover only the affected market and due actions; clock sweeps
retain the full check. The idle clock runs at 10 Hz instead of 20 Hz; incoming
feed events still advance due actions in causal receipt order.
