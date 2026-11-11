# MT-019 — Bounded owner history pages (hot raw + packed)

## Why

The original shadow dashboard only exposed the most recent 100 rows. The
new verified-R2 pointer reader in PR #201 protects those recent decisions,
but it does not make older Favorites evidence enumerable or support
sample-by-sample analytical continuity.

This PR adds **owner-authenticated, read-only, index-keyset pages** for two
independent *still-held-in-PostgreSQL* histories:

- `GET /demo/shadow/history/raw` pages through every existing
  `demo/shadow/event/` row, including non-diagnostic trading/settlement
  evidence. Returns at most **four original events** per request. When a
  selected row is a v2 R2 pointer, it invokes the independently gated
  four-object SHA/gzip/full-row reader, with no writes. Without separate R2
  READ credentials, it returns 503, **not misleading zero events**.
- `GET /demo/shadow/history/packed` pages through
  `demo/shadow/event-batch/` rows, one losslessly compressed PostgreSQL
  batch per request; each expands to at most 64 original diagnostic event
  IDs using the already SHA/size-validated batch decoder.

Both support optional `?cursor=demo/shadow/event/<key>` or
`?cursor=demo/shadow/event-batch/<key>` respectively; the cursor is
bounded and validated to the selected source namespace. The responses
include original `id`, key, parameters, progress and the event's original
`progress.time` when present. They return `more` and `next_cursor`, and
declare `order='idempotency_key_ascending'`: this is **key order**, not
event-time order. Clients must sort by `event_time` when studying outcomes.
Cursor traversal is not a repeatable-read snapshot if writers are active.

## Data completeness remains explicitly unproven

Every response carries:

- `reclaimed_manifests_included=false`
- `all_time_coverage_complete=false`

Older rows already **physically reclaimed to R2** are not returned by these
two PostgreSQL source endpoints. Those still require the separately
owner-gated, read-only
`GET /demo/shadow/archives` and
`GET /demo/shadow/archives/{manifest_id}` paths, including manifest/packed
R2 verification. Future work must join all four sources by original event
ID, deduplicate and reconcile statistics with full historical coverage.

The endpoints perform no SQL UPDATE/DELETE, R2 PUT or trading operation.
Every PostgreSQL source page is a bounded indexed range query with a
five-second SQL statement limit; no `OFFSET` scans, `COUNT(*)` table scans,
arbitrary SQL, or unbounded R2 enumeration. On invalid cursors return 422;
unavailable/corrupt cold R2 or compressed batch returns a sanitized 503
instead of partial results. Normal hot-only raw history uses **zero R2**.

Disposable PostgreSQL regression tests page through eleven original raw
events including a protected settlement and three compressed diagnostic
batches containing six original event IDs. They assert no duplicates,
no omissions, correct keyset continuity, source preservation, namespace
validation, owner/proxy boundaries and fail-closed disabled cold history.

**Do not enable automatic archiving or trading** as a result of this PR.
The P0 archive-history acceptance issue #196 remains open until unified,
verified, paginated hot/packed/R2-pointer/reclaimed-manifest history and
Favorites learning-statistics totals are complete and tested, and the
Render physical disk/WAL, restricted role and credential rotation gates
are independently satisfied.
