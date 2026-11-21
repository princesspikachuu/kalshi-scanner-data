# Durable burst throughput

The owner approved one 1-CPU / 2-GB paper worker at $25/month. No additional instances or further paid capacity are configured.

Live measurements after the upgrade still showed roughly 100 ms for snapshot preparation and 120 ms for database writes on dirty batches. The existing 256-input / 40-ms burst budget repeatedly paid that cost before draining a busy feed. Under sustained load, entries and discovery paused while protective exits continued through the queue.

Busy queues use a 512-input / 80-ms simulation budget. Backlogs above 2,000 queued inputs use a bounded 1,024-input / 160-ms tier to amortize the measured checkpoint cost further. The low-load budget remains 128 inputs / 20 ms. The time check occurs after each input, so one indivisible input can exceed the time boundary. Sockets and controls regain the event loop between committed batches. Database latency remains observable and may exceed the simulation budget.

Every book update and trade retains its original order and timestamp. Each completed batch is durably committed before queue acknowledgments. Failed commits leave inputs unacknowledged and retain the existing abort/recovery behavior. The existing 20,000-input queue cap, admission thresholds, fees, capital limits and fill models are unchanged. The larger batch bounds transient in-memory audit buffering to at most 1,024 incoming inputs, within the approved 2-GB worker budget.

All scalper and maker portfolios read the same resource-admission decision for an input. Pause/resume flags propagate only when that decision changes, preserving immediate risk-gate transitions without hundreds of repeated assignments on each unchanged delta. New/rebuilt fleets receive the current flag on their first input.

Tests verify FIFO ordering, socket fairness, the time budget, unacknowledged failed commits, shared admission reads, immediate pause/resume transitions, and protective exit behavior. This is throughput work, not relaxed trading criteria or automatic strategy optimization.

Resource admission uses current wall-clock time, matching the wall-clock timestamps recorded by monitoring after each durable commit. Using a queued market observation timestamp falsely made newer monitoring samples look invalid (negative sample age), pausing entries even while operational metrics were healthy. Market features and execution ordering continue to use their original observation timestamps; this change supplies no later market information to strategy signals. Stale and overloaded telemetry still block entries at the same limits.
