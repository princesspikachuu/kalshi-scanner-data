# MT-019 — fail-closed bounded-index key boundary validation

The existing offline PostgreSQL keyset scans intentionally use an indexed upper bound, `idempotency_key < prefix + 'zzzz'`, alongside a `LIKE prefix + '%'` predicate. This is efficient for ordinary UUID-keyed history but it **does not include** a row whose key is exactly the bare prefix, equal to `prefix + 'zzzz'`, or has an unexpectedly large or legacy suffix sorting above that upper limit. A scan that terminates inside the bounded range is not automatically a complete inventory of the entire prefix namespace.

This change adds `assert_no_hidden_prefix_keys(connection, prefixes)` as a mandatory same-transaction guard before three offline audit routines can return a "scanned" receipt:

- `read_postgres_snapshot_window` for raw, packed and recognized manifests.
- `scan_postgres_index_snapshot` for all three bounded source keysets.
- `audit_manifest_namespace_snapshot` for the full manifest prefix, including unknown legacy kinds.

For each explicitly allowlisted prefix, it performs **two small indexed existence probes**: a bare-prefix equality probe and an upper-tail `>= prefix+'zzzz'` probe restricted to the same prefix. If either returns a row, the existing diagnostic **raises**, preserving the source row and refusing to claim a completed indexed scan. The probes execute inside the caller's existing **REPEATABLE READ, READ ONLY** transaction with a five-second statement timeout; they never fetch event payloads, delete rows, contact R2, change API/worker configuration, or grant access.

New output flag: `bounded_prefix_key_boundaries_verified=true` only after every probe succeeds. It does **not** change any separate all-time source/R2/history, physical disk/WAL, settlement, training, or writer-restart flags; these remain false.

Regression coverage includes input rejection and exact SQL query contracts, mock transaction tests, and actual disposable `pocket_test` PostgreSQL rows with hidden bare-prefix or legacy `zzzzzz` keys, verifying all affected paths reject incomplete coverage while retaining the records.

This is a correctness fix to **offline diagnostics**, not an operator authorization to restart trading, collection, R2 archiving or reclamation. Database physical free disk and WAL headroom, private R2 READ, maintenance role, credential rotation, full historical source enumeration, venue outcomes and paper-wallet cash/lot/fee reconciliation remain independent hard gates.
