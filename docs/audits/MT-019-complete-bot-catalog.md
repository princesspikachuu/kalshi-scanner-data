# Complete bot controls at startup, refresh and workspace read

The worker and workspace API previously fetched at most 800 bot controls and
treated that result as the entire catalog. The query orders by UUID, so an
overflow can silently omit controls in any strategy. Startup can then miss
saved strategy state, control refresh can miss pauses, and workspace results
can omit bots.

All three paths now share `bot_catalog.load_bots`. It uses one SQL statement
with a 4,096-control capacity plus one overflow sentinel. The SQL read follows
the namespace key index instead of ordering the sparse namespace by UUID;
sorting the bounded result locally preserves the former consumer order without
a potential walk of the unrelated job primary key. Every returned paused
and retired control remains available for state restoration and UI history.
No controls, strategy state or historical records are deleted or rewritten.

An overflow raises before the caller consumes a partial catalog; the workspace
returns HTTP 503. A database failure also propagates instead of becoming an
empty catalog. The existing `BOT_LIMIT` import remains compatible. This change
does not alter desired strategy states or increase exchange requests by itself.
Monitoring after restart should include the cost of complete control reads.

Regression fixtures exceed the old limit and verify tail controls and saved
pauses survive. They also cover empty/exact-capacity catalogs, overflow and
source errors. Full PostgreSQL CI verifies the shared worker/API integration.
