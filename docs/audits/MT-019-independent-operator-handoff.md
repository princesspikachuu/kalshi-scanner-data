# MT-019 — Independent engineering closeout and operator handoff

**Date:** 2026-11-12 Pacific. **Task remains OPEN / P0** until the operational and financial recovery acceptance gates below are proven. This document does not authorize access changes, SQL writes, archive deletion/reclaim, trading, collection, retraining or API deployments.

## Verified without production mutation

- Render PostgreSQL `pocket-db-staging` is available, with **15 GB provisioned, disk autoscaling disabled, and external IP allowlist empty**. These facts **do not measure physical free space**.
- Processing collector is live on merged MT-019 PR #225 (`064c12bab71445418a7a469f49eda0887ab99be7`). Full premerge CI `43350408874` and postmerge CI `43354831041` passed. Its predeploy receipt at 2026-11-13 02:54:23 UTC confirmed `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`, and deferred DB check. Research worker was separately confirmed recovery-held; the API retains its earlier manual deployment and may run DB migration on redeploy.
- Bounded, offline PostgreSQL/R2 evidence validators, source keyset receipts, original UUID conflict rejection, whole archive manifest namespace inventory and prefix high-key boundary guards have passed disposable PostgreSQL and CI testing. They **do not** prove an all-time original history, a stable global SQL/R2 source snapshot, or real market settlement.
- Recovery archive functions are opt-in and require stopped writers, separately scoped SQL authority, read-after-write R2 verification, diagnostic-only eligibility and short guarded transactions. `SETTLED`, fills, orders, cash and control events must not be reclaimed. API recovery-hold code defaults OFF and is not proof that the current API has stopped writing.
- The earlier 4,190-record / 98-chunk R2 control-backup receipt and ten-row diagnostic archive checks concern their **specific supplied snapshots**, not all database history or current routine backups.
- The **final static review** identified an analogous `prefix+'zzzz'` upper-tail omission risk in multipart control-backup V2. Draft PR #226 `fix/mt019-control-backup-tail-boundary` adds fail-closed same-snapshot upper-tail probes to its in-memory and spooled capture paths, unit tests and disposable PostgreSQL preservation tests. At document creation, exact head `013b557e1b35a2d9c29aef369478d43fcfe14837`, CI `43361374939` was in progress. **Do not merge until exact-head full CI success; verify postmerge CI and held worker startup.**

## Operator-only acceptance evidence (all required; none inferred from code CI)

| Gate | Evidence required | Stop condition |
|---|---|---|
| Physical database disk | Render database **Metrics → Disk Usage**: observed current usage, recent peak, trend and timestamp against provisioned 15 GB | Missing graph, inadequate headroom, or steep growth |
| WAL headroom | Separately authorized actual `pg_wal` occupancy/current retention and filesystem free-space evidence | Only cumulative `pg_stat_wal`, logical DB bytes, healthy CPU or low connections known |
| Independent R2 readability | Scoped **READ-only** credentials, independently enumerated current/legacy archive manifests and actual R2 object checksum/readback receipts; verify missing/orphan/conflicting original IDs | Credentials unavailable, incomplete provenance, unknown manifest rows or verification mismatch |
| Privileged maintenance | Isolated least-privilege `pocket_archive_maintenance` role with scoped reclaim function; rotate previously exposed DB credential through trusted private operator controls | Ordinary app/owner role or broad INSERT/UPDATE/DELETE/TRUNCATE access |
| Writer quiescence | Explicit API hold only in coordinated maintenance window; all old API instances and in-flight requests fully drained; both workers held; independent verification of cron/manual/other SQL writers | Only worker flags or connection counts observed |
| Recoverability and money | Preserve verified backups, financial/event originals and exact historical market outcomes; independently reconcile paper wallet positions, partial fills/exits, costs, fees and cash with authoritative venue settlement | Any unexplained original, settlement, discrepancy or incomplete restore |
| Controlled resumption | Only after previous gates: operator-supervised *small* eligible nonfinancial diagnostic R2 archive, verified manifest/source-ID transaction and repeated physical disk/WAL checks. Establish sustainable backups/cold-history reads and resource budget before any regular collection/trading restart | Any missing gate or regression; automatically paused strategies must remain paused |

## Safe operator sequence

1. Obtain **read-only actual physical disk and WAL measurements** using existing authorized Render interfaces. Do **not** open database IP allowlisting or deploy a migration merely to gather a figure.
2. Establish independent R2 READ and stable complete SQL/R2 history evidence. Reject unknown/legacy archive key mismatches; never assume a terminal bounded page equals full history.
3. Through trusted owner-only controls, rotate exposed credentials and verify the scoped maintenance role's actual grants. Do not put tokens or passwords in GitHub, logs or chat.
4. If any write-capable recovery is required, coordinate a maintenance window and independently confirm **all** API/worker/other writers stopped. A held collector alone is insufficient.
5. Perform at most one small supervised R2-verified nonfinancial archival batch after all required gates pass, rechecking source identity, manifest, disk and WAL between batches. Keep financial/control history and original provenance intact.
6. Reconcile authoritative settlement and paper funds/positions/fees and validate recurring backup/retention policy before a separate decision to restore normal service.

**No further safe independent production steps are available under the connected permissions.** Do not create additional diagnostic services, expose the database, raise spending, auto-enable collection/trading or invoke archivers merely to make MT-019 appear complete.

Current working status belongs in [WORK_QUEUE.md](../../WORK_QUEUE.md); the entire earlier investigation was preserved verbatim in [MT-019 historical checkpoints](MT-019-work-queue-history-2026-11-12.md). The system may remain held safely while external evidence is obtained.
