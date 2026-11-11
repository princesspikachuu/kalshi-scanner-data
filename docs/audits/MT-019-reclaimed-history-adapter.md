# MT-019 — Verified reclaimed history source pages

This change adds a **source-specific, owner-authenticated, read-only**
`GET /demo/shadow/history/reclaimed/{manifest_uuid}` endpoint. It wraps the
preexisting R2 manifest verification reader, **not** a new object retriever.

- Optional `?offset=0&limit=25` with strict bound 0–10000/1–50.
- The existing manifest reader must fully verify R2 gzip/SHA, original
  records/counts and the independent R2 READ credentials before returning.
  It remains disabled unless `MT_ARCHIVE_READ_ENABLED=true` and the
  separate read-only credential set is present.
- The adapter then checks the manifest kind, count, original UUID/key and
  timestamp, detects duplicate originals, validates the exact next offset
  and preserves original parameters, progress, settlement/P&L fields.
- Invalid user inputs: 422. Absent manifest: 404. Unconfigured reader or
  unverified/corrupt contents: sanitized 503. Authentication is mandatory.
- Responses explicitly declare `verified=true` for *this one archive
  object*, but `all_time_coverage_complete=false`,
  `source_exhaustion_verified=false`, and
  `r2_manifest_catalog_complete=false`.

This does **not** prove all-time coverage, create a cross-source snapshot,
compute Favorites statistics or enable any archival, restoration or trading.
Other P0 gates remain: independent R2 READ credential setup, strict storage/WAL
capacity, a scoped archive database login, credential rotation and complete
historical accounting. No production environment values, SQL rows or R2
objects are changed by this PR.

Validation includes pure raw/packed conversion tests, malformed counts,
duplicate original identities, tampered timestamps, source identity checks,
owner authentication, invalid paging, default-off R2 read refusal, and no
credentials disclosed in error messages.
