# MT-019 — Final independent control-backup coverage hardening

The already-deployed multipart control backup V2 preserves original selected control data and verifies every compressed R2 chunk, root receipt and readback. The final static review found one bounded-index caveat: each of its eleven control prefixes uses `idempotency_key >= prefix AND idempotency_key < prefix + 'zzzz'`. A future legacy or malformed key such as `live/write/zzzzzz-legacy` belongs to that control prefix but sorts **after** the upper limit. The snapshot could have verified all *selected* rows while missing this original row.

## Fix

Both in-memory `collect_snapshot` and bounded-on-disk `collect_snapshot_spooled` now run a small upper-tail existence probe for each fixed, allowlisted control prefix, inside the **same REPEATABLE READ, READ ONLY PostgreSQL snapshot** as the capture:

```sql
SELECT 1 AS present FROM research_job
WHERE idempotency_key >= $1
  AND idempotency_key LIKE $2
LIMIT 1;
```

The bound parameters are `prefix + 'zzzz'` and `prefix + '%'`. If any hidden row exists, the backup raises `ValueError`, never publishes a partial snapshot as complete, and the spooled path closes its temporary file. It leaves the original row untouched. Ordinary controls within the normal prefix continue to back up. The legacy census and source selection scopes are not changed.

Regression tests exercise the exact query and fail-closed receipt, closing the temporary spool after failure, and **real disposable pocket_test PostgreSQL** with a high-suffix legacy key and a valid control key. No live database or R2 call occurs in these tests.

This guarantees only that these **configured control prefix windows** contain no additional upper-tail keys in the sampled snapshot. It does not prove all-time historical event recovery or a complete backup of data outside the defined control scope; it also does not establish physical disk or WAL headroom, current R2 read credentials, authoritative settlement, or readiness to restart trading.

## Deployment and hard gates

The code change is inert while the collector's recovery hold keeps collection and the normal maintenance loop disabled; one-time control-backup and recurring backup opt-ins remain OFF unless an operator explicitly enables them. No production SQL, R2 upload, archive/delete/reclaim, API deployment, IAM or networking change is required.

Full exact-head GitHub CI, including the real disposable PostgreSQL suite, must pass before merging. Keep MT-019 IN PROGRESS until physical disk/WAL, separately authenticated R2 READ, complete SQL/R2 original history, least-privileged archive role, credential rotation, all-writer drain, and cash/lot/fee/settlement reconciliation are proven by an authorized operator.
