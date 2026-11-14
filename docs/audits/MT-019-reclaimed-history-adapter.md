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

## Individual manifest completion proof

The new pure `verify_reclaimed_manifest_chain()` checks consecutive bounded
offset pages from a single previously verified manifest: stable manifest ID and
source, unchanged total count, no repeated original UUID, no missing intermediate
page, and a terminal page ending at the recorded original-event count. It may
return `individual_manifest_exhausted=true` **only for that one manifest**.
It always returns `r2_manifest_catalog_complete=false` and
`all_time_coverage_complete=false`. The current maximum is 128 verified
pages / 10,000 original events for one chain; oversized histories require a
separately designed streaming receipt rather than silent truncation.

## Stable manifest fingerprint across requests

Owner manifest summaries now include only an opaque SHA-256 digest of the
manifest's canonical metadata (not the R2 object path or credentials).
Reclaimed pages inherit this digest from the verified manifest. The
individual-manifest chain checker requires the **same digest on every page**;
a manifest edited or replaced between two reads will fail rather than quietly
combine different content. This does not replace the existing full R2 object
SHA/gzip/row readback checks and does not prove PostgreSQL snapshot isolation.

## Original audit timestamps

`Engine.audit.log` serializes `progress.time` as a decimal string.
The shared identity reconciler now accepts safe nonnegative decimal-string
timestamps as well as numeric timestamps for ordering while **preserving the
original string inside `progress`**. Nonfinite, negative, exponent, malformed,
oversized and injected values fail closed. This is necessary for real Favorites
cohort/settlement audit compatibility; it does not convert or rewrite R2 data.
