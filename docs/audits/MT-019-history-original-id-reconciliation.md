# MT-019 verified-history original identity reconciliation

This additive library is an **offline-only building block**, not a live all-time
Favorites endpoint. It does no database or R2 reads/writes and changes no
background work, trading, or archive flags.

A caller first retrieves source pages using their existing owner-authenticated
bounded endpoints. Raw R2 manifests must be verified by their existing SHA/gzip,
row count, and ID/provenance checks; packed batches must be decoded using the
existing lossless diagnostic decoder. The caller must explicitly mark each
R2-derived page `verified=True` **only after** those checks succeed.

`reconcile_verified_pages()` then:

- uses original event UUIDs to deduplicate hot raw, hot packed, verified R2
  pointers, and physically reclaimed R2 rows/batches;
- rejects mismatched source key/parameters/progress when the same UUID recurs;
- rejects reuse of one original event key under multiple UUIDs;
- retains full original progress, including settlement and P/L evidence;
- orders by original event time, not archive/manifest/UUID order;
- enforces 16 pages and 256 original events maximum per invocation;
- never claims complete all-time coverage, even if every supplied page is valid.

**Not yet implemented:** a cursor-driven orchestrator that exhausts the two
Postgres sources plus R2 manifest pages and their nested original events, checks
for page gaps and concurrent writer changes, and publishes a validated
completeness receipt. Neither all-time Favorites statistical aggregates nor
frontend counters are changed by this PR. Do not turn on archival, R2 reader
flags, restores, or trading based on this library.

Automated tests cover duplicate and mismatched source copies, payload and
timestamp tampering, UUID/key collisions, private source allowlist and caps,
protected financial progress, and explicit incomplete coverage.

## Second safeguard: pagination-chain validation

`verify_history_page_chain()` additionally rejects repeated or out-of-order
source-row keys, incorrect continuation cursors, missing terminal pages,
incorrect namespace, and invalid raw/packed/manifest source labels. This is
pure validation of supplied pages, not an R2 or SQL fetch. The collecting
caller must retain the exact request cursor and source row key for each page.

**Indexed-key visibility now added by this draft:** authenticated raw and
packed history responses expose `source_keys` taken from their actual
PostgreSQL rows, and owner manifest summaries expose `manifest_key`
from their indexed manifest record. These are *not* Cloudflare object
paths, credentials, or links. The future orchestrator must record the
exact request cursor alongside each response before asking the pure
checker to validate pagination. These changes remain draft until CI
passes and do not activate any R2 read or archive operation.
Every return still reports `database_snapshot_verified=false`,
`r2_manifest_catalog_complete=false`, and
`all_time_coverage_complete=false`.

This only helps detect malformed *supplied* page chains. It cannot detect a
missing database row between two apparently contiguous keyset results,
writer interference across separate transactions, or an omitted R2 manifest
outside the enumerated set. A final completeness receipt needs independent
source exhaustion and stable snapshot/cutoff verification.
