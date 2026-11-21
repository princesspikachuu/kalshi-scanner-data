# Active worker data-handling audit

Date: November 7, 2026 (America/Los_Angeles). Scope: production-data paper worker; no real exchange orders or infrastructure upgrades.

## Baseline evidence

The active worker has 0.5 CPU and 512 MiB memory. Render samples did not establish CPU or memory saturation. Worker logs continued to show intermittent queues of thousands of inputs, stale book rejections and discovery admission pauses. At 4:19 PM, the queue was approximately 4,900 messages, with a 3.1 second recent p95 queue delay and no REST cooldown. This is an execution/data-flow problem, not evidence that a paid upgrade is required.

## Findings and changes

| Finding | Effect on trading | Change |
| --- | --- | --- |
| Audit/checkpoint writes run synchronously on the socket event loop | Database waits prevent price frames and pongs from being received promptly; frames may already be stale when received | Prepare immutable audit batches on the execution task; perform fenced, atomic database writes off the event loop |
| Control/configuration and status SQL shares the same loop | Periodic dashboard and configuration work interrupts feed reception | Run SQL I/O off the event loop; fetch read-only mode/profiles concurrently outside the execution lock |
| Making persistence asynchronous without serialization would race controls and wallet changes | Potential duplicate commands or checkpoints inconsistent with audit events | One execution lock covers mutations and durable commits; command reads remain inside it; do not acknowledge inputs before commit |
| Cancelling a thread-backed database wait does not stop its thread | A write could finish after shutdown released state or wrote another checkpoint | Shield and await database completion, including repeated cancellation, before releasing the execution lock |
| BTC spot stream runs while all legacy consumers are paused and empty | Unneeded messages and risk evaluation consume execution capacity | Connect only while a legacy bot, position or outstanding order needs the stream; reconnect when needed |
| BTC spot disconnect invalidates unrelated Kalshi strategy books | Favorites and spread strategies lose usable data despite an intact Kalshi feed | Scope the spot disconnect to the legacy spot-dependent engine |
| Global health depends on the paused legacy engine's BTC spot readiness | Dashboard can say waiting while Favorites has fresh usable books | With no legacy spot consumer, report readiness from active strategy books |
| Existing load telemetry blends simulation, persistence and receive stalls | Hard to choose effective improvements or justify compute spending | Add bounded `shadow_pipeline_cost` summaries for source counts, simulation/commit time, latest checkpoint/SQL time, control duration, queue delay and event-loop lag |

## Execution properties preserved

All book deltas and trade prints stay in receipt order. No synthetic fills, relaxed fee validation, bypassed freshness checks or increased risk limits. Wallet/checkpoint, event rows, reports and refill completion remain one database transaction. Pause controls, recovery checks, real-trading disablement and the existing shared REST budget remain in effect. Paused portfolios with positions continue receiving protective data.

## Remaining priorities

Use live stage timings to identify the next measured bottleneck. A larger queue alone cannot improve trading. Do not increase subscription limits or buy compute based only on a backlog. Database latency, checkpoint size, incoming message mix and execution time must be distinguished. Report generation/reset commands still have synchronous exceptional paths; they should be changed only if live timings show a material contribution.

## Validation

Regression coverage includes socket intake during a blocked commit, exclusion of concurrent state mutation, ordered durable wallet snapshots, failed-write acknowledgment, repeated cancellation, transaction/refill-marker integrity, the hosted control loop, idle spot suppression and independent Kalshi book validity after a spot disconnect. Full suite and live verification are recorded in the change report.

## First live timing result and follow-up

After the asynchronous I/O deployment, one roughly 30-second sample processed 42,110 inputs in 836 batches, recorded 10,741 ms in simulation and about 2 ms in audit flush calls (few auditable state transitions in that interval), and rejected zero stale inputs. Source counts were dominated by 43,198 book deltas and 2,279 trade frames; no BTC spot inputs were recorded. Fresh books were visible for all nine legacy market tickers and 18 active strategy book copies. These samples demonstrate continued feed reception and correct spot suppression, but do not establish sustained throughput or a trade-rate improvement.

