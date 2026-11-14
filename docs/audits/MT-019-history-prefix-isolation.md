# MT-019 — Exact diagnostic key namespaces

Owner-only raw and packed history listing previously used bounded keyset
inequalities against two adjacent prefixes:
`demo/shadow/event/` and `demo/shadow/event-batch/`.

Some PostgreSQL collations can compare punctuation differently from raw
bytewise Python comparisons, so a prefix range is not itself a proof that
all returned keys have the intended prefix. The source SQL now also requires
`idempotency_key LIKE %s`, with the fixed source prefix plus `%` supplied
as a bound parameter. Neither prefix contains wildcard characters.

The original index range, ORDER BY, strict request cursor validation, small
limits, PostgreSQL read-only transaction, and all original event data
remain unchanged. This fix adds no SQL queries and no R2 requests. A
disposable PostgreSQL integration test inserts raw and packed records
together and verifies that each endpoint returns only the intended originals,
including across raw-page boundaries.

This is still not a globally stable database snapshot or a complete R2
manifest archive. The endpoints remain owner-only and report
`all_time_coverage_complete=false`. No collection, trading, archival or
restore action is activated.
