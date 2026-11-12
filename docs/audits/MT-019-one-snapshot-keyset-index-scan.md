# MT-019 — Bounded single PostgreSQL snapshot index scan

`scan_postgres_index_snapshot(pool)` is an offline diagnostic that walks the existing raw, packed, and archive-manifest SQL *index namespaces* within **one REPEATABLE READ READ ONLY transaction**. It preserves keyset ordering and reports counts and SHA-256 digests, without materializing or modifying the underlying event rows.

It uses fixed preexisting namespace predicates, a 5-second SQL statement timeout, and no COUNT/OFFSET. It caps page size at 32, pages at eight per source, and combined keys at 512; when any source exceeds a cap or returns inconsistent data, the function **raises rather than returning a partial exhaustion receipt**. It performs no R2, HTTP, background-worker, deletion, or trading operations.

A verified full keyset scan means only that the three selected indexed SQL namespaces terminated inside that **single PostgreSQL snapshot**. This is not evidence that all source events or historic R2 objects were recovered: the manifest query filters to recognized succeeded rows, and physically reclaimed events may exist only in independently verified R2 history. The result always keeps source-exhaustion, all-time coverage, realized P/L, safe-to-train and safe-to-restart flags false.

Tests exercise exact SQL read-only transaction structure, ordering, lookahead and bounded failure, plus actual disposable `pocket_test` PostgreSQL raw+packed+manifest rows and page-size-independent fingerprints. No production DB credentials, external IP allowlist changes, R2 authorizations, or archival enablement.

This is one intermediate audit building block. Required operator gates remain physical free disk/WAL, independent R2 READ credentials, scoped maintenance role, DB credential rotation, complete SQL/R2 historical enumeration, and authoritative virtual-lot settlement/fee/cash accounting. Do not restart writers or turn on archiving based on this audit.