A queue still developed. The timing evidence identified remaining duplicate simulation: even with all legacy bots paused and no legacy exposure or outstanding orders, the base engine still applied every book/trade frame before forwarding it to Favorites. The follow-up skips that base-engine application and fee preparation only while the base engine is idle. The complete frame still reaches active portfolios in receipt order. Lifecycle, clock, market discovery and settlement continue, and legacy resume clears obsolete sequence state and requires a fresh snapshot. Idle legacy books are excluded from the shared snapshot selector to prevent needless replacement requests. `legacy_inputs_skipped` measures the duplicate work removed.

## Recovery and data-quality qualifications

- Snapshot repair must target the current WebSocket subscription for a desired, subscribed market, even if its local book still carries an obsolete subscription ID after pause or reconnect. Requiring that stale ID to equal the new one can strand the book indefinitely. The recovery regression test now checks the repair request before any new snapshot has arrived.
- Paper execution still uses the configured 150 ms simulated order latency. It does not automatically add the worker's measured queue delay to every simulated order. Aggregate pipeline timings are operational evidence, not proof that every paper fill would be achievable by a backlogged real-money worker. Per-order latency attribution is a further data-quality improvement.
- Current Favorites learning rejects whole cycles marked invalid. A market gap before a new, fully observed post-recovery entry can therefore suppress otherwise useful learning outcomes, even though financial reporting retains its trades. A future change should distinguish entry-window validity from earlier cycle history; it must not relabel missing history as valid.
- If several strategies are enabled together, each still applies its own book copy. A canonical shared market-data representation is a possible next optimization if measured simulation cost remains dominant. The current change removes only copies with no active trading intent or exposure.

## Follow-up resolution: worker delay and execution windows

The hosted paper executor now schedules order and cancel arrival at actual worker decision time plus the configured transport delay. Source timestamps remain unchanged, so processing an old queued input cannot backdate a new request into an earlier market book. Orders and fills retain decision time, measured worker delay, arrival time and an execution-model label. Offline replay keeps its configured fixed-latency behavior. Cohort metrics distinguish observed worker-delay quantities from older data with no such measurements.

Favorites now track execution-window quality from a verified entry request through exit or market close. An earlier cycle gap remains invalid in historical cycle metrics but does not poison a new clean execution window. A gap while orders/exposure remain active, or a restart during an open window, excludes execution/exit learning. Verified entry-price forecasts still use their fresh fill observation and authoritative final outcome independently of interim execution gaps. Financial results retain every trade. No prior unknown window is backfilled as verified.

Liquidation and IOC depth traversal now calculate only needed levels. Price ordering is cached until price membership changes; quantity changes and hypothetical depth-use overlays are read fresh. This avoids sorting and evaluating an entire book for every position check while preserving price priority, fees, partial fills and shadow depth accounting. Burst telemetry remains the measure of live throughput; this optimization is not a guarantee of zero queues under every feed load.

## Root cause of residual multi-second stalls

The shared REST limiter's `wait()` held its threading lock while sleeping for the next read slot. The trading consumer, discovery admission checks and fee maintenance synchronously call `remaining()`, which acquires the same lock. Contending REST threads could therefore make the supposedly cheap cooldown read block the entire event loop for several pacing intervals, even with low measured simulation and database time.

The limiter now holds its lock only while checking cooldown and claiming a read slot. It sleeps outside the lock, then rechecks both slot eligibility and newly imposed cooldowns. The configured three-reads-per-second pacing remains unchanged. Rate-limit rejection can be applied immediately while other callers sleep. A regression holds a REST waiter asleep and verifies that cooldown updates/reads finish before that waiter is released, and that the sleeping request then rejects the newly imposed cooldown.

A bounded independent loop watchdog records only code locations, GC timings and CPU counters if a stall exceeds one second. It records no frame locals, provider bodies or credentials and makes no trading decisions.
