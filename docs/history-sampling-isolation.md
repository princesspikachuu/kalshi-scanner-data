# Reporting timeout isolation

On November 8, 2026 at 17:21:09 UTC, the live worker logged `trading_router_recovery` with `QueryCanceled` from `record_bot_balances`. Its subsequent pipeline counters reset and all strategy books had to recover. The report-history aggregate ran inside the execution mutex, so even a nonfatal slow query delayed market inputs.

Minute history sampling now freezes a small reporting projection while holding the state mutex, publishes current status through the existing fenced path, then performs history database work outside that mutex. The projection contains monetary snapshots and per-bot research totals; it omits detailed research cells. It cannot mutate execution state and cannot incorporate future fills.

Only a statement timeout (`QueryCanceled`) in those two reporting operations is deferred. It records `paper_history_sample_deferred`, does not mark the missing bot-history sample complete, and waits 30 seconds before a new bounded attempt. The minute sampler still has only one in-flight operation; it creates no accumulating background task or queue. Delayed history is reported as missing rather than fabricated. Existing historical records and their first-observation semantics are preserved.

Financial checkpoint/order/audit writes, ownership fencing, unexpected exceptions and coroutine cancellation retain their original failure behavior. Status publication remains serialized and fenced. The maximum database connection count is unchanged, and reporting uses no market-data API calls. This addresses host resets and mutex stalls; it does not claim to eliminate the cost of the underlying historical aggregate query.
