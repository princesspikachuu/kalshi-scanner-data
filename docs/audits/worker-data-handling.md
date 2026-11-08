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
