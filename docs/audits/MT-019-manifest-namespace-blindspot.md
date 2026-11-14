# MT-019 — Identify archive-index rows hidden by recognized-only SQL filtering

The production owner archive reader and the bounded source index scan intentionally list only `succeeded` manifest rows with recognized kind/format. That is a useful access safety filter, but it does **not** prove the archive-manifest key namespace has no older, failed, unexpected or malformed rows.

`audit_manifest_namespace_snapshot(pool)` inspects **all** rows under `demo/shadow/archive-manifest/%` within ONE PostgreSQL `REPEATABLE READ, READ ONLY` transaction. It does not write, restore, archive, delete, relabel or move these records. It preserves unknown rows for later operator review, rather than silently treating them as absent.

**Protection:** Bounded 25 rows/page, 8 pages and 200 consumed index rows per invocation, with a 5-second per-statement timeout; a nonterminal page, malformed key, unexpected order or budget overrun raises instead of returning a false complete receipt. Each row is checked against the existing canonical ID, key, count, kind, format and digest summary contract. Non-succeeded, unfamiliar kind/format and malformed rows get distinct count categories and up to twelve SHA-256 *key hashes* as safe examples. No raw event/manifest bodies, secret or R2 path leaves the function.

A zero-anomaly result means **only** that no anomalous rows were found in this bounded, terminal SQL prefix walk at this snapshot. It does NOT establish that all historical archives are present, that the recognized manifest points to a currently readable R2 object, or that any archival deletion, settlement P/L, statistical training, API migration or writer restart is safe.

Disposable `pocket_test` PostgreSQL integration tests insert genuine recognized and unfamiliar legacy/format rows into the same index prefix; they verify that the recognized-only scan omits those unfamiliar rows, whereas this whole-prefix audit reports them, preserves them and maintains digest identity across page boundaries. No production SQL/R2 connection or database access change is made.

Operator blockers remain actual physical free disk and pg_wal headroom, independently scoped R2 READ credentials, least-privileged SQL maintenance, DB secret rotation, stable multi-source history and venue-authoritative virtual-lot/cash/fee settlement reconstruction. Collection/trading/automated archival must remain held.
