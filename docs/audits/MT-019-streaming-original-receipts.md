# MT-019 — Bounded original-ID streaming receipts

The existing supplied-page preview deliberately caps materialization at 256
original event copies. This offline, no-I/O helper creates a rolling SHA-256
receipt over successive chunks of up to 256 entries, making exact original
UUID counts and conflicting duplicate detection possible across chunks
without maintaining an unbounded set of UUIDs.

Each input entry contains the original event, an allowlisted source label,
and independent verified=True provenance for R2/cold rows. The caller MUST
globally merge source streams in ascending original UUID order; duplicate
copies of an original UUID must be adjacent. The receipt refuses backward
UUIDs or changed original parameters/progress/key for duplicate UUIDs.
It carries only the last UUID and its payload fingerprint, the cumulative
hash, exact counts and processed-chunk count. The rolling hash covers each
unique event exactly once, independent of how chunks are divided.

This primitive does not fetch sources, authenticate a manifest, create a
durable signed record, prove the caller's source enumeration was exhaustive,
or prove no event UUID was omitted between adjacent UUIDs. In particular,
a stable digest cannot substitute for a database snapshot, full R2 manifest
catalog exhaustion, wallet/fee reconciliation, verified payouts, or
authoritative Favorites statistics. The result always reports
all_time_coverage_complete=false, safe_to_train=false,
safe_to_restart_writers=false and authoritative_financial_outcomes=0.

Do NOT feed it into trading, mark MT-019 done, or use it to authorize any
archival/reclamation. It is a testable building block for a later streaming
orchestrator under explicitly authenticated and fixed snapshot/cutoff
conditions. No Render worker loop, SQL, R2 I/O or environment change.
