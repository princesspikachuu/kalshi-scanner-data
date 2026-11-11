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
