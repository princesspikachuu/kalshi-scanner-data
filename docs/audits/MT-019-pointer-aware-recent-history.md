# MT-019 — Verified v2 cold-event readback for recent Favorites history

This is a **default-OFF** visibility safeguard for P0 issue #196. The existing
`GET /demo/shadow/events` previously read only PostgreSQL `progress` and
packed hot event-batches. With the newly versioned legacy archiver, an eligible
older `demo/shadow/event/` row may contain a `progress.archive` pointer
instead of its original Favorites decision. Returning that pointer as an
event would silently hide useful training/decision evidence.

## Behavior

- When the latest 100 raw shadow events contain **no archive pointers**, the
  endpoint behaves as before and makes **zero** calls to R2.
- If a pointer is present, the API must separately have
  `MT_ARCHIVE_V2_POINTER_READ_ENABLED=true`, plus
  `MT_ARCHIVE_READ_ENABLED=true` and explicit read-only credentials
  `R2_READ_ACCESS_KEY_ID` / `R2_READ_SECRET_ACCESS_KEY`, account ID and bucket.
  **None of these are activated by this PR.**
- Before reading, validate each R2 receipt key format, SHA-256 and bounded
  compressed object size. Verify actual R2 checksum and gzip readback through
  the existing `read_verified` method, validate the complete v2 diagnostic
  payload and allowlisted event kinds, and confirm the archived row's
  identity, idempotency key, parameters and original creation timestamp match
  the corresponding PostgreSQL pointer row.
- Perform all reconstruction **in memory** and return the original event
  `progress` through the existing history endpoint. No SQL UPDATE/DELETE,
  no R2 writes, no automatic restoration to PostgreSQL, and no real trades.
- Group pointer rows by identical object receipt to avoid repeated downloads.
  Limit a single request to **four distinct R2 objects** and at most 100 raw
  rows, plus the existing bounded packed hot batches. If the page exceeds
  this resource budget, a receipt is unavailable, R2 read-only credentials
  are missing, or any integrity/provenance check fails, return a generic
  **503** with no partial history data or private object keys.
- Include `recent_history_complete=true`,
  `archived_rows_rehydrated` and `archive_objects_verified` only for a
  successfully assembled recent page.

## What this does not solve

This route still reports **the most recent 100 events**, not all-time
Favorites statistics, full pagination, or every historic experiment.
A long cold history may exceed the strict four-object budget; in that case
the owner receives an explicit 503 instead of misleading "complete" data.
The existing separately gated manifest reader is still required for R2
reclaimed/packed history, and the all-time Favorites study/dashboard must
eventually merge hot + cold evidence with pagination and verified
deduplication.

**Do not enable automatic v2 archival** merely because this PR deploys.
Keep `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED=false`, collection/trading paused
under MT-019, and complete the owner dashboard/analytics acceptance,
physical free-disk/WAL checks, restricted archive-role installation and
credential rotation independently.

The implementation is intended to be low-cost while archival is OFF:
no read-only R2 client is constructed when the hot page contains no v2
pointers. Test coverage includes real gzip/SHA roundtrip, tampered metadata,
wrong diagnostic type, missing read-only credentials, excessive per-page
objects, no R2 connection when hot, and HTTP fail-closed behavior.
