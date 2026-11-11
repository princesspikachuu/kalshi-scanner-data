# MT-019 — Actual read-only storage measurements after database recovery

Source: `pocket-processing-staging` one-shot `storage_recovery_diagnostic` emitted **2026-11-11 03:33:18 UTC**. All market collection and trading stayed disabled. Database was manually resumed and its allocation increased to **15 GB by the owner**; Render autoscaling remains disabled.

## In-database logical sizes

| Object | Bytes | Decimal GB |
| --- | ---: | ---: |
| Entire database | 9,127,323,315 | 9.13 |
| `research_job`, including indexes | 6,198,132,736 | 6.20 |
| `research_job` table storage | 5,216,083,968 | 5.22 |
| `research_job` indexes | 982,048,768 | 0.98 |
| `research_dataset` | 1,351,368,704 | 1.35 |
| `collection_page` | 445,038,592 | 0.45 |
| `raw_archive` | 286,326,784 | 0.29 |
| `research_campaign_work` | 277,192,704 | 0.28 |
| `research_dataset_artifact` | 227,467,264 | 0.23 |
| `research_artifact` | 225,239,040 | 0.23 |

`research_job` is ~68% of the logical database. These are **not physical free-disk/WAL measurements**; do not claim the 15 GB volume has an exact 5.87 GB of free headroom. PostgreSQL n_live_tup/n_dead_tup estimates were zero after restart, apparently reset; do not treat them as actual row counts.

## Raw shadow event sample (SYSTEM 0.25%, page-based)

| Event kind | Sampled rows | Sampled parameter + progress bytes |
| --- | ---: | ---: |
| SCALPER_OBSERVATION_BATCH | 695 | 2,221,489 |
| FAVORITE_STAT_DECISION | 397 | 445,534 |
| CYCLE_REPORT | 286 | 434,182 |
| DATA_GAP | 959 | 296,729 |
| SCALPER_ENTRY_DECISION | 95 | 185,198 |
| ORDER_SUBMITTED | 294 | 173,714 |
| MARKET | 134 | 83,294 |
| CANCEL_SUBMITTED | 158 | 76,794 |
| FILL | 102 | 68,607 |

A separate 1% SYSTEM sample included 16,611 `demo/shadow` job rows with 20,633,139 sampled bytes. **These samples do not establish the exact whole-table bytes for each kind or the number of rows eligible for removal.** The priority is older Scalper and Favorites non-financial diagnostic history, to R2 with verification.

## Operational constraints

- PR #174 operator-only R2 raw-event reclaim and PR #175 lossless diagnostic batching + packed-event recovery merged, but no historical rows have been deleted or moved by this audit.
- PR #177 implemented a one-time read-only storage inspection within recovery hold; it is off again.
- `pocket-processing-staging` and `pocket-research-staging` remain `WORKER_ROLE=collector`, `COLLECTION_ENABLED=false`, `MT_STORAGE_RECOVERY_HOLD=true`. Processor `DATABASE_CAPACITY_GB` is 15.
- Connected Render SQL query is blocked by the intentionally empty external IP allowlist. Do not open database externally for this work; run approved operator CLI inside Render with separate private recovery credentials.
- Before deleting any DB row: inspect candidate IDs, upload all original fields to Cloudflare R2, verify readback, store exact-ID manifest, execute just one small scoped transaction, recheck account/settlement integrity, and verify actual physical/WAL storage. Normal VACUUM can make dead pages reusable without reducing provisioned disk.
- Retain finances, orders, settlement evidence, current checkpoints and published learning datasets. Do not run heavy VACUUM FULL at near capacity.
- Render Blueprint source-of-truth has been aligned to **15 GB, disk autoscaling off**, but is draft-only and has **not** been synced/applied. Do not increase storage again without new owner approval.
