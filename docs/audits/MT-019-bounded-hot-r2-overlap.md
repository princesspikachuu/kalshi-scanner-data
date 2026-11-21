# MT-019 — Bounded supplied hot/R2 original overlap

This **offline, read-only** audit compares up to eight supplied hot raw source pages, eight supplied packed source pages, and the previously validated bounded archive catalog + R2 original page chains.

- Requires hot raw indexed key to equal its original event key and packed original to reference its actual batch key.
- Requires terminal continuous hot source keyset chains and independently checked supplied archive catalog/readbacks.
- Deduplicates identical original UUIDs across hot and R2, rejecting conflicting payloads and keys reused for different IDs.
- Preserves settlement, cash and fee payloads but never infers resolved wins or Favorites P/L.
- Limits all supplied input to 16 combined pages and 256 original copies. Larger histories need separately validated segments; this does not prove cross-segment uniqueness.

**Trust limits:** This pure function does no SQL/R2/HTTP I/O. Source-page authenticity, actual R2 SHA/gzip/manifest verification, and SQL snapshot stability must be separately established. A terminal supplied chain is not proof of global source exhaustion.

All readiness flags remain false: all-time coverage, independently authenticated R2 reads, stable database snapshot, authorized financial settlement, safe-to-train and safe-to-restart-writers. Do not use this audit to authorize deletions, archives, production writes, trading, collection, credential changes or new infrastructure.

Run focused tests with: python -m unittest services.api.tests.test_shadow_hot_r2_overlap. Full GitHub CI must pass before merge. This is not an API deployment.
