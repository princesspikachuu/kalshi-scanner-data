# MT-019 — Long-running source-keyset receipts

The authenticated owner routes for raw, packed and manifest history already
provide bounded keyset pages with request_cursor, next_cursor, more, indexed
source_keys or manifest_key, and row counts. Unlike original UUIDs, those
indexed source keys are actually sorted by their SQL queries.

This pure helper consumes *one source page at a time* and carries a constant-
size receipt. It rejects changed sources, page-key regressions, duplicated
source keys, invalid continuations, page count mismatches, pages after a
terminal page and invalid preceding receipts. It stores a cumulative SHA-256
digest of indexed keys, pages processed, source rows processed and count of
expanded original events. Manifest rows separately contribute
manifest_originals_claimed; those are never counted as verified outcomes.

The rolling key digest is stable regardless of how many source pages contain
the same keys. Its continuity evidence is useful when a collector needs to
enumerate more than the existing 64-page in-memory validator can hold.

LIMITATIONS AND SAFETY: These receipts cannot detect source rows omitted
from the SQL result by a broken or malicious fetcher, writers inserting rows
between queries, changes to indexed rows after scanning, unlisted archive
manifests, or changes to financial contents with unchanged indexed keys.
The digest is not signed and must not be confused with verified R2 object
hashes. This helper does no database or R2 I/O, no app routing, no background
work, no trading and no archived-row reclamation. It always returns:
stable_database_snapshot_verified=false,
r2_manifest_catalog_complete=false,
all_time_coverage_complete=false,
financial_reconciliation_complete=false,
safe_to_train=false, and safe_to_restart_writers=false.

Next design step: combine stable snapshot/cutoff under an authenticated owner
with per-source keyset receipts and independently verified archived source
objects, then verify portfolio settlement/fee records before any historical
Favorites training integration. Do not infer all-time reconstruction from a
successful keyset receipt.
