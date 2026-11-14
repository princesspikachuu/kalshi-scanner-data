# MT-019 — Read historic diagnostics after R2 archival

Archived paper diagnostic rows stay in Cloudflare R2 with PostgreSQL manifests.
The owner API now supports **bounded, authenticated, verify-on-read cold history**.
No changes to execution, cash, orders, trade statistics or retention policy.

## Endpoints (owner session required)

- `GET /demo/shadow/archives?limit=10` — metadata-only index page from existing PostgreSQL manifests. Returns `manifest_id`, archival kind (`raw`/`packed`), source row count, **original** diagnostic event count, time span and a cursor. Max 25 manifests per page. `next_cursor` may be supplied as `cursor`; ordering is the stable index key order, **not chronological**. This metadata route does not access R2.
- `GET /demo/shadow/archives/{manifest_id}?offset=0&limit=25` — one manifest only, max 50 original events per response. Validates R2 object bytes, SHA-256, expected row IDs, event UUIDs and allowed non-financial types before returning original `id`, `key`, `parameters`, `progress` and timestamp. For compressed diagnostic batches, the original events are losslessly expanded in stored sequence. Returns `verified=true` **only after** full manifest readback. No direct R2 links or secrets are emitted.

## Activation gate

The metadata route is available after API deployment with no new secrets.
**The R2 reader is disabled by default.** Enabling requires the following
settings on the API service, not the trading/research worker:

- `MT_ARCHIVE_READ_ENABLED=true`
- `R2_ACCOUNT_ID` and `R2_BUCKET` (same existing private bucket)
- `R2_READ_ACCESS_KEY_ID` and `R2_READ_SECRET_ACCESS_KEY`

Issue a dedicated *read-only* R2 token scoped to the archive bucket. Do
**not** reuse the worker's read/write R2 token for the public-facing API;
requests remain authenticated through the existing proxy and owner session.

The reader creates an R2 client only for a requested manifest page, validates
it and closes the client. Missing reader configuration returns 503. A missing
manifest returns 404; a bad cursor, UUID or page size returns 422. Invalid
R2 data or failed checksum returns 503 without leaking SDK exception details.

## Safety and remaining work

- This is a browsing/restore endpoint for known immutable manifest chunks, **not
  an unbounded search across every event or an automatic reingestion**. A
  time-indexed archive catalog and statistics read-through still require design.
- Normal live trading event views remain PostgreSQL-only for current events.
  Historical diagnostics live under the new explicit cold archive endpoints.
- Current raw and packed archivers still require an operator-only maintenance
  role for deletion. Merely enabling this reader **does not** start automatic
  archival, reconnect market feeds, or resume the trading worker.
- Historical financial events (`FILL`, `SETTLED`, orders and reports) are
  never archived by the diagnostic cleanup tools; they remain in PostgreSQL.
