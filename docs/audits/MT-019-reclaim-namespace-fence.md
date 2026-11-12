# MT-019 — Operator-only diagnostic reclaim namespace fences

This patch strengthens both **preview-only** and explicitly authorized
operator archival/reclaim paths. Under PostgreSQL text collation, a bounded
range for `demo/shadow/event/` can include neighboring
`demo/shadow/event-batch/` keys. The raw and packed archive candidate
SELECTs and legacy direct-owner DELETEs now require a separate, bound
`idempotency_key LIKE prefix%` predicate in addition to the existing
indexed range, eligibility, age, and original-ID checks.

The raw archiver also checks every candidate's actual source prefix
**before any R2 write**. A mocked adjacent-prefix row is rejected and cannot
reach either a manifest insert or DELETE. Disposable PostgreSQL integration
shows a historical packed neighbor with a raw-diagnostic-looking event does
not enter the raw preview, and the preview leaves both records intact.

For new **direct-owner** manifests only, the manifest row ID now provides
the UUID used inside its indexed manifest key, rather than independently
generating two UUIDs. This makes future metadata easier to audit. Already
stored archives with independent row/key UUIDs remain fully supported by the
legacy-compatible reader in PR #214; they are **not rewritten or deleted**.
The separate scoped SECURITY DEFINER maintenance SQL function is not changed.

No automatic task or worker calls these operator-only tools. The normal
paper trading worker does not gain new database DELETE permissions.
No existing archives, credentials, actual production SQL, R2 contents,
strategy data, or account balances are changed by this PR. It is NOT an
authorization to execute archive reclamation, resume writers, or consider
physical WAL/disk headroom verified. Full latest CI is required to merge.
