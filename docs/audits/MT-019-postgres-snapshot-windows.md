# MT-019 — Read-only PostgreSQL source-window consistency check

A bounded operator-facing helper can now inspect the raw, packed and
archived-manifest indexed PostgreSQL namespaces within ONE database
transaction. The first command is SET TRANSACTION ISOLATION LEVEL REPEATABLE
READ READ ONLY; the tool also sets a 5-second local statement timeout and
only SELECTs indexed keys. A snapshot ID labels which database version all
three windows were read from.

Only the first 1–32 indexed keys in each namespace are collected per source.
The helper returns each source's first/last key, whether more rows remain
and a next cursor, plus a simple digest of the supplied keys. No original
financial details or R2 object URLs are exposed.

If all three namespaces end inside the *first* read-only transaction,
indexed_namespaces_fully_scanned_in_this_snapshot may be true. This asserts
only that these three specific indexed PostgreSQL namespaces had no more
visible matching rows within that single bounded snapshot. It does NOT
cover other research_job namespaces, physically reclaimed R2 history,
a stable snapshot across later calls, verified original event identities,
complete Favorites evidence cells, or realized paper P/L.

If any namespace has more keys, its next window is a NEW transaction and
cannot inherit the earlier snapshot. The function therefore never sets
source_exhaustion_verified, r2_manifest_catalog_complete,
all_time_coverage_complete or safe_to_train to true. No production route,
cron job, new connection, archival, deletion, deployment or collection is
enabled by this PR. Disposable PostgreSQL tests check real keyset
pagination and record counts.

For a comprehensive history scan, use an authorized long-lived snapshot
or an explicit fixed immutable cutoff with independent change-detection,
plus R2 manifest catalog and SHA/gzip checks, before asserting completeness.
Do not leave long-lived PostgreSQL transactions open during active storage
pressure without understanding vacuum/WAL costs.

## Verified namespace-boundary finding

Disposable PostgreSQL tests showed that a range bounded by
`demo/shadow/event/` and `demo/shadow/event/zzzz` also counted a
neighboring `demo/shadow/event-batch/` row under the active collation.
The snapshot helper now requires **both** the existing indexed bounds
and an explicit bound `idempotency_key LIKE 'demo/shadow/event/%'`
(or the corresponding packed/manifest prefix). Its verification count
uses the same strict predicate. This prevents incorrect source counts
without relaxing the fail-closed index-key validation.
The production owner history endpoint mitigation is separately reviewed
in PR #213.
