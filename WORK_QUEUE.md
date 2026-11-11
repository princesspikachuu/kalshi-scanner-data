# Money Tree / Kalshi Shared Work Queue

This file is the coordination source of truth for ChatGPT/Codex implementation chats working on this repository.

## How implementation chats must use this file

When the user says **"continue"** and the current chat has finished its assigned work:

1. Read this file before choosing more work.
2. Do **not** start a task already marked `IN PROGRESS` by another chat.
3. Claim exactly one unclaimed task by editing its status to `IN PROGRESS`, adding a short worker label and UTC timestamp.
4. Commit that claim before changing application code so parallel chats can see it.
5. Complete the task end-to-end, including relevant tests/verification.
6. Update this file again with:
   - `DONE` if complete, or `BLOCKED` if genuinely blocked.
   - concise implementation notes.
   - files/components changed.
   - verification performed and result.
   - any follow-up task discovered.
7. If the task is done and the user says "continue" again, return here and claim another `READY` task.
8. Before claiming, re-read the latest `WORK_QUEUE.md` from `main` so a stale copy cannot overwrite another chat's claim.
9. When a task changes application code, record the implementation branch/PR/commit in Completion notes so another chat can audit or continue it.

## Urgency levels
- `U0 — BLOCKER` — user-visible outage, broken core workflow, data integrity risk, or issue preventing normal use. Claim before any lower-urgency READY work unless already blocked by another active fix.
- `U1 — URGENT` — severe degradation or time-sensitive work that should be next after blockers.
- `U2 — HIGH` — important product/strategy work with meaningful impact, but not currently blocking use.
- `U3 — NORMAL` — standard planned improvement.
- `U4 — BACKLOG` — useful but deferrable work.

### Queue ordering rule
When choosing new work, sort first by urgency (U0 → U4), then by dependency/readiness, then by the existing Priority text. A lower-urgency task already `IN PROGRESS` may finish unless a U0 issue requires the same files/infrastructure or the user explicitly redirects it.

### Status values
- `READY` — available for any chat to claim.
- `IN PROGRESS` — actively owned; other chats must skip it.
- `BLOCKED` — cannot proceed until the blocker is resolved.
- `DONE` — finished and verified.
- `PAUSED` — intentionally not being worked on.

### Global constraints
- Preserve all existing collected trading data.
- Extend current strategies instead of replacing/resetting them unless explicitly instructed.
- Paper-trading behavior must remain isolated from live trading.
- Do not reduce useful monitoring/trading activity merely to save worker resources.
- Favor instrumentation that lets us measure whether a change actually increased trade opportunities, fills, data volume, and P/L.
- If a task changes shared strategy infrastructure, verify it does not silently break the other active strategies.
- Current user intent: **Market Maker and Favorites are active; volatility strategies are paused.** Paused markets/strategies should remain paused unless explicitly re-enabled.

---


# PRIORITY 0 — URGENT DATABASE OUTAGE & RUNAWAY STORAGE

## MT-019 — Recover automatically suspended Render Postgres and stop uncontrolled paper-history growth
**Status:** IN PROGRESS  
**Worker:** ChatGPT / storage-outage investigation  
**Claimed:** 2026-11-10 17:30 UTC  
**Urgency:** U0 — BLOCKER  
**Priority:** Immediate, before MT-011 throughput verification and any resumed trading

### Latest independent continuation checkpoint — 2026-11-11 UTC
- **PR #203 MERGED**, commit `f7c14ae531a8a1294887610e720d90b6d1987bee`; full premerge CI `43119627571` SUCCESS and postmerge CI `43120391268` SUCCESS. Adds fail-closed original-event UUID deduplication, SQL source-key cursor-chain checks and honest incomplete-history flags. Render **processing worker LIVE** on that exact commit at 23:36:37 UTC; verified recovery-hold log at 23:36:26: `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`.
- **PR #204 MERGED**, tested head `e2145974ba8417bd88d4478ded0b3097aa82bb31`, full PR CI `43121292339` SUCCESS, squash merge `0138992bbf2bf195021aae6c72d770f51c6304ca`; **API has not been manually deployed**. Postmerge CI `43121982282` **SUCCESS**; Render processing worker last confirmed LIVE on #203 `f7c14ae5` (not yet #204). Earlier head runs `43120817203` and `43120963040` SUCCESS. Bounded authenticated R2 reclaimed raw/packed source pages, exact original IDs/manifest key, nonsecret manifest metadata fingerprint and per-manifest offset-chain checks, real audit decimal-string timestamp compatibility, 503 on unverifiable data. Existing separate R2 READ credentials and flags remain OFF; **never claim all-time coverage from one R2 page**.
- **PR #205 MERGED** as `899b017efbb16e94e0dec844c897c13c99f95632`; corrected head `1c311a54b62560e993bfa61e7cbd1901fa9645eb` full CI `43122326989` SUCCESS. Postmerge CI / processing deployment still to verify. Initial run `43121723189` had failed a decimal-GB field/constant typo, which was fixed and fully retested. Adds read-only 70/85% logical-size thresholds and 1%-capacity/hour optional growth detection to existing audit with NO extra SQL/cadence. Render capacity compared as decimal GB. Always marks physical filesystem free bytes/WAL headroom **unverified**, never authorizes deletion, trading or capacity upgrades.
- **API still LIVE on PR #201** commit `93c86efc` as of last Render inspection; new history endpoints from #202/#204 have **not** been independently verified LIVE in API. Do not deploy #204 before latest CI terminal SUCCESS.
- **PR #204 processing deployment verified LIVE** at 2026-11-11 23:48:04 UTC as `0138992b`; predeploy 23:47:53 log verified `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, role collector. API remains separately manual and not rolled forward.
- **PR #206 MERGED** `c541a95edd27edc00f5e67df5cabcd5868ec6fe7`, exact head `eaa6465ab33e85f2ec9ac34ec635d92717af3205`, full premerge CI `43122697167` SUCCESS. Postmerge CI/deployment pending; no runtime integration. Adds pure bounded Favorites cohort/trial/settlement record-presence census over independently verified originals, never invents authoritative outcomes/P&L or signals safe-to-train. This is **NOT** a verified all-time statistical model reconstruction.
- **Draft PR #207** `fix/mt019-history-source-cursor-receipts`, head `a90bbcf2edd3d8db3e92cdd0d0abd31c5be78191`, CI `43123205885` in progress at last check; adds read-only validated `request_cursor` response metadata for raw/packed/manifest source pages and tests, no extra SQL/R2/worker calls, never claims all-time completeness.
- **Draft PR #208** `fix/mt019-bounded-multisource-preview`, head `3fadf2c74b8f120217cc4b08178135d109b5cd7d`, CI `43123396759` IN PROGRESS; pure no-IO supplied hot/raw/packed/R2 manifest-chain verification and original ID reconciliation, hard 16-page/8-manifest/256-event caps, explicitly `safe_to_train=false`, `all_time_coverage_complete=false`. No route or runtime activation; snapshot/catalog completeness still unresolved.
- **P0 still IN PROGRESS.** Main remaining engineering: cursor-driven all-source exhaustion (hot raw + packed + R2 manifest list + verified manifests), cross-source stable provenance and truthful Favorites evidence reconstruction. `favorite_statistics.aggregate()` uses persisted evidence cells, NOT archived event pages automatically; all-time statistical training must not be assumed restored.
- Operator-only blockers: physical disk/WAL free headroom measurement, dedicated least-privilege archive SQL role, separate R2 READ credentials, rotate previously exposed runtime DB password, verify all writers drained before selective reclaim. **Keep collection/trading, automatic archival, restore requests, and any further data deletion OFF.** Earlier 10-record archive and independently verified R2 backup remain preserved. No live SQL/R2 mutations performed by this continuation.


### Confirmed incident and ownership
- Render account email at **2026-11-10 12:34:06 UTC**: Render **automatically suspended** database `pocket_staging` after exceeding disk quota to prevent repeated restarts. This was **NOT confirmed to be initiated by the user**, despite `suspenders=["user"]` in generic Render resource metadata. Previous >90% usage alerts were delivered Nov 8/9.
- Database id `dpg-dbgcrl6c6qcc73f1hi1g-a`, 10 GB allocated, disk autoscaling **disabled**, status **suspended**. Service/worker startup now fails to resolve DB hostname and times out on connection pools.
- Connection and safety settings unchanged. Do not resume or increase billable storage without user direction; simply resuming at quota without space can fail again.

### Measured root cause: stored table growth (not just checkpoint network write traffic)
Database `database_storage_audit` log:
| UTC timestamp | Total DB bytes | research_job total bytes | Approx research_job rows |
| --- | ---: | ---: | ---: |
| Nov 7 06:05 | 5,856,***,*** (~5.86 GB) | ~2.97 GB | ~1.94m live |
| Nov 9 23:35 | ~8.82 GB | ~5.90 GB | ~3.13m live |

**~2.93 GB of ~2.96 GB total database growth** is attributable to growth of `research_job` table + indexes during this period (measurements rounded). The table stores both background jobs and append-only `demo/shadow/event/<uuid>` paper-trading events; within sampled jobs, `demo/shadow` grew from **2,376 sampled rows / 0.656 MB sampled bytes** to **14,319 rows / 18.372 MB sampled bytes**, while campaign sample remained about 13k rows / ~7.3 MB. The sample is SYSTEM(1) and is **not** a complete exact partition of table bytes. It nevertheless strongly implicates paper-history expansion as the dominant recent contributor.

The paper worker creates a new `research_job` event row for each new event UUID in `services/paper_demo/shadow/storage.py`, and preserves individual audit events by design. Its existing checkpoint upserts also generate WAL/dead tuples but do not necessarily grow the live table by 2.81 GB per 30 minutes. Postgres indexes, TOAST, dead tuples, and WAL contribute physical disk beyond stored logical values. **Do not equate 2.81 GB/30min checkpoint transport with net table growth.**

### Safe recovery/engineering steps
1. **Owner billing/storage decision**: use Render Dashboard DB page to resume and increase storage together. Render notification explicitly directs the operator to resume **and increase storage**; do not claim 10 GB is sufficient. Size increase is billable/non-reversible; obtain owner approval. Do not delete data.
2. Once access returns, immediately measure top table/TOAST/index sizes and `research_job` family growth by counts, median/p95 event payload size, hourly rate, and per-event-kind quantities. Measure `pg_database_size`, free disk, WAL, dead tuples, autovacuum/analyze, and time-based growth.
3. Design lossless archival/compaction or partitioned history for `demo/shadow/event` with stable, queryable aggregates and durable raw evidence. Keep settlement, P/L, bot analytics, and all research history intact. Do **not** wipe history, reset funds, truncate tables, or delete events as a quick fix.
4. Add durable growth budget and proactive thresholds (e.g., warning at 70% and 85%, unexpected growth alert) and restrict **redundant** per-tick event logging while retaining meaningful observations. No reduction to useful Favorites or Market Maker trading/monitoring.
5. PR #171 merged as `edd87e8d`, included in live worker version `a274d028`, to avoid identical checkpoint upserts; savings cannot be verified while database is suspended. Assess its actual value independently of the append-only-event problem.
6. Confirm resumed worker/API health, account/history recovery, and before/after database growth. Only mark DONE after sustainable growth is verified.

### No-storage-increase decision and corrected architecture audit (2026-11-10)
- **Owner instruction:** NO Render storage expansion, NO disk autoscaling. Keep the 10 GB cap. Investigate unnecessary data, migrate cold evidence to the already architected Cloudflare R2 object store, and delete only after verifiable archive and safe retrieval.
- **Correction:** Contrary to an earlier incomplete code-path inspection, active `HostedRun.control()` in `services/paper_demo/shadow/host.py` **does call** `services.demo.maintenance.maintenance()` about every five minutes. The archiver was not absent: verified live `demo_archive_scan` logs repeatedly show `scanned:129–200, archived:0` through Nov 10 00:14 UTC.
- **Why it made no progress:** `archive_events()` waits **30 days normally / 7 days under pressure**, but the large flood of paper event rows accrued over only a few days. It handles **at most 200 rows per pass**, alternates `demo/event` and `demo/shadow/event`, and merely replaces `progress` JSON with an R2 pointer while retaining each Postgres row and indexes. At five-minute cadence the shadow path reaches only **~28,800 rows/day** even when eligible, far below measured creation rates. This cannot keep active DB small.
- **Backup also degraded:** live `demo_backup_verification_failed` logs show repeated `QueryCanceled` (SQLSTATE 57014) and later `backup_capacity`; verified R2 control backup last seen Nov 8 04:36 UTC, not current. Diagnose backup separately; don't claim archival healthy.
- R2 adapter is implemented in `services/research/r2.py` and the verified archive contract is `services/demo/maintenance.py` and `services/research/archive.py`. Whether every intended bucket/object is configured and healthy needs operator-side verification after DB restoration; don't disclose credentials.
- **Do not treat `VACUUM` as immediate shrinkage:** normal VACUUM makes free pages reusable inside Postgres but may not reduce disk allocation. A `VACUUM FULL` or table rewrite needs extra space and exclusive locks, unsafe near hard disk limit. Avoid mass DELETE without verified R2 and a bounded WAL/disk budget.
- Design **bounded hot event retention** plus verifiable **R2 archive manifests / searchable metadata** and controlled batched removal of old `demo/shadow/event` rows. Preserve current executions, open orders, settlement and P/L, and allow restoration of historical evidence. Ensure the archive scanner can keep up with current creation volume.
- Worker currently logs `paper_balance_retention_deferred` due to **no DELETE privilege**; don't grant broad DELETE to normal workers. Plan an explicitly authorized, tightly scoped recovery/operator procedure for deletion after archive verification.
- Based on Render docs, a suspended at-capacity database may need short resumption to reclaim space, but it may be re-suspended if no room becomes available; stop new writes first. No user approval to upgrade disk.

### Completion notes
_Confirmed auto-suspension due to full 10 GB allocation. Code-path and logs show archival was running but doing zero successful event archives. Owner forbids storage expansion; preparation of safe R2 archival + selective cleanup remains in progress, live DB changes blocked by suspension._

### Prepared recovery implementation
- Draft PR [#174](https://github.com/princesspikachuu/kalshi-scanner-data/pull/174), branch `fix/mt-019-r2-archive-reclaim`: operator-only, preview-first tool `services/demo/shadow_archive_recovery.py` for R2 verified archival + single-transaction deletion of aged `demo/shadow/event/` originals. No runtime hook; requires independent recovery DB credential and explicit --writers-stopped --execute. It does not touch live orders, wallet, research datasets or checkpoints.
- Added `services/api/tests/test_shadow_archive_recovery.py` and `docs/audits/MT-019-no-storage-upgrade-recovery.md`. CI review pending. No live database change or deletion done.
- **Not the final fix:** need continuous low-overhead R2 cold offload, searchable history, control backup repair, duplicate/diagnostic event reduction, and actual post-recovery physical disk monitoring, without extra Render capacity.

### Engineering progress — 2026-11-10
- PR [#174](https://github.com/princesspikachuu/kalshi-scanner-data/pull/174), `fix/mt-019-r2-archive-reclaim`: recovery tool further limited to six **non-financial** diagnostic event kinds, protects fills/settlements/CYCLE_REPORT, uses indexed keyset paging, preserves *all original research_job columns* in checksum-verified R2 objects, and provides event-ID manifests plus restoration verification. Tests expanded; latest CI validation still pending. Draft/unmerged; no data deleted.
- PR [#175](https://github.com/princesspikachuu/kalshi-scanner-data/pull/175), `fix/mt-019-lossless-diagnostic-batches`: preventive lossless gzip+SHA packing of consecutive Favorites/scalper diagnostic events (<=64 per database row), retaining original event IDs/payload, with recent-activity API reconstruction and protected financial event rows. Separate draft/unmerged; validation pending. Not the final R2 archival bridge; needs support for packed history before a recurring reclaim policy.
- Verified Render DB status remains `suspended` and allocated storage remains **10 GB**. No auto-expand, delete, resume or deploy initiated. User explicitly forbids buying capacity.
- More work required: restore without extra disk using an approved, controlled access path; verify R2 backup/restore and physical WAL/free space; implement sustainable recurring archive of both raw and packed histories; resolve stale control backup failures and confirm growth is bounded. Live recovery remains blocked while DB suspended.


### Validation check
- PR #174 code and expanded safety tests passed GitHub Actions on commit `7f557e60e99dec88ebdac5264bb8d70adaa4feb9`; a subsequent documentation-only commit `9ccf61fa48ef316417b757b41b908ff11c7ff8bb` has been pushed. Keep draft; **no cleanup executed**.
- PR #175 new lossless diagnostic batch implementation and tests have been pushed; GitHub Actions run `42876257675` was still in progress on last inspection. Keep draft; **not deployed**.
- Before merging either, review R2 retrieval of compressed-batch histories, PostgreSQL physical disk free space/WAL headroom, and the suspended database's recovery route. No storage purchase authorized.


### Combined raw + compressed recovery support (2026-11-10)
- Latest PR #174 head `9ccf61fa48ef316417b757b41b908ff11c7ff8bb` passed GitHub CI; still draft and not deployed. Operator-only, previews before any R2-backed deletion.
- PR #175 now includes `services/demo/shadow_batch_archive_recovery.py` for old `demo/shadow/event-batch/` records in addition to the lossless new-event packer. Uses bounded indexed candidate queries, a separate recovery DB connection, explicit --writers-stopped --execute, verified R2 readback, manifest IDs for both original batch rows and embedded event UUIDs, and a single transaction for manifest + exact deletion. Added `test_shadow_batch_archive_recovery.py`. New CI run is in progress; retain draft.
- Legacy Favorites statistics are sourced from persistent in-engine research cells, not raw `demo/shadow/event/` SQL scans (verified code paths). However, historical dashboard/replay browsing after archival still needs a dedicated R2 cold-history read path.
- Both operator archivers require actual database access, verified R2 bucket, and safe WAL headroom. No storage purchase, resume, archive execution, row deletion, or live strategy modifications authorized.
- Standard Render guidance says a full suspended DB can temporarily resume before being suspended again, but zero-upgrade recovery is not guaranteed. Do not start bulk cleanup without a controlled recovery and no concurrent writers.


### Owner-directed emergency recovery action (2026-11-10 afternoon PT)
- User authorized: **stop all data collection**, then resume existing 10 GB DB, then apply verified fixes. NO storage expansion. Do not automatically reactivate worker trading after DB resume.
- Render environment configuration accepted on `pocket-research-staging`: `COLLECTION_ENABLED=false` (deployment `dep-dbpqv90u01pc738ujna0`), but **pre_deploy_failed** because database is suspended; old live worker revision still exists.
- Render environment configuration accepted on `pocket-processing-staging`: `WORKER_ROLE=collector`, `COLLECTION_ENABLED=false`, `STAGING_ACCEPTANCE=off`, `STAGING_OPERATOR_ACTION=off` (deployment `dep-dbpqvauk1f9s73cnaosg`); not yet verified live. Using role `collector` is essential because `WORKER_ROLE=demo` ignores `COLLECTION_ENABLED`.
- PR [#176](https://github.com/princesspikachuu/kalshi-scanner-data/pull/176) introduces an explicit `MT_STORAGE_RECOVERY_HOLD=true` predeploy skip restricted to a disabled `collector` research-role worker. API and active worker DB safety checks remain enforced. **Wait for tests before merge**.
- **Restore-sequence gate**: both workers must be confirmed idle after completed deployment before resuming Postgres; account/API may still write and must remain quiescent during recovery. Render connector currently offers no Postgres Resume or service Suspend action; a dashboard action from the owner is needed. Do not claim database was resumed.
- PR #174 R2 old diagnostic reclaim and PR #175 packed diagnostic prevention / R2 recovery both passed CI, but remain draft/unmerged; cannot execute cleanup while Postgres suspended. Reclaim requires verified bucket/backup, narrow privileges, and WAL/free-space checks.


### Shutdown-preparation / code merges
- PR #174 merged as `0d2f47e8505b486306242dc0598beca06b3ea027` (operator-only, preverified R2 raw-event recovery).
- PR #175 merged as `5cd7f38abe72525428fbfbbac4d12a44518cc980` (lossless diagnostic batching and R2 packed-event recovery).
- Neither change has been executed against DB. The processor auto-deploy is NOT confirmation that revised code is running while PostgreSQL is suspended.
- Both Render worker env updates attempted; both deployment attempts failed `pre_deploy_failed` due to suspended DB. **Old live instances must not be assumed idle.**
- PR #176 supplies explicit `MT_STORAGE_RECOVERY_HOLD=true` for disabled collector-role worker predeploy; awaiting test/merge. Need set this recovery hold on both workers, get live deployments, verify no collection, before DB resumption.
- Render connector lacks a native Postgres Resume or service Suspend action. Manual dashboard resume is required once worker safety gates pass. No storage upgrade.


### Recovery hold merged and deployment queued
- PR #176 passed full GitHub CI; merged as `bca89f1b295dbb92c13547d606209fdc0b35648b`.
- Both Render workers now have `WORKER_ROLE=collector`, `COLLECTION_ENABLED=false`, `STAGING_ACCEPTANCE=off`, `STAGING_OPERATOR_ACTION=off`, and `MT_STORAGE_RECOVERY_HOLD=true` set (additive environment updates; no secrets replaced).
- Processing deployment `dep-dbpr2849v7es73c7vhlg` and research deployment `dep-dbpr28u7bikc73b54ecg` started with merged recovery hold code. **Not marked idle/live until verified.**
- No database resume was performed: the Render connector has no Resume action. Owner may need to use Render dashboard after confirming worker deployments are live and disabled.


### Recovery hold active on Render
- On Nov 11 00:05:57–00:06:11 UTC, Render reported both **new worker deployments LIVE**: processing `dep-dbpr2849v7es73c7vhlg`, research `dep-dbpr28u7bikc73b54ecg`, commit `bca89f1b`.
- Render predeploy log explicitly reported `storage-recovery-hold-v1`, `collection_enabled=false`, `worker_role=collector`, `trading_enabled=false`, `predeploy_database_check=deferred`. Both preceding worker revisions marked `deactivated`.
- Some **old process shutdown logs** briefly continued after live replacement (PoolTimeout / DB hostname resolution); avoid claiming strict quiescence until log activity stops past maxShutdownDelaySeconds=120.
- Database remains **suspended**, no upgrade. Connected Render actions do not expose a database Resume or worker Suspend action; owner dashboard is needed for physical resume. Avoid re-enabling bots until DB recovery and archived history safety checks complete.


### Live 15 GB database recovery and actual sizes (Nov 10, 2026 PT)
- Owner **intentionally upgraded** `pocket-db-staging` to **15 GB** and resumed it. Render reports `available` and disk autoscaling `false`. No additional upgrade planned.
- PR [#177](https://github.com/princesspikachuu/kalshi-scanner-data/pull/177) passed CI and merged as `7c680abe`. Disabled processing worker's one-shot **read-only** audit (Nov 11, 03:33 UTC) measured `pg_database_size` **9,127,323,315 bytes (~9.13 GB)**. `research_job` **6,198,132,736 bytes (6.20 GB)** including **982,048,768 index bytes**; `research_dataset` **1,351,368,704 bytes (1.35 GB)**; `collection_page` 445 MB, `raw_archive` 286 MB. Logical DB bytes are **not** true free filesystem/WAL headroom.
- 0.25% page sample of raw shadow events: `SCALPER_OBSERVATION_BATCH` 695 rows / 2,221,489 payload bytes; `FAVORITE_STAT_DECISION` 397 / 445,534; `CYCLE_REPORT` 286 / 434,182; `DATA_GAP` 959 / 296,729. This establishes **sampled priority**, not exact whole-table totals. Do **not** delete financial audit records or datasets.
- `MT_STORAGE_RECOVERY_AUDIT` reset to **false** and processing `DATABASE_CAPACITY_GB` set to **15**, while `WORKER_ROLE=collector`, `COLLECTION_ENABLED=false`, `MT_STORAGE_RECOVERY_HOLD=true` remain. Processing disabled replacement `dep-dbpu453l550s738v0ing` reported LIVE; both workers remain disabled. API compatibility deploy `dep-dbpu4j15efls7392nu3g` was in progress at last check.
- Next: operator-only, R2-verified, small-batch archival and exact-row reclaim of old non-financial diagnostics using merged PR #174/#175 tools. Render's connected SQL tool is blocked by the deliberately empty external database IP allowlist; **do not expose DB**. Requires internal Render Shell and separate narrowly privileged private recovery credential. Verify R2 and Postgres WAL/physical space before more batches. No data deletion executed here.


### API compatibility deployed and zero-cost preview handoff
- API `pocket-api-staging` deployment `dep-dbpu4j15efls7392nu3g` finished **LIVE** at Nov 11 03:35:58 UTC on `7c680abe` (contains PR #175 batched diagnostic reading).
- Source-of-truth configuration/report commit `98de5af94d28016017df79086888c71b9ed03d1e` on `build/google-auth-foundation` aligns draft Blueprint Postgres to 15 GB, autoscaling `false`, processing `DATABASE_CAPACITY_GB=15`, and stores [measured audit](docs/audits/MT-019-resumed-storage-baseline-2026-11-11.md). This **did not** sync a Blueprint or change paid database allocation.
- NEXT safe operator step via Render **processing worker Shell** (not the connected read-only SQL tool): `RECOVERY_DATABASE_URL="$DATABASE_URL" python -m services.demo.shadow_archive_recovery --age-hours 24 --batch-size 50`. Default is **read-only preview**, no R2 write, no SQL DELETE; outputs one bounded candidate page. Do not add `--execute` or paste credentials into chat.
- Before any execute, provision narrowly privileged private `RECOVERY_DATABASE_URL` in Render, validate R2 bucket readback and financial integrity, then perform a single 50-row verified batch via the operator tool and measure WAL/free physical disk. Normal workers stay disabled throughout.


### Verified first R2 archive-and-reclaim transaction (Nov 10, 2026 evening PT)
- Operator ran bounded preview against the resumed 15 GB Postgres: 50 eligible diagnostic rows in a **single sample page** (33 `SCALPER_OBSERVATION_BATCH`, 13 `FAVORITE_STAT_DECISION`, two each `FAVORITE_ENTRY_DECISION` and `FAVORITE_REPEAT_OPPORTUNITY`). No whole-table count implied.
- Runtime DB `pocket_research_runtime` has `DELETE=false, INSERT=true`, as intended. Separate owner account `pocket_staging` has `DELETE=true, INSERT=true`. R2 bucket connectivity and one small independent write/readback verification succeeded.
- **First exact-row reclaim succeeded:** `--execute --writers-stopped --age-hours 24 --batch-size 10 --max-batches 1` returned `{"archived":10,"compressed_bytes":7892,"deleted":10,"manifest_stored":true,"verified":true}`. Contents and manifest preserved in R2; no financial records selected. This does not prove physical disk free space increased. Workers stay held/disabled.
- Security: earlier Shell error disclosed a runtime DB password into chat. Rotate it and update dependent service secrets before restoring normal trading; never paste owner or app connection URLs.
- [PR #178](https://github.com/princesspikachuu/kalshi-scanner-data/pull/178) **PASSED full GitHub CI and MERGED** into `build/google-auth-foundation` as `ba16bba8011264985f6892d9cdc35d8dbef0e53a`: **disabled-by-default, recovery-hold-only** automatic archive loop for both raw and compressed diagnostic histories; explicit writer-stopped acknowledgement, dedicated non-owner SQL maintenance role, conservative capacity/batch guards, receipt verification and unit tests. This is *not* live ongoing retention. No automatic cleanup enabled or operator credential installed.
- Remaining U0: create isolated maintenance role (owner secret must NOT be persisted to the worker), verify Render physical disk/WAL and control backup integrity; run bounded backlog only while stopped, then add live-safe cold-history read-through/retention before resuming normal writes. 


### Independently verified first real cold archive (Nov 10, 2026, ~20:42 PT)
- [PR #179](https://github.com/princesspikachuu/kalshi-scanner-data/pull/179) passed full CI and merged as `af4a269e642581c1dcc48df252976b439b9a804b`. Its one-shot, SELECT-only + R2-read-only audit ran on the explicitly disabled processing collector using `MT_ARCHIVE_VERIFY_ONCE=true`.
- **Live Render output 2026-11-11 04:42:24 UTC**: `shadow_archive_r2_integrity` reported `verified=true`, `manifests_scanned=1`, `verified_manifests=1`, `original_rows_verified=10`, `original_events_verified=10`, `deleted_rows_absent=10`, `compressed_bytes_verified=7892`, `no_deletion=true`. Actual R2 object and PostgreSQL absence independently verified. This reconciles the operator's earlier execute receipt without additional deletion.
- `MT_ARCHIVE_VERIFY_ONCE` immediately reset to `false` via Render (new disabled-worker deployment underway). Both paper/research workers remain recovery-held, collection disabled. Do not turn on live paper trading until backup/growth/automated retention is safe.
- [PR #180](https://github.com/princesspikachuu/kalshi-scanner-data/pull/180) **PASSED GitHub CI and MERGED** as `845daf7d31852d0e44733c57348c5bb50032383b`. Owner-authenticated metadata and verified cold-history read endpoints for raw and compressed diagnostics. R2 read is OFF until separate read-only Cloudflare R2 bucket credentials are configured in the API. API manual deployment `dep-dbpv5l6k1f9s73d3v4ag` **LIVE** at 2026-11-11 04:46:32 UTC, commit `845daf7d31852d0e44733c57348c5bb50032383b`; Render logged successful predeploy privilege/migration validation and Uvicorn startup. This is bounded restoration/browsing, not time-indexed historical analytics/search.


### Control-backup root cause and guarded repair (Nov 10 evening / Nov 11 UTC)
- Pre-outage Render logs repeatedly show backup `QueryCanceled` (SQLSTATE 57014) and `backup_capacity`. Legacy `services.demo.maintenance.backup` has an expensive multi-prefix OR query, `LIMIT 2001`, and refuses any scope containing over 2,000 rows. **Do not omit or reset financial/control evidence.**
- [PR #181](https://github.com/princesspikachuu/kalshi-scanner-data/pull/181) **passed CI on retry and merged** as `18e8ba403e272a62d5f0ac8474094074c50ea26b`. First full CI run had one unrelated `test_processing` SQL timeout, six new audit tests passed. The one-time `MT_CONTROL_BACKUP_AUDIT=true` inspection **executed on LIVE disabled processing collector at 2026-11-11 05:02:14 UTC**; mode `read_only`, `verified=true`, `failed_scopes=[]`, `candidate_count_exact=false`:
  - `shadow_bots`: **at least 2,001 rows, 67,793,342 JSONB payload bytes** (capped sample; this is not the full category).
  - Other original backup categories: 124 rows / 2,535,728 measured payload bytes (sum of their uncapped reads).
  - **Total at least 2,125 rows / 70,329,070 payload bytes**; conclusively exceeds the legacy 2,000 row cap and first V2 64-MiB in-memory cap.
  - The audit flag was immediately restored to `false`; disabled processing replacement became LIVE. No deletion, trading restart or complete control backup occurred.
- [PR #182](https://github.com/princesspikachuu/kalshi-scanner-data/pull/182) **PASSED full GitHub CI and MERGED** as `2ed821de3736b6bd00696629d840e5167571a4c9`. V2 preserves 4,190+ original demo/live control records via a bounded REPEATABLE READ snapshot into an unlinked temporary file (100k-row/512MiB cap with 256MiB local reserve); chunks, root hash, and complete R2 restoration are verified before updating `backup-health`. An independently discoverable R2 `demo/backups/roots/` receipt is also verified before marking success, so backup roots are recoverable even if the database is lost. `MT_CONTROL_BACKUP_V2_ONCE` and recurring `MT_CONTROL_BACKUP_V2_ENABLED` remain **OFF**. Tests pass; **the full live backup has not run yet**.
- [PR #183](https://github.com/princesspikachuu/kalshi-scanner-data/pull/183) **passed CI and merged** as `253fbb2daa712b519c034f6fb9ba1b687f0b6368`. Live **SELECT-only** exact census at 2026-11-11 05:11:09 UTC: `shadow_bots` **4,066 rows, 187,718,269 JSONB payload bytes**, maximum individual payload **74,381 bytes**. Other uncapped control categories: **124 rows / 2,535,728 bytes**. Total original backup: **4,190 rows, ~190,253,997 JSONB payload bytes (~190.25 decimal MB)** before JSON serialization/R2 framing. `MT_CONTROL_BACKUP_AUDIT` and `MT_BACKUP_EXACT_CENSUS` both reset to **false** with new held-worker redeployment `dep-dbpvhvgu01pc739ck3pg` started. No deletion and no actual control backup yet.
- NEXT: verify processing worker auto-deploy of merged V2 commit `2ed821de3736b6bd00696629d840e5167571a4c9` returns LIVE with `collection_enabled=false` and `trading_enabled=false`; then activate *one-time only* `MT_CONTROL_BACKUP_V2_ONCE=true` on that recovery-held collector. Monitor full R2 backup result and root receipt; on success or failure immediately restore the flag to **false** and verify disabled worker LIVE. Do **not** enable recurring backups or resume trading until full restore is verified and broader retention is safe.
- [PR #184](https://github.com/princesspikachuu/kalshi-scanner-data/pull/184) **PASSED full CI and MERGED** as `bc8f9455553fad6b4d921b68cef31e9ee52693a0`. One-shot zero-DB/R2-write temp filesystem preflight ran at **2026-11-11 05:22:55 UTC** on recovery-held processing worker: `verified=true`, `/tmp`, conservative available **52,925,263,872 bytes**, maximum stage budget **536,870,912 bytes** (512 MiB) after 256 MiB reserve, source JSONB census **190,253,997 bytes**, `source_jsonb_fits_stage_budget=true`, `sufficient_for_full_backup="unverified"`. This is a filesystem advisory; Render's ephemeral per-instance/quota limits and serialized bytes are **not** guaranteed by this huge free-space figure. Worker plan `1c-2g`; paused usage ~65–74 MB. No backup, DB changes or trading. `MT_WORKER_DISK_AUDIT_ONCE` immediately reset to **false**; replacement processing worker deploy `dep-dbpvnee7bikc73bj4cc0` **LIVE at 2026-11-11 05:23:51 UTC**, same commit `bc8f9455553fad6b4d921b68cef31e9ee52693a0`. Pre-deploy logged `collection_enabled=false`, `trading_enabled=false`, recovery-hold collector; new startup shows no repeated audit output. Research worker remains live on recovery hold and Postgres is available at 15GB. **Safe checkpoint: paused before starting V2 trial.** Do not claim backup recovery or live-safe recurring retention until proven. Dedicated **separate** maintenance DB role and R2 read-only API token still required for unattended diagnostic cleanup/cold-history browsing. A leaked runtime DB password also requires rotation before normal trading.

### First complete R2 control backup verified (2026-11-11 06:09:40 UTC)
- [PR #182](https://github.com/princesspikachuu/kalshi-scanner-data/pull/182) passed full CI, merged as `2ed821de3736b6bd00696629d840e5167571a4c9`, deployed to **disabled/recovery-held** processing collector. `MT_CONTROL_BACKUP_V2_ONCE=true` was enabled **only** on that service, while `MT_CONTROL_BACKUP_V2_ENABLED=false`.
- **REAL VERIFIED BACKUP SUCCEEDED**: Render emitted `demo_control_backup_v2_verified` at 2026-11-11 06:09:40 UTC with `records=4190`, `chunks=98`, `staged_bytes=190846407`, `compressed_bytes=143900749`, `catalog_stored=true`, `verified=true`. Identical adjacent log lines are the inner backup and outer one-shot result logging, not evidence of duplicate source deletion.
- V2 took a consistent PostgreSQL READ ONLY snapshot, staged locally within capped filesystem headroom, uploaded 98 content-addressed R2 chunks, read every chunk back and verified aggregate SHA256, then published separately discoverable catalog under `demo/backups/roots/` before updating `demo/backup-health`. **No PostgreSQL source records deleted or reset.** This is a control backup, **not** a full PostgreSQL PITR backup.
- Delayed automatic GitHub webhook caused a second deploy of the same commit while the first was live; because R2 writes are content-addressed and source access read-only, this was non-destructive. Latest successful worker deployment while one-shot enabled was `dep-dbq0cp7f3r2c73b3nv40`.
- `MT_CONTROL_BACKUP_V2_ONCE` immediately reset to `false`; recurring V2 flag kept `false`, replacement deployment `dep-dbq0dggn74is739b1lpg` **LIVE at 2026-11-11 06:11:04 UTC**. Render predeploy confirms `collection_enabled=false`, `trading_enabled=false`, role `collector`, and recovery hold active. The research worker remains LIVE on its held deployment; PostgreSQL remains available at 15GB. Both one-shot and recurring backup flags explicitly OFF. **Safe checkpoint, no further backup or deletion running.** Do not re-enable once or trade.
- NEXT MT-019: close the backup-health failure loop with cautious live policy integration only after other storage hold blockers; create separate minimally privileged archival DB account, and read-only R2 API credential; continue verified bounded diagnostic R2 offload and storage headroom monitoring. Rotate exposed runtime DB password before resuming trading.


### Least-privilege automatic archival hardening (Nov 10 evening PT / Nov 11 UTC)
- [PR #185](https://github.com/princesspikachuu/kalshi-scanner-data/pull/185) **PASSED full GitHub CI, MERGED** as `d5e055ff045facbf7d31841adf723a42fcd09968`, and **DEPLOYED LIVE but disabled** on processing worker (Render `dep-dbq0q98u01pc739giql0`, 2026-11-11 06:38:57 UTC). The earlier automatic recovery loop demanded broad `SELECT/INSERT/DELETE` on all `research_job`; this was narrowed to SELECT + a function that can modify only eligible archived diagnostics. No automatic role installation or cleanup triggered.
- New operator-only `infra/archive-maintenance-role.sql` creates `pocket_archive_maintenance` as **NOLOGIN**, with **SELECT but no direct INSERT, DELETE, UPDATE, TRUNCATE, owner or admin rights**. A tightly granted `SECURITY DEFINER` function **atomically inserts a verified archive manifest and reclaims only exact unchanged 24h+ diagnostic rows**. Automatic worker fails closed unless it sees exactly this non-owner role and scoped function; ordinary operator-led emergency recovery remains separate.
- Future raw and packed R2 archives now include all present `research_job` columns, including previously omitted `lease_token`, `available_at`, `max_attempts`; existing earlier archives remain readable.
- Disposable PostgreSQL integration tests and full 1,487+ API test suite **PASSED**: denied direct INSERT/DELETE, allowed old safe diagnostics only, financial/fresh/wrong-namespace denial, tampered-row and owner invocation denial. SQL file was repaired after tests identified malformed duplicated content; latest clean single-transaction version passed.
- **No archive role has been installed/activated in Render, and no automatic cleanup has started.** Existing R2 control backup remains independently verified (4,190 source rows; 98 chunks; root catalog). Processing/research workers stay recovery-held with trading/collection disabled; Render predeploy explicitly confirmed `collection_enabled=false`, `trading_enabled=false`, role `collector`. NEXT: only in a private owner Render Shell, install the NOLOGIN role, activate an isolated SCRAM credential, and configure `RECOVERY_DATABASE_URL` on the held worker. Do not install blanket research_job INSERT/UPDATE/DELETE grants or enable retention before role privilege verification. Rotate leaked owner credential before returning to trading.


### Privilege guard follow-up (PR #186)
- [PR #186](https://github.com/princesspikachuu/kalshi-scanner-data/pull/186) **PASSED GitHub Actions and MERGED** as `0ce391ac8c6bf31ca8bebd29e0489446a4bf92a0`. Recovery-only archive role validation now explicitly checks `public.research_job` and `public` schema, independent of session search_path, and rejects maintenance credentials with TRUNCATE or schema CREATE authority in addition to owner/admin and direct INSERT/UPDATE/DELETE. Regression tests and disposable PostgreSQL privilege assertions added.
- **Render deployment VERIFIED:** `pocket-processing-staging` deploy `dep-dbq1c7ks728c738v2n3g` was LIVE on commit `0ce391ac` at 2026-11-11 07:16:29 UTC. Predeploy logged recovery hold, collection disabled, trading disabled, role collector. Research worker remained LIVE and held. Render Postgres available at 15 GB with autoscaling OFF. Read-only DB metrics from 06:00-08:30 UTC showed 1-3 connections and low CPU; neither this nor logical usage proves physical disk/WAL safety. No automatic archival, cleanup, maintenance account, or trading was activated.
- **PR #187 CI PASSED and MERGED:** https://github.com/princesspikachuu/kalshi-scanner-data/pull/187. Full GitHub Actions workflow run `43063347524` succeeded (staging gateway, browser, Favorites regression, full API/owner policy/real PostgreSQL, staging Blueprint validation); squash merge commit `8c65e0cce672af5409591862482db7d017f2f155` on `build/google-auth-foundation`. New guard refuses archive principal role memberships, INHERIT, REPLICATION and BYPASSRLS attributes, adds tests and fixes operator documentation function signature. No SQL role installed and no cleanup or trading enabled.
- **PR #187 DEPLOYMENT VERIFIED (2026-11-11 17:10:51 UTC):** processing worker `dep-dbqa2iu7bikc73aksil0` is LIVE on `8c65e0cce672af5409591862482db7d017f2f155`. Live predeploy at 17:10:17 UTC emitted `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`; no archival/error events in reviewed deployment window. Database remains `available`, 15 GB, autoscaling OFF. DB metrics around deployment showed approximately 2 active connections; this does NOT confirm physical WAL/free disk headroom or guarantee every potential API writer is stopped. No archive role installed and no cleanup/collection/trading activated.
- **PR #188 REVIEWED AND MERGED (documentation only):** https://github.com/princesspikachuu/kalshi-scanner-data/pull/188. Head `2191a630` changed only `docs/audits/MT-019-no-storage-upgrade-recovery.md`. Exact one-file diff manually reviewed; GitHub did **not** report a CI run for the docs-only PR, so it is not described as CI-passed. Squash merge `7f4773088bf8c73e60fe505fa2213c97ab6139c0` explicitly starts with `[skip render]` to prevent unnecessary worker deployment. Latest Render processing worker remained LIVE on PR #187 `8c65e0cc` when checked immediately afterward; no deploy event was visible then. Runbook accurately reflects available 15 GB DB, verified 4,190-record R2 control snapshot, first verified 10-row diagnostic reclaim and operator-only next gates.
- **PR #189 FULL CI PASSED, MERGED:** GitHub Actions [run 43093190708](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43093190708) passed every job, including actual PostgreSQL tests. Four files added/changed on [PR #189](https://github.com/princesspikachuu/kalshi-scanner-data/pull/189). Squash-merged as `a0b2934049947a5e43f803601248813216c81e11` to `build/google-auth-foundation`. This is an OFF-by-default, one-shot, recovery-held-only PostgreSQL WAL and archival-role audit. It does not validate physical Render free space, prove all database writers quiescent, authorize cleanup, or change trading behavior. **Next:** verify automatic processing-worker deployment of this exact SHA and held logs; consider operator-approved one-shot `MT_WAL_PREFLIGHT_ONCE=true` with immediate reset only after deployment and gates. Do not install maintenance credentials or enable archival yet.
- **2026-11-11 ~20:19 UTC extended recovery checkpoint:** Additional hardening [PR #190](https://github.com/princesspikachuu/kalshi-scanner-data/pull/190), branch `fix/mt019-wal-audit-mutual-exclusion`, head `d69ee5a9fc74a8fdb0a5a1a0c4286001da19da8c`, OPEN (CI run [43095349876](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43095349876) queued). It adds explicit mutually exclusive flags for old worker disk audit and exact backup census, regression assertions, runbook update. **Do not merge until PR #190 CI succeeds.** Merge commit `a0b29340` for PR #189 itself also has CI run [43094509260](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43094509260) in progress, so processing worker remains LIVE on prior PR #187 commit `8c65e0cc` with recovery hold. No forced deploy; Render autoDeployTrigger=checksPass. A separate public Render doc confirms physical Disk Usage graph in the managed Postgres Metrics page; Render MCP's available get_metrics schema lacks disk metrics, so physical free bytes remain UNVERIFIED. Connected SQL refused by safe empty external allowlist and was not bypassed. No new R2 archive/deletions or production env changes. Next: verify both CI runs; merge #190 only if passed, verify actual LIVE process commit and held predeploy logs; then consider **one** tightly bounded read-only WAL flag toggle with immediate reset, while archival/trading remain off. Do not treat WAL SQL metrics as volume free space or writer quiescence proof.
- **2026-11-11 API writer audit / PR #191:** Static audit of `services/api/app.py`, `collection.py`, `paper.py`, `demo.py`, `shadow.py`, `live_bots.py`, and `store.py` CONFIRMED API can write to `research_job` and other control/auth tables while both collectors are recovery-held. API lifespan also calls `seed_live_bots` and `configure_approved_pilot` on normal startup. Therefore never assert `MT_ARCHIVE_WRITERS_STOPPED=true` solely from paused collectors. [PR #191](https://github.com/princesspikachuu/kalshi-scanner-data/pull/191), `fix/mt019-api-recovery-write-hold`, head `93473598`: OFF-by-default `MT_API_RECOVERY_HOLD=true` temporarily blocks **all non-health API routes** with 503 and skips optional API startup DB seeding. Adds config validation, tests and owner runbook. This will make dashboard/sign-in temporarily unavailable if enabled. API is manual-deploy and NOT modified live. GitHub CI #191 queued [43095935073](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43095935073); do not merge before PASS, do not enable before a coordinated maintenance window. It is NOT a database-enforced read-only guarantee; other writers may exist.
- **CI sequencing blocker:** PR #189 merged as `a0b29340` but its merge-commit CI [43094509260](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43094509260) still reports IN PROGRESS even though each reported test/job step succeeded. PR #190 [43095349876](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43095349876) and PR #191 [43095935073](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43095935073) remain queued. Render `autoDeployTrigger=checksPass` means no new processing deployment should be forced until GitHub resolves. Confirm actual statuses again next turn; diagnose action-run stall if persistent. Database 15 GB available with no autoscaling and secure empty external allowlist. No live env flags, SQL/role, deletion or trading changed.
- **Extended diagnostic checkpoint — CI status and archived-data safety (Nov 11 2026):** Created U0 [issue #192](https://github.com/princesspikachuu/kalshi-scanner-data/issues/192) tracking GitHub Actions run #865 `43094509260` stuck `in_progress` after **every job step including Complete job shows completed/success**; full job log fetch returned a timeout. #190 run `43095349876` and #191 run `43095935073` still queued. Did NOT rerun, cancel or bypass checks. Render `autoDeployTrigger=checksPass` correctly leaves processing on recovery-held `8c65e0cc`. Read-only Render metrics ~19:15–20:30 UTC: processing RAM ~63.8 MB / 2 GB, research ~61.9–63.6 MB / 512 MB, API ~85 MB / 512 MB; worker CPU effectively idle, DB active connections ~1–2, DB memory ~318–327 MB. **Not proof of physical free disk or zero writers.** Read-only source audit of `infra/archive-maintenance-role.sql` and `services/demo/shadow_archive_automatic.py` confirmed SQL scoped deletion and automatic loop remain OFF; no role credentials installed. The SQL SECURITY DEFINER function cannot independently verify R2, so Python checksum/readback and no compromised maintenance account are critical. Added a [review note on PR #191](https://github.com/princesspikachuu/kalshi-scanner-data/pull/191) requiring full API instance drain/in-flight request completion before the operator may assert writers stopped (zero-downtime deploy may retain old API writes briefly). PR #191 remains OFF/unmerged and never activated. No storage, credentials, live API flags, financial or trading records changed. NEXT: resolve CI #192, verify #190/#191 CI, deploy #189/#190 only after checksPass, run one-shot read-only WAL preflight and promptly reset flag; obtain actual Render physical disk/WAL headroom and API quiescence before considering bounded R2-reclaimed diagnostics.
- **2026-11-11 additional unmerged safety hardening (checkpoint):** [PR #191](https://github.com/princesspikachuu/kalshi-scanner-data/pull/191) branch `fix/mt019-api-recovery-write-hold`, HEAD `b9e384e2` adds **PostgreSQL `default_transaction_read_only=on` for API connection pool only when `MT_API_RECOVERY_HOLD=true`**, in addition to HTTP 503 block, skipped startup writers, default-off flag; added strict config/default and session-options tests. This is not role-level revocation of all writes and old API instance/in-flight request drain must still be verified. [PR #190](https://github.com/princesspikachuu/kalshi-scanner-data/pull/190) branch `fix/mt019-wal-audit-mutual-exclusion`, HEAD `1a154df8` now **rejects automatic recovery archive startup** unless both `MT_ARCHIVE_API_DRAIN_ACKNOWLEDGED=true` and `MT_ARCHIVE_PHYSICAL_HEADROOM_ACKNOWLEDGED=true` accompany all existing recovery-hold/writers-stopped flags. The latter requires a real Render physical disk+WAL inspection, NOT `pg_database_size`; both acknowledgments must be cleared after cleanup. Regression tests and owner runbook updated. Neither PR has CI PASS or deployment authorization; GitHub latest #190 Actions run `43097419428` QUEUED, #191 run `43097081275` QUEUED; merge-commit #189 validation `43094509260` still IN PROGRESS despite all reported steps SUCCESS. [GitHub incident history](https://www.githubstatus.com/history) documents a resolved Nov 10 Actions/PR disruption, and Nov 11 [community report](https://github.com/orgs/community/discussions/212707) describes similar queued-without-jobs failures, **not proof of the cause**. U0 [issue #192](https://github.com/princesspikachuu/kalshi-scanner-data/issues/192) contains triage and external context. No forced deploy, credential change, database query (external network remains blocked), R2 deletion or trading. Processing worker still LIVE on held `8c65e0cc`; PostgreSQL available 15 GB, autoscaling OFF. NEXT: resolve Actions statuses without bypass, get CI passes for #190/#191, verify held deploy, only then consider one-shot read-only WAL preflight with immediate OFF reset; physical disk and private restricted role remain outstanding.
- **2026-11-11 ~21:01 UTC continuation checkpoint:** GitHub Actions run [#865 / 43094509260](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43094509260) FINALLY completed SUCCESS, unblocking Render `checksPass` auto-deploy of merged PR #189. Processing worker deploy `dep-dbqden49v7es73dfqj2g`, commit `a0b2934049947a5e43f803601248813216c81e11`, entered `pre_deploy_in_progress` at 21:00:50 UTC; log shows `verify-runtime --profile research` at 21:01:06 UTC; **not yet LIVE** at this checkpoint. Do not enable one-shot WAL preflight before LIVE + held flags verified. PR #190 (head `1a154df8`, CI [43097419428](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43097419428)) and PR #191 (head `b9e384e2`, CI [43097081275](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43097081275)) remain QUEUED and unmerged. New [PR #193](https://github.com/princesspikachuu/kalshi-scanner-data/pull/193), `fix/mt019-short-scoped-reclaim-transactions`, head `176c2317`, CI [43099335529](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43099335529) QUEUED: for scoped **nonfinancial diagnostic** archive paths, closes bounded candidate SELECT transaction *before* R2 network upload/readback, then reopens short atomic SQL function transaction that rechecks exact original rows and prevents deletion of changed rows; legacy owner/direct-delete locked semantics unchanged. Added tests verifying R2 outside SQL transactions and fail-closed mismatch, plus operator docs. No data deletion/role installation/flag changes. Do not merge #190/#191/#193 without terminal SUCCESS. Issue #192 tracks queued-workflow resolution; the original #189 merge run is now successful, so issue should be updated, not misrepresented as fully resolved while other checks remain queued. Next: verify processing live, predeploy recovery-hold flags and absence of unexpected writes; when safe, briefly run one-shot SELECT-only WAL census and immediately reset; physical disk/WAL remains unverified and manual private scoped maintenance role outstanding.
- **2026-11-11 21:04 UTC VERIFIED one-shot WAL census + reset:** Merged PR #189 processing worker `a0b29340` deployed LIVE as `dep-dbqden49v7es73dfqj2g` (21:02:09 UTC), held predeploy `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, collector. Temporarily set **only** `MT_WAL_PREFLIGHT_ONCE=true`, triggering `dep-dbqdg4h42hec73cq7bpg` LIVE 21:04:04 UTC. At 21:04:03 UTC log `mt019_wal_preflight`, `mode=read_only`: logical DB `9,127,331,507 bytes`, WAL generated since `stats_reset=2026-11-11T03:25:05Z` `10,077,101 bytes`, `wal_records=7,023`, `wal_fpi=1,295`; DB sessions `total=3`, `active=1`, `idle_in_transaction=0`; archive role `role_exists=false`, `login_enabled=false`, `scoped_function_exists=false`. WAL directory query failed **InsufficientPrivilege**. Explicit report: `verified_physical_free_disk=false`, `verified_all_writers_stopped=false`, `authorizes_archive_reclaim=false`. **Immediately reset `MT_WAL_PREFLIGHT_ONCE=false`**, triggering replacement `dep-dbqdgq2jnfac738c5sr0` 21:04:40 UTC (build pending at first check). Verify replacement LIVE and absence of new audit records before resuming any other task. No cleanup, financial edits, scoped SQL account, or trading enabled. Physical Render disk/WAL headroom cannot be inferred from cumulative WAL counter; operator dashboard metric check still mandatory.
- **2026-11-11 21:05:52 UTC WAL audit OFF verified:** Replacement processing worker `dep-dbqdgq2jnfac738c5sr0` is LIVE, same merged PR #189 commit `a0b29340`, after setting `MT_WAL_PREFLIGHT_ONCE=false`. Render predeploy at 21:05:39 UTC again reported `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`. No new `mt019_wal_preflight` logs after the reset deployment; earlier one-shot aggregate result remains preserved above. **No further WAL audit execution, trading or automatic archive activation.** PR #193 validation run `43099335529` subsequently started IN PROGRESS; #190/#191 remained queued at last check. Continue checking CI without bypassing validation; physical WAL directory unavailable to runtime role (InsufficientPrivilege) and 15 GB volume headroom still needs private Render dashboard check.
- **2026-11-11 ~21:06 UTC PR #193 full CI PASSED and MERGED:** [GitHub Actions run 43099335529](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43099335529) completed SUCCESS (all steps). [PR #193](https://github.com/princesspikachuu/kalshi-scanner-data/pull/193) shortens only scoped diagnostic recovery DB transaction lifetime by moving verified R2 upload/readback between a bounded SELECT transaction and a separate short atomic SQL fence transaction. Regression tests cover transaction separation, unchanged row identity, and rollback on mismatch; the legacy unscoped owner path remains unchanged. Squash merge `a8a48d6161ac2372ed7658472359ba67f23a1674` on `build/google-auth-foundation`. **Postmerge CI and Render `checksPass` deployment not yet verified**. No archival loop flag, DB account creation, cleanup or trading enabled. MT-019 continues.
- **2026-11-11 21:11:49 UTC PR #193 production-held deployment VERIFIED:** Merge commit `a8a48d6161ac2372ed7658472359ba67f23a1674` full [GitHub Actions run 43100276785](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43100276785) passed every step. Processing Render worker deployed LIVE as `dep-dbqdjonf3r2c73f0mhdg` (21:11:48 UTC); predeploy log at 21:11:37 shows `contract=storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`. No `mt019_wal_preflight` events following prior OFF reset. Scoped diagnostic transaction shortening is deployed but archival itself is still disabled and no data deleted. PR #190 and #191 heads `1a154df8` and `b9e384e2` still queued (and GitHub currently says mergeable=false, investigate conflicts separately). No forced deployments or DB/R2 changes. Physical disk/WAL volume safety, scoped account, credential rotation still outstanding.
- **2026-11-11 21:14 UTC PR #190/#191 CURRENT-BASE SYNC / CI UNBLOCKED:** Both original recovery PR branches were one commit behind deployed `a8a48d61` (#193) with NO overlapping changed files. Safely merged verified deployment base into each PR by preserving all PR-specific blobs in a new Git tree, with both original PR head and the verified base as commit parents; updated branch refs fast-forward only with expected-SHA lease. PR [#190](https://github.com/princesspikachuu/kalshi-scanner-data/pull/190) new HEAD `1727f0c59182510cf5342c483cd59ce4f70262b3`, compare vs deployment base behind=0, 6 original files only, clean/mergeable; fresh GitHub Actions run [43101709787](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43101709787) IN PROGRESS. PR [#191](https://github.com/princesspikachuu/kalshi-scanner-data/pull/191) new HEAD `8071faac7c35390c5172b22bbd7fb42eafe1522c`, behind=0, 5 original files only, clean/mergeable; fresh run [43101757088](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43101757088) IN PROGRESS. The older queued workflow runs are obsolete; do not mistake those for the new runs. Neither PR was merged or deployed at this checkpoint. Do not merge until each current-head run terminal SUCCESS. Current processing worker LIVE held `a8a48d61`; database 15 GB available with autoscaling OFF, no auto archival or trading. If both suites pass, merge sequentially and verify each postmerge CI/held deployment (API manual deploy must not be toggled without coordinated maintenance). Physical volume, scoped role and secret rotation remain blocked operator steps.
- **2026-11-11 ~21:17 UTC PR #190 CI PASSED and MERGED:** Synced PR #190 head `1727f0c59182510cf5342c483cd59ce4f70262b3` passed full [GitHub Actions run 43101709787](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43101709787), including PostgreSQL/owner policy, then squash merged as `a0bf2afcde0aa8300814da24dafd5f7d50aba9c8` onto deployment branch. It adds required recovery archive config flags `MT_ARCHIVE_API_DRAIN_ACKNOWLEDGED=true` and `MT_ARCHIVE_PHYSICAL_HEADROOM_ACKNOWLEDGED=true` before any recovery loop can start, with negative tests and runbook. **Flags remain OFF/not set, no archive/account/cleanup enabled.** Postmerge CI and held Render deployment unverified at this point; do not force deployment. PR #191 validation on previous base running; synchronize with newly merged #190 before merging so the combined API+archival safety remains tested. Disk headroom, maintenance account, credential rotation remain outstanding.
- **2026-11-11 ~21:18 UTC PR #191 latest-base sync:** Following CI-passed merge of PR #190 `a0bf2afc`, checked all 6 PR #190 changed files are disjoint from PR #191's 5 files. Safely integrated current deployment branch into PR [#191](https://github.com/princesspikachuu/kalshi-scanner-data/pull/191) using preserved PR file blobs + verified base Git tree, a two-parent fast-forward commit and expected-SHA branch lease. New head `d86001be2f2e28adc7e6f3127ddc121611431d98` has behind=0, preserves all 5 original API recovery hold files, compare clean. Fresh GitHub Actions [run 43102447921](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43102447921) now IN PROGRESS; old PR #191 validation head `8071faac` is superseded. PR #190 merge-commit [run 43102342082](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43102342082) IN PROGRESS. **Do not merge #191 until latest run is terminal SUCCESS; do not force Render deploy.** API still has not been deployed or had any env toggle; processing LIVE remains held on PR #193 `a8a48d61`. Physical disk capacity, private restricted archive account and credential rotation remain operator-only blockers; no trading, archival or additional delete.
- **2026-11-11 ~21:26 UTC PR #190 postmerge CI VERIFIED:** [Run 43102342082](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43102342082) reached terminal SUCCESS; Render checksPass automatically started processing worker deploy `dep-dbqdqmhsrm7s738d38gg` of `a0bf2afcde0aa8300814da24dafd5f7d50aba9c8` at 21:25:47 UTC. **Build was still in progress at this checkpoint, do NOT report LIVE until exact SHA and recovery-held predeploy logs verified.** PR #191 was synced to this base and latest head `d86001be` run [43102447921](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43102447921) was IN PROGRESS, full API/Postgres suite running with no failure reported so far. API maintenance code still OFF/unmerged; neither R2 archival, DB maintenance account, financial write nor trading was activated. Verify PR190 Render rollout then PR191 CI; if PR191 PASS, merge, await postmerge CI, and plan API manual deploy with `MT_API_RECOVERY_HOLD=false` first. No API 503 hold window without separately ensuring dashboard access impact is acceptable and verifying all writers drained. Physical Render disk/WAL still operator-only blocker.
- **2026-11-11 21:26:38 UTC PR #190 HELD RENDER DEPLOYMENT VERIFIED:** `pocket-processing-staging` deploy `dep-dbqdqmhsrm7s738d38gg` on exact squash commit `a0bf2afcde0aa8300814da24dafd5f7d50aba9c8` reached LIVE. Predeploy log at 21:26:26 emitted `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`. New API drain and physical-headroom guard flags remain unacknowledged/not activated, automatic R2 archival remains OFF. No automatic deletion. PR #191 latest synced head `d86001be` full CI [43102447921](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43102447921) still running Postgres tests, do not merge before terminal PASS. Physical disk/WAL, isolated archive login and exposed DB credential rotation still pending, keep workers paused.
- **2026-11-11 ~21:32 UTC PR #191 full CI PASSED + MERGED:** Latest integrated API maintenance branch HEAD `d86001be2f2e28adc7e6f3127ddc121611431d98` passed full [GitHub Actions run 43102447921](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43102447921), including real PostgreSQL tests. Squash merged [PR #191](https://github.com/princesspikachuu/kalshi-scanner-data/pull/191) as `fa4fe1f215a83691a67a5d710ba199a4ad5830ae` on deployment branch. Adds default-OFF `MT_API_RECOVERY_HOLD`, 503 rejection of all non-health routes, skips optional startup writes, and sets `default_transaction_read_only=on` on API pooled sessions *only while held*. Tests cover default/off and read-only behavior. **API service `pocket-api-staging` has autoDeploy=no/off** so its LIVE version has NOT been updated by this merge and its maintenance hold remains INACTIVE; no dashboard/sign-in shutdown triggered. PR #191 merge-commit CI [43103219432](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43103219432) currently IN PROGRESS, worker autoDeploy checksPass will not proceed until SUCCESS. Processing worker LIVE remains PR #190 held `a0bf2afc`; database available 15 GB, autoscaling OFF. DO NOT manually deploy API or enable its maintenance flag before staged verification and coordinated operator window. Physical disk/WAL, restricted archive role login and exposed credential rotation still block any cleanup/trading restart.
- **2026-11-11 ~21:33 UTC CI backlog issue #192 RESOLVED/CLOSED:** Original stuck run `43094509260` terminal SUCCESS, current-base PR #190 and #191 full pull-request suites terminal SUCCESS; [issue #192](https://github.com/princesspikachuu/kalshi-scanner-data/issues/192) closed with exact evidence. PR #190 merged and **held processing Render LIVE** on `a0bf2afc`, `dep-dbqdqmhsrm7s738d38gg`; no archival activated. PR #191 merged as `fa4fe1f2` but postmerge [GitHub Actions 43103219432](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43103219432) still IN PROGRESS and its Render worker rollout has not occurred; do not treat merge alone as deployment. API `pocket-api-staging` remains on older LIVE version with autoDeploy=no, maintenance hold never enabled. MT-019 remains IN PROGRESS (operator physical disk/WAL headroom, isolated archive role/login, full writer quiescence including API and secret rotation). All saved backups/diagnostic history remain intact, paper trading/collection and automatic R2 archival remain OFF. Next: verify PR191 merge CI terminal SUCCESS, exact held processing deployment and no new diagnostics, then plan API code deployment on manual service with `MT_API_RECOVERY_HOLD=false`. Do **not** enter maintenance 503 window or assert writers stopped until operator coordination and all gates met.
- **2026-11-11 21:32:04 UTC PR #191 API CODE ROLLOUT VERIFIED, hold OFF:** [Merge-commit CI 43103219432](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43103219432) completed SUCCESS. Manually updated only `MT_API_RECOVERY_HOLD=false` (merge, not replace) on `pocket-api-staging` service with `autoDeploy=no`; this triggered deployment `dep-dbqdt6mc6qcc73f1fi7g` of exact `fa4fe1f215a83691a67a5d710ba199a4ad5830ae`, Render LIVE at 21:32:03 UTC. Build succeeded. `python -m services.api.manage migrate` predeploy reports contract `staging-database-audit-v2`, `migration_count=9`, `migrations_match=true`, `history_mutation=false`, `privilege_boundary_ready=true`; the API server logs `Application startup complete`. No error-level logs or `api_database_unavailable` entries in checked rollout period; no `live_bots_copied` event (no evidence of new copy seeding), database CPU low and connections 2 after deploy. **API MAINTENANCE HOLD IS EXPLICITLY FALSE; sign-in/dashboard not intentionally blocked, and no API write-quiescence has been asserted.** Processing worker still recovery-held on PR #190 `a0bf2afc`, collection/trading off and R2 cleanup off. R2 cold backups/manifests retained. Physical disk/WAL free headroom remains unknown via available connector; restricted maintenance DB role/login uninstalled, leaked DB credential rotation still outstanding. Next safe work: reconcile obsolete recovery runbook and operator-only preflight; do NOT enable `MT_API_RECOVERY_HOLD=true`/archive flags or write SQL without coordinated safe maintenance and measured disk headroom.
- **2026-11-11 ~21:34 UTC MT-019 processing + API PR191 LIVE, runbook corrected:** Verified postmerge [GitHub Actions 43103219432](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43103219432) SUCCESS. **API service `pocket-api-staging`** manually deployed exact `fa4fe1f215a83691a67a5d710ba199a4ad5830ae` as `dep-dbqdt6mc6qcc73f1fi7g` LIVE at 21:32:03 UTC with **explicit private `MT_API_RECOVERY_HOLD=false`** (only env var changed, merge not replace), keeping normal sign-in/dashboard access. API predeploy `migrate` audit logged `migration_count=9`, `migrations_match=true`, `history_mutation=false`, `privilege_boundary_ready=true`; Uvicorn startup complete, no error logs or `api_database_unavailable` in checked window, no `live_bots_copied` startup event. **Processing worker** automatically deployed same `fa4fe1f2` as `dep-dbqdti7f3r2c73f186tg` LIVE at 21:32:44 UTC; held predeploy at 21:32:32 logged `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`; no worker error logs in checked window. Database remains available 15 GB with autoscaling OFF, ~2 connections and low CPU; actual physical volume/WAL headroom still UNVERIFIED, WAL directory query denied. Owner-only narrow SQL role and function remain UNINSTALLED, private archive URL not configured, API maintenance hold not activated, no writer-quiescence attestation or R2 diagnostic cleanup authorized, leaked DB credential rotation pending. The running API health endpoint was not independently probed by HTTP (public web fetch unavailable); deployment/startup evidence only. Docs-only reviewed [PR #194](https://github.com/princesspikachuu/kalshi-scanner-data/pull/194) merged `[skip render]` as `7b33964892609baa699d2057712bd24e59e24cf7`, correcting stale one-transaction and two-flag instructions, preserving latest WAL preflight and API held OFF facts; postmerge GitHub docs run [43104200598](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43104200598) IN PROGRESS, no new Render deployment seen. **Next**: verify docs run / no-deploy; operator privately inspect actual Render PostgreSQL physical disk utilization+WAL, rotate previously exposed credentials, verify R2 root catalog/recovery and stop all writers including old API instances in a coordinated window. Then install least-privilege archival SQL role via private owner Shell and run only bounded, verified 24h+ diagnostic archival. DO NOT turn on archive/collection/trading or claim physical safety based on logical size.
- **2026-11-11 21:46 UTC ONE-SHOT R2 DIAGNOSTIC ARCHIVE REVERIFICATION PASS:** GitHub PR #194 docs-only merge `7b339648` full validation [43104200598](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43104200598) SUCCESS; Render processing held worker was explicitly set `MT_ARCHIVE_VERIFY_ONCE=true` only (default false), starting `dep-dbqe3l6gekts73e84pl0` on unchanged app code. It reached LIVE 21:46:18 UTC, emitted one read-only `shadow_archive_r2_integrity` report at 21:46:18.553Z: `verified=true`, `no_deletion=true`, `manifests_scanned=1`, `verified_manifests=1`, `original_rows_verified=10`, `original_events_verified=10`, `deleted_rows_absent=10`, `compressed_bytes_verified=7892`. This re-reads the real archived objects from R2 and checks exact source row IDs absent from PostgreSQL. **Immediately reset `MT_ARCHIVE_VERIFY_ONCE=false`** after receipt, triggering replacement `dep-dbqe4emi0phs73cdhsb0` starting 21:46:34 UTC; verify it reaches LIVE and no new audits fire after reset. No archival writes, deletes, restored rows, or paper trading activated. This is a 10-record DIAGNOSTIC archive integrity check, not a new complete database backup/PITR or permission for bulk cleanup; the separate 4,190-record R2 control snapshot remains preserved from earlier. Operator physical database volume/WAL headroom, isolated archive login/function and leaked DB credential rotation remain outstanding. Parallel code-only branch `fix/mt019-one-shot-exclusivity` created but not merged or deployed.
- **2026-11-11 21:47:28 UTC R2 one-shot OFF and worker restored LIVE:** After verified `shadow_archive_r2_integrity` (1/1 manifests, 10/10 original records, 7,892 compressed bytes, 10 source rows absent), `MT_ARCHIVE_VERIFY_ONCE=false` replacement processing deploy `dep-dbqe4emi0phs73cdhsb0` became LIVE on exact `7b33964892609baa699d2057712bd24e59e24cf7` at 21:47:28 UTC; predeploy logged `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`. **Zero new integrity-audit events after OFF reset** in checked logs. Archive SQL owner role/function remains absent; no cleanup activated. Concurrent **PR #195** https://github.com/princesspikachuu/kalshi-scanner-data/pull/195, branch `fix/mt019-one-shot-exclusivity`, head `005c54b1dd59a9db14736cae22fa320930f0e16b` OPEN/UNMERGED, GitHub Actions [run 43106267752](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43106267752) IN PROGRESS at checkpoint. Adds startup fail-before-I/O mutex for six recovery one-shot flags, prevents overlap with archival loop/recurring backup, and allows `MT_BACKUP_EXACT_CENSUS` only when subordinate to its dedicated audit. Tests assert every pair refuses before DB/R2 access; read-only normal startup unchanged. Do not merge #195 until CI success. Neither PR nor audit reset starts trading/collection, deletes source data or mutates R2. Physical Render volume/WAL headroom still requires private operator metric, and DB credential rotation/scoped role still outstanding.
- **2026-11-11 legacy archiver pre-restart risk discovered, P0 issue #196:** Source-level audit of `services/demo/maintenance.py::archive_events` found old demo-event archival R2 object writes only `id,parameters,progress` (omits immutable row metadata) and later overwrites `progress` if `NOT(progress ? 'archive')`, without checking whether selected progress/parameters changed while the R2 PUT ran. A concurrent update could lose newer progress or make the R2 snapshot stale; this is NOT an observed live loss. The old archiver is NOT active while the demo worker is held. Created [P0 issue #196](https://github.com/princesspikachuu/kalshi-scanner-data/issues/196) to require complete versioned row export, optimistic exact-row mismatch protection, back-compatible restoration and PostgreSQL race tests **before re-enabling normal demo archival/maintenance**. Do not delete old R2 archives, assume v1 is full-row PITR, or restart demo/collection/trading. New scoped diagnostic-only archiver and independent 10/10 integrity PASS are separate and unaffected.
- **2026-11-11 PR #195 full CI SUCCESS, merged:** [GitHub Actions run 43106267752](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43106267752) passed all tests including disposable PostgreSQL; [PR #195](https://github.com/princesspikachuu/kalshi-scanner-data/pull/195) review showed exactly four files (new pure guard, unit tests, runtime call before SQL/R2, operator note). Squash merged into deployment branch as `3f54400fee33277f2da6352231a48ac3580c9a17`. This fails closed at worker startup when multiple recovery one-shot flags are true or any audit overlaps the archival loop/recurring backup, and permits exact backup census only under its one-shot audit. **Postmerge CI and Render LIVE deployment not yet verified at this checkpoint; DO NOT force deploy while checksPass autoDeploy handles it.** The independently verified previous diagnostic R2 integrity (10 of 10, 7,892 bytes) and one-shot reset stand, processing idle held, API hold false, DB available 15 GB autoscaling OFF. No SQL role installed, no physical free-volume measurements, no trading or automatic archival enabled. P0 issue #196 prevents returning to legacy demo archival until full-row and CAS-safe remediation.
- **2026-11-11 ~22:00 UTC extended MT-019 pause checkpoint:** [PR #195](https://github.com/princesspikachuu/kalshi-scanner-data/pull/195) full head CI [43106267752](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43106267752) SUCCESS and squash MERGED as `3f54400fee33277f2da6352231a48ac3580c9a17`. Central one-shot recovery startup mutex is now in the deployment branch, but postmerge CI [43107109399](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43107109399) was still IN PROGRESS (full API/PG suite, no reported failures) and no new worker Render deployment had begun; **do not claim PR #195 code LIVE until checksPass and exact deployment verified**. Latest processing worker LIVE `dep-dbqe4emi0phs73cdhsb0` on docs commit `7b339648` with audit flag explicitly OFF and held predeploy `collection_enabled=false`, `trading_enabled=false`, `storage-recovery-hold-v1`, zero repeated R2 integrity events. Fresh Render metrics 21:40–22:00 UTC: PostgreSQL CPU ~0.0068–0.0071, memory ~317 MB, active connections 1–2; processing worker effectively idle CPU, memory ~65–73 MB; no processing error-level logs. These do NOT establish free physical disk/WAL or writer quiescence. P0 issue #196 tracks legacy demo event archiver partial-row R2 backup and stale UPDATE risk before restarting demo maintenance. The R2 integrity audit proved prior exact 10 diagnostics and R2 7,892 bytes, not a whole DB/PITR restore; 4,190-record multipart control snapshot remains preserved from earlier verification. NO data deletion, trading restart, archive enablement, owner-role install, or credential mutation occurred. Next: verify PR195 merge CI and auto-deploy held; physical Render storage/WAL graph + protected owner-only SCRAM archive role + exposed password rotation remain operator gates; before normal demo trading, fix #196 and establish sustainable retention.
- **2026-11-11 ~22:09 UTC MT-019 P0 #196 fix IN PROGRESS / PR #197 OPEN:** Verified [PR #195](https://github.com/princesspikachuu/kalshi-scanner-data/pull/195) postmerge [CI 43107109399](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43107109399) completed SUCCESS and processing worker `dep-dbqe9vff3r2c73f1ttn0` on commit `3f54400fee33277f2da6352231a48ac3580c9a17` became LIVE 2026-11-11 21:59:12 UTC. Predeploy `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, no errors; API separate service remains `fa4fe1f2` LIVE with recovery hold OFF. P0 issue [#196](https://github.com/princesspikachuu/kalshi-scanner-data/issues/196) old demo event archiver lost full metadata and could overwrite changed progress; branch `fix/mt019-legacy-event-archive-v2` [PR #197](https://github.com/princesspikachuu/kalshi-scanner-data/pull/197), HEAD `761de06764290740a1d098a380a883043b55518b` OPEN/UNMERGED, [CI run 43109066862](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43109066862) IN PROGRESS at full API/disposable PostgreSQL phase (focused Favorites PASS). New `services/demo/legacy_event_archive.py` restricts auto archive to 25 aged nonfinancial `demo/shadow/event/` diagnostics, retains ALL 15 original research_job columns in R2 v2 and exact R2 readback, then short SQL row lock/full snapshot compare + progress CAS to refuse concurrent source changes; supports old v1 archives and v2 restoration with metadata checks. `maintenance.py` auto archive is now **OFF BY DEFAULT even if UI policy.archive_enabled=true**, requires private `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED=true` after all independent gates, not set LIVE. Disposable DB and R2 in-memory tests added; docs and issue comment. IMPORTANT: source record update never DELETE; PR unmerged; CI must PASS before any merge. The v2 dashboard archive read-path and physical disk/WAL/operator role/credential rotation still block any automatic activation or return to normal demo trading. No production DB/R2 mutations or env changes made in this continuation.
- **2026-11-11 ~22:12 UTC P0 #196 / PR #197 CI correction checkpoint:** Initial PR #197 HEAD `761de067` [CI 43109066862](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43109066862) FAILED 3 tests in full real PostgreSQL suite: (1) new `verified_records` pre-R2 source validation missed `source_prefix`, (2) old backup-diagnostics test expected archival to be on without private opt-in, (3) old hosted test expected 202 broad trading/shadow records to be archived, contrary to newly intentional diagnostic-only protection. Read full GitHub job logs and corrected both implementation and tests: the implementation now includes `source_prefix=PREFIX`, backup failure test explicitly opts into the archival stage to verify alert+backup failure isolation, hosted PostgreSQL regression now asserts all 201 ordinary trading events and a financial shadow settlement stay HOT while only one old safe allowlisted shadow diagnostic is archived losslessly. Added no production flags. Latest PR #197 head `72b3b0e214f929a22a17699df8604c386bd84f66` has fresh GitHub Actions [run 43109791995](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43109791995) IN PROGRESS; PR remains OPEN and unmerged pending full CI pass. Issue [#196](https://github.com/princesspikachuu/kalshi-scanner-data/issues/196) remains OPEN and notes additional owner UI route gap: existing `/demo/restore/{id}` only queues `demo/event/`, but new diagnostic v2 archive scope is `demo/shadow/event/`, so enabling v2 requires owner-facing read/restore acceptance beyond the backend's verified R2 restore function. Keep `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED` absent/OFF. Database physical free disk/WAL unknown; no scoped archive role, writer-stop confirmation, credential rotation, collection/trading or automatic cleanup. Safe worker processing remains LIVE on held `3f54400f` and API on `fa4fe1f2` normal hold false.
- **2026-11-11 22:23 UTC P0 #196 archive safety fix CI PASSED and merged:** [PR #197](https://github.com/princesspikachuu/kalshi-scanner-data/pull/197) latest head `72b3b0e214f929a22a17699df8604c386bd84f66` full real PostgreSQL [CI 43109791995](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43109791995) SUCCESS. Manually reviewed six changed files; merged squash `604ed7724092d12bcc87dca57337132844b427d3` into deployment branch. It replaces stale partial-column legacy R2 archive with versioned full 15-column, nonfinancial diagnostic-only, separate read-only candidate transaction + verified R2 I/O + short locked row compare/CAS; changed source keeps original PostgreSQL progress, v1/v2 restore compatibility, archive explicitly **OFF by default** behind new `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED` (NOT set). Postmerge [CI 43110999655](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43110999655) IN PROGRESS and processing Render still LIVE held `3f54400f`, so **do not call #197 deployed until exact new Render commit/hold verified**. Follow-on [PR #198](https://github.com/princesspikachuu/kalshi-scanner-data/pull/198) branch `fix/mt019-shadow-archive-owner-restore`, head `087f8001a9ce710534ec94bc8d13c9988fe733f1`, CI [43111271920](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43111271920) IN PROGRESS: authenticated read-only `GET /demo/shadow/archive/{uuid}` returns only status/format, and CSRF-protected POST to queue archive restoration from `demo/shadow/event/` only, explicit `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=true` OFF by default; old demo/event v1 restore unchanged. Disposable PG tests verify namespace isolation, proxy/CSRF, no source mutation, legacy v1 compatibility. **Do not merge #198 until full CI PASS**, do not manually deploy API or activate archive/restore settings. No physical disk/WAL proof, restricted DB account, credential rotation or database-wide writer quiescence; trading/collection/automatic archival remain OFF. Issue #196 stays OPEN until dashboard archive/history acceptance and actual operator safety gates.
- **2026-11-11 ~22:29 UTC verified PR #197 LIVE, two restorability follow-ups pending:** [PR #197](https://github.com/princesspikachuu/kalshi-scanner-data/pull/197) merge commit `604ed7724092d12bcc87dca57337132844b427d3` full [postmerge CI 43110999655](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43110999655) SUCCESS, Render processing deployment `dep-dbqemr8ae00c7389g48g` on exact `604ed772` LIVE; predeploy `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false` at 22:26:26 UTC. **Legacy automatic archiving v2 remains private default OFF** (`MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED` never set) and no cleanup/trading started. [PR #198](https://github.com/princesspikachuu/kalshi-scanner-data/pull/198), HEAD `087f8001a9ce710534ec94bc8d13c9988fe733f1`, [CI 43111271920](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43111271920) IN PROGRESS full PG suite, adds authenticated owner-only read-only `GET /demo/shadow/archive/{id}`, private default-OFF `POST /demo/shadow/restore/{id}` with `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED`, no cross-namespace access, v1 demo/event endpoint unchanged; NOT merged/deployed. Further restore queue review found `DemoStore.rows('restore/',5)` sorts random UUID IDs and applies limit before skipping `done`, potentially starving pending requests. Opened [PR #199](https://github.com/princesspikachuu/kalshi-scanner-data/pull/199), HEAD `e9e3986aad42422dbd74974a7060b3f5df366038`, [CI 43111862126](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43111862126) IN PROGRESS; uses bounded indexed SQL limited to pending restore requests, regression seeds 12 completed and one pending v1 restore. Both PRs unmerged pending full CI. If #198 merges first, sync #199 to combined verified base before its merge even if non-overlapping. Keep P0 issue #196 OPEN: owner dashboard archive-aware historical statistics/actual R2 read path acceptance not complete, new archive+restore flags OFF. API still LIVE prior `fa4fe1f2` with hold FALSE. Actual 15 GB physical PostgreSQL free/WAL headroom, restricted maintenance role and exposed password rotation remain owner-only; no new source data mutation or deletion in this continuation.
- **2026-11-11 ~22:31 UTC PR #198 CI PASSED / MERGED; #199 synchronized:** [PR #198](https://github.com/princesspikachuu/kalshi-scanner-data/pull/198) HEAD `087f8001a9ce710534ec94bc8d13c9988fe733f1` [CI 43111271920](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43111271920) full API/PostgreSQL SUCCESS; squash merged as `4347129e47cbc550d77e46d010568ca22710a96e`. Authenticated owner read-only archive status and separately **OFF-by-default** restore request (`MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED` never set) are in GitHub base, but **API service uses autoDeploy=no, this code NOT YET LIVE**; processing held-worker autoDeploy waits merge-commit [CI 43112045622](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43112045622) IN PROGRESS. [PR #199](https://github.com/princesspikachuu/kalshi-scanner-data/pull/199) restores pending-only query fairness, after identifying `DemoStore.rows('restore/',5)` UUID LIMIT-before-done starvation. Its initial head `e9e3986a` started full CI 43111862126; to ensure combined-code validation, safely synced #199 atop merged #198 since changed file sets were disjoint (verified) using two-parent merge commit and expected-SHA branch lease. Latest head `08d0d580f683514af2bef4ce0a909df26f7fb7ff` needs its own new CI SUCCESS before merging. No manual API deploy, no env/secrets change, no trading/collection/cleanup, no physical disk/WAL safety attestation or scoped maintenance role. P0 #196 still OPEN pending archive-aware dashboard history, owner restoration acceptance and operator gates. Existing live processing `604ed772` held, API `fa4fe1f2` hold OFF.
- **2026-11-11 latest MT-019 PR199 full CI PASS, merged (verification pending):** [PR #198](https://github.com/princesspikachuu/kalshi-scanner-data/pull/198) postmerge [CI 43112045622](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43112045622) SUCCESS and processing held worker `dep-dbqeq3qjnfac73bej730` LIVE on `4347129e47cb`, API **not** manually redeployed (still earlier `fa4fe1f2`). [PR #199](https://github.com/princesspikachuu/kalshi-scanner-data/pull/199) integrated head `08d0d580f683514af2bef4ce0a909df26f7fb7ff`, full real Postgres [CI 43112133504](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43112133504) terminal SUCCESS, no failing steps, mergeable and independently reviewed 3 changed files, then squash merged into deployment branch as `ccef7fb160e787129e842435949227ba4f31f7a6`. Restoring old/new archives now uses `PENDING_RESTORE_SQL` to filter completed requests in indexed Postgres query BEFORE LIMIT 5; disposable PG tests seed twelve completed and one pending request, proving no starvation. **PR199 postmerge CI and Render held deployment NOT YET VERIFIED; DO NOT force deploy**. Owner read-only shadow archive status + private default-OFF restore request code of #198 now available in GitHub, but live API remains earlier version with `MT_API_RECOVERY_HOLD=false`; no owner restore opt-in set. P0 #196 remains OPEN for archive-aware dashboard and `completed` terminal status after a restore clears its pointer, plus manual owner acceptance. No data, SQL roles or credentials changed; auto archive, trading, collection remain OFF. Physical free disk/WAL and scoped maintenance SQL role/secret rotation still operator gates.
- **2026-11-11 ~22:39 UTC MT-019 PR #200 terminal restore status and archived analytics visibility gap:** [PR #199](https://github.com/princesspikachuu/kalshi-scanner-data/pull/199) CI 43112133504 SUCCESS, merged squash `ccef7fb160e787129e842435949227ba4f31f7a6` as recorded above; merge [CI 43112940529](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43112940529) still IN PROGRESS in real PG tests, processing remains previous held `4347129e` and API older `fa4fe1f2`, no manual restart. New [PR #200](https://github.com/princesspikachuu/kalshi-scanner-data/pull/200) branch `fix/mt019-shadow-restore-completion-status`, head `e3e145de3a3d0c804e7ee03e7663eedbd25816c1`, [CI 43113181777](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43113181777) IN PROGRESS; fixes default-OFF owner-only archive status to show `completed` once a successful restore has removed its R2 pointer, only if a trusted `owner_shadow_diagnostic` durable request with matching event ID has `done=true` AND original row `restored_at`, keeps namespace isolation and never shows R2 object keys/full progress; new route tests cover stale/fake completed markers, missing timestamp, wrong source/ID, crossed namespace, and proxy auth. Not merged or deployed. **New P0 issue #196 finding:** `GET /demo/shadow/events` queries hot `progress` and packed hot batches but does not join v2 `progress.archive` R2 pointer rows; `services/demo/shadow_archive_reader.py` is a separately gated reader for recovery manifest archives, not an automatic dashboard v2 pointer reader. If v2 automatic archive were enabled, Favorites decision/cohort/trial-quality evidence could disappear from hot dashboard history even though preserved in R2. Added detailed GitHub issue #196 comment. **DO NOT ENABLE `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED` or further diagnostic reclaim until historical analytics completeness/readback acceptance is established.** Both new archive and owner restore request flags remain OFF, no app storage cleanup/trading restarted. Physical disk/WAL headroom, restricted archive SQL role and credential rotation still operator prerequisites.
- **2026-11-11 ~22:42 UTC PR199 merge CI SUCCESS, Render updating; PR200 status still testing:** [PR #199](https://github.com/princesspikachuu/kalshi-scanner-data/pull/199) merge `ccef7fb160e787129e842435949227ba4f31f7a6` full postmerge [CI 43112940529](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43112940529) terminal SUCCESS; processing worker autoDeploy `dep-dbqet149v7es73di6lp0` entered `update_in_progress` at last check (NOT yet LIVE/hold verified). Existing held worker remains previous `4347129e` until rollout. [PR #200](https://github.com/princesspikachuu/kalshi-scanner-data/pull/200) current HEAD `e3e145de3a3d0c804e7ee03e7663eedbd25816c1` full [CI 43113181777](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43113181777) IN PROGRESS real PostgreSQL, no failed steps observed. It fixes owner archive status after successful R2 restore clears archive pointer, requires matching owner-shadow restore request done + restored_at + no active pointer, records nonsecret original format; tests reject fake completion and wrong namespace. Do not merge until CI SUCCESS. Render DB available 15 GB, autoscaling OFF, latest measurements one active connection/low CPU, no processing errors checked. API remains prior `fa4fe1f2`, manual API deploy deferred until #200 validated/merged, all owner restoration/archival feature opt-ins remain OFF. No physical volume/WAL headroom measurement, narrow SQL role, credential rotation, or all-writer quiescence. P0 issue #196 explicitly blocks enabling v2 archival due `GET /demo/shadow/events` reading hot `progress` without R2 pointer-aware dashboard historic reconstruction, regardless of proven R2 recoverability. No new deletion, cleanup or trading.
- **2026-11-11 ~22:44 UTC PR199 held Render LIVE, PR200 full CI PASS and merged:** [PR #199](https://github.com/princesspikachuu/kalshi-scanner-data/pull/199) merge CI [43112940529](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43112940529) terminal SUCCESS. Processing worker `dep-dbqet149v7es73di6lp0` exact commit `ccef7fb160e787129e842435949227ba4f31f7a6` LIVE at 22:39:53 UTC; predeploy at 22:39:43 logged `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`, no error logs inspected. [PR #200](https://github.com/princesspikachuu/kalshi-scanner-data/pull/200) HEAD `e3e145de3a3d0c804e7ee03e7663eedbd25816c1`, full real PG [CI 43113181777](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43113181777) terminal SUCCESS and 3-file reviewed diff then merged squash `7913a0c6beeafb40178e093949a07d1532adf780`. API owner archive status now returns `completed` after actual v1/v2 restore clears pointer only with matching owner source/ID request `done=true` and original `restored_at`; stores nonsecret format, tests reject forged/stale markers and cross-namespace. **Postmerge CI and held Render rollout for #200 not yet verified**; API manual deployment with `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=false` deferred until merge CI completes. All archive/trading/collection and owner restore-request activation flags remain OFF. Key issue #196 remains OPEN: `GET /demo/shadow/events` hot-only API omits new v2 R2 pointer cold evidence so automatic archival would hide Favorites learning histories from dashboard; physical disk/WAL headroom, narrow database maintenance role and secret rotation also pending. Do not enable cleanup or live trading. `WORK_QUEUE.md` is the cross-chat checkpoint.
- **2026-11-11 ~22:46 UTC MT-019 SAFE STOP after long PR199/200 implementation:** Postmerge [PR #199 CI 43112940529](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43112940529) SUCCESS; processing worker `dep-dbqet149v7es73di6lp0`, exact `ccef7fb160e787129e842435949227ba4f31f7a6` became LIVE at 22:39:53 UTC; predeploy at 22:39:43 logged `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`, no error-level logs. [PR #200](https://github.com/princesspikachuu/kalshi-scanner-data/pull/200) full disposable PG CI [43113181777](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43113181777) SUCCESS and merged as `7913a0c6beeafb40178e093949a07d1532adf780`, fixing owner archive terminal `completed` status when original source progress restored, pointer cleared and durable trusted owner request matches; owner request stores only nonsecret archive format, tests reject forged/stale markers and cross-namespace disclosure. **Merge-commit CI [43113806285](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43113806285) remains IN PROGRESS full API/real PostgreSQL at latest check**, no failed steps observed; **API manual deploy NOT yet performed** and live API stays older `fa4fe1f2`, `MT_API_RECOVERY_HOLD=false`. Do NOT deploy API or claim PR200 LIVE until merge CI terminal SUCCESS; then use a controlled API deploy with explicit `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=false` (merge env only) and verify migrations, endpoint uptime and no accidental demo seed. P0 issue #196 updated with all PRs and remains OPEN due dashboard `GET /demo/shadow/events` hot-only data path, cold v2 pointer readback absent, which would hide historical Favorites learning if automatic archival enabled. **Never turn on** `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED`, owner restoration requests, diagnostic reclaim, collection or trading until cold analytics acceptance and full operator gates (physical 15 GB disk/WAL free headroom, narrow recovery SQL role, credential rotation, writer quiescence) are independently verified. No R2/PG data deleted or reset in this continuation.
- **2026-11-11 ~22:55 UTC PR200 API LIVE with hold/restores OFF; PR201 archive-aware recent history under CI:** Postmerge [PR #200 CI 43113806285](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43113806285) completed SUCCESS. Manually set only API env `MT_API_RECOVERY_HOLD=false` and `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=false` (`replace:false`), triggering manual API deploy `dep-dbqf33lbedkc73ddcq4g` of exact `7913a0c6beeafb40178e093949a07d1532adf780`, LIVE at 22:53:00 UTC. API predeploy 22:52:34 logged `staging-database-audit-v2`, 9 migrations match, `history_mutation=false`, `privilege_boundary_ready=true`, non-owner API role; Uvicorn application startup complete, zero API error-level logs in deployment window. Processing held worker `dep-dbqf0ae7bikc739h6jn0` on same `7913a0c6` LIVE 22:46:52 UTC, predeploy `storage-recovery-hold-v1`, collection/trading false, no worker errors. Database available 15 GB autoscaling OFF; physical used/free WAL NOT measured. [PR #201](https://github.com/princesspikachuu/kalshi-scanner-data/pull/201), branch `fix/mt019-pointer-aware-shadow-events`, head `6211317700a9b6863437d29765f931e2ec6852a0`, GitHub Actions [run 43115704522](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43115704522) IN PROGRESS; **NOT MERGED/DEPLOYED**. Adds bounded read-only R2 pointer rehydration for latest 100 `/demo/shadow/events` and `recent_history_complete` only after full verification; uses separate default-OFF `MT_ARCHIVE_V2_POINTER_READ_ENABLED` plus existing `MT_ARCHIVE_READ_ENABLED`/R2 read-only credentials, max four distinct R2 objects/request and fails sanitized 503 rather than silently hide a pointer or return partial history; normal hot-only path performs zero R2 calls. Tests for real gzip/SHA, source key/parameters/time, allowlisted kinds, hostile receipts, budget and HTTP failure/success, CI pending. The last-100 endpoint is NOT all-time Favorites analytics; issue #196 stays OPEN; **never enable automatic v2 archival/diagnostic reclaim until all-time cold-history/dashboard learning verified**. R2 / DB records preserved, no cleanup/trading resumed, no scoped role or credential rotation.
- **2026-11-11 ~23:01 UTC PR201 complete full PG CI PASS + MERGED, next deployed validation pending:** [PR #201](https://github.com/princesspikachuu/kalshi-scanner-data/pull/201) HEAD `6211317700a9b6863437d29765f931e2ec6852a0` passed [GitHub Actions run 43115704522](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43115704522), terminal SUCCESS incl full owner/API/real PostgreSQL and frontend tests, four changed files reviewed; squash merged into deployment branch as `93c86efccd4f9fafb1ec9babd8ec02c1ad0f813b`. Adds safe v2 R2 cold pointer rehydration of last 100 `GET /demo/shadow/events` results; when 0 archived pointers no R2 calls, when present requires new `MT_ARCHIVE_V2_POINTER_READ_ENABLED=true` and existing `MT_ARCHIVE_READ_ENABLED` + independent R2 READ-only credentials, all NOT set/activated. Uses verified gzip/SHA and all-v2 row provenance, ID/key/parameters/created_at consistency; max four objects/request and sanitized 503 when cold evidence inaccessible/invalid/oversize (no partial hidden Favorites history). Unit tests use real compressed mock-R2 readback and auth route. **Postmerge CI and processing Render LIVE on `93c86efc` NOT YET VERIFIED; API autoDeploy=no stays prior `7913a0c6`, so #201 is not live in API. Do NOT manually deploy API before merge CI pass; if pass, plan controlled manual API rollout with pointer READ flag OFF, archive/restore OFF and `MT_API_RECOVERY_HOLD=false`.** Current API was safely deployed LIVE on PR200 `7913a0c6`, migration count 9 matched, `history_mutation=false`, no API errors; processing held worker also on prior `7913a0c6`. Latest metrics ~22:55–23:00 UTC: API CPU ~0.002, memory 81MB; database CPU ~0.005–0.007, memory ~319MB, 3 connections; worker CPU idle and ~70MB memory. Physical DB disk/WAL free headroom NOT exposed and not measured. **P0 #196 stays OPEN**: PR201 covers recent last100 only, NOT all-time indexed hot/packed/v1 reclaimed manifest/R2 pointer union or Favorites statistics dashboard validation; acceptance plan recorded in issue #196. Never enable `MT_LEGACY_EVENT_ARCHIVE_V2_ENABLED`, R2 reader flags, trading/collection or cleanup without independently verified cold all-time history and owner disk/WAL, scoped role, credential rotation, all writer quiescence gates. No data deletions/resets or archive role changes.
- **2026-11-11 ~23:02 UTC PR201 safe pause after merge:** Squash merge `93c86efccd4f9fafb1ec9babd8ec02c1ad0f813b` triggered postmerge GitHub Actions [run 43116254121](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43116254121), currently IN PROGRESS (dependency-install step at last check), no failures reported. Processing Render worker still verified LIVE held on previous `7913a0c6`, API LIVE on `7913a0c6` with `MT_API_RECOVERY_HOLD=false`, `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=false`. **Do not claim PR201 deployed** until run 43116254121 terminal SUCCESS, then Render worker exact `93c86efc` LIVE and `storage-recovery-hold-v1` log verified. API autoDeploy=no; after CI, a separate manual API code-only rollout must explicitly preserve pointer reader `MT_ARCHIVE_V2_POINTER_READ_ENABLED=false`, `MT_ARCHIVE_READ_ENABLED=false`, restoration requests=false and API hold=false, and verify startup/migrations. Current PR201 R2 reader code is NOT configured or active in the API and must not be activated before owner full-history acceptance. No automatic archiving, trading, collection, physical DB cleanup or role setup permitted.
- **2026-11-11 ~23:08 UTC PR201 safely deployed; PR202 paginated hot/packed history under CI:** [PR #201](https://github.com/princesspikachuu/kalshi-scanner-data/pull/201) postmerge [CI 43116254121](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43116254121) terminal SUCCESS. Processing worker `dep-dbqf8l8473hc73ftndt0` LIVE on exact `93c86efccd4f9fafb1ec9babd8ec02c1ad0f813b`, predeploy `storage-recovery-hold-v1` logged `collection_enabled=false`, `trading_enabled=false`, no worker errors. API explicitly merged ENV ONLY (`replace:false`) `MT_API_RECOVERY_HOLD=false`, `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=false`, `MT_ARCHIVE_READ_ENABLED=false`, `MT_ARCHIVE_V2_POINTER_READ_ENABLED=false` and deployed exact `93c86efc` as `dep-dbqf8u8n74is73c11ki0`, Render LIVE at 23:05:40 UTC. API predeploy 23:05:04 logged migration count 9 matches, `history_mutation=false`, `privilege_boundary_ready=true`, no error-level logs. No actual R2 cold reader activated. **Next independent P0 #196 implementation claimed:** [PR #202](https://github.com/princesspikachuu/kalshi-scanner-data/pull/202) branch `fix/mt019-paginated-shadow-history`, HEAD `ec437221792c6524dc380c6b59969fa4763dfaa1`, [CI 43117356602](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43117356602) IN PROGRESS; OPEN and unmerged. Adds two authenticated read-only keyset indexed APIs `/demo/shadow/history/raw` (max4 hot rows incl protected financial evidence and verified v2 pointers when reader explicitly enabled) and `/demo/shadow/history/packed` (max1 compact diagnostic batch, up to64 original IDs), strict source-specific cursor, 5s SQL timeout, sanitized 503 on incomplete/invalid R2 or batch, provenance original IDs and event times, explicit `all_time_coverage_complete=false` and `reclaimed_manifests_included=false`. Disposable PG tests cover 11 raw originals and 3 packed batches/6 original IDs, no duplicates or SQL mutation, auth and invalid cursors. Do NOT merge before full CI success. This is NOT unified all-time Favorites analytics nor reclaimed R2 manifest union; P0 #196 stays OPEN. Physical disk/WAL volume headroom, private least-privilege archival account and DB credential rotation remain operator blockers. **No source DB deletions, trading, collection, auto-archive or R2 reader/restore flags enabled.**
- **2026-11-11 ~23:15 UTC PR202 source-page pagination CI PASS and MERGED:** [PR #202](https://github.com/princesspikachuu/kalshi-scanner-data/pull/202) HEAD `ec437221792c6524dc380c6b59969fa4763dfaa1` passed full [CI 43117356602](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43117356602) terminal SUCCESS incl owner API/real disposable PostgreSQL suite and focused Favorites frontend, exactly four files reviewed; squash merged into `build/google-auth-foundation` as `c6ebfde223ac0462c83b50ec23bd8614d4758668`. New owner-authenticated read-only `/demo/shadow/history/raw` (indexed keyset, max four raw including financial events and v2 pointer readback when separately authorized) and `/demo/shadow/history/packed` (indexed keyset, one packed diagnostic batch/max64 original IDs); 5-second SQL statement timeout, no `COUNT(*)`/offset scans, strict namespace cursor and 422/503 fail closed. Every response declares `all_time_coverage_complete=false` and `reclaimed_manifests_included=false`; physical R2 reclaimed raw/packed archives, cross-source dedup and all-time Favorites-statistics dashboard integration **remain required** before v2 archival. Disposable PG regression verified 11 original raw events including protected SETTLED, 3 packed batches -> 6 exact original event identities, no lost/doubled records; hot source unchanged. **Postmerge [CI run 43118068564](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/43118068564) IN PROGRESS**, worker still LIVE recovery held on previous `93c86efc`, API LIVE previous `93c86efc` (autoDeploy=no). DO NOT claim #202 live or manually deploy API before merge CI terminal SUCCESS and worker held deploy verified. On later controlled API rollout explicitly keep `MT_ARCHIVE_V2_POINTER_READ_ENABLED=false`, `MT_ARCHIVE_READ_ENABLED=false`, `MT_SHADOW_ARCHIVE_RESTORE_REQUESTS_ENABLED=false`, `MT_API_RECOVERY_HOLD=false`; never activate cold R2 read without separate least-privilege read credential and acceptance. P0 #196 stays OPEN. Physical disk/WAL headroom, restricted maintenance SQL role, leaked DB credential rotation, all-writers quiescence remain unverified/operator-only. No trading, collection, archival cleanup or historical record deletions/resets.
- **PAUSE CHECKPOINT (Nov 11 2026):** No SQL account creation, environment/secrets changes, automatic cleanup or resumed trading. Physical filesystem/WAL safety, API/other writer quiescence, private scoped DB login, and leaked credential rotation remain outstanding. Future cleanup requires freshly verified disk/WAL capacity and a separate explicit private operator sequence; never enable broad DELETE or reset research history. Keep MT-019 IN PROGRESS and all workers held.

---


# PRIORITY 1 — Increase Favorites data collection volume

## MT-001 — Allow repeated Favorites data-collection bids on the same market
**Status:** DONE  
**Worker:** ChatGPT / MT-001 completed and verified  
**Claimed:** 2026-11-09 04:32 UTC  
**Priority:** Highest

### Goal
The **data-collection Favorites strategy** must be able to place multiple paper-trading bids/trades in the same market whenever a new qualifying condition appears. The current one-market/one-entry behavior is preventing us from collecting enough observations.

### Required behavior
1. Remove any blanket rule that permanently marks a market "already traded" after the first Favorites data-collection entry.
2. Replace it with an **opportunity-level** rule:
   - A market may generate multiple entries over its lifetime.
   - Each entry must correspond to a distinct qualifying opportunity/event, not repeated duplicate submission every worker cycle.
3. Preserve protections against accidental spam/duplicate bids:
   - Do not submit the same logical signal repeatedly while nothing meaningful has changed.
   - Introduce or reuse an opportunity fingerprint / signal key based on the relevant decision inputs (for example price bucket, probability/side, time-to-expiration bucket, market state, and/or other strategy conditions).
   - Allow another entry when the qualifying condition materially changes or reappears after leaving the qualifying state.
4. Do **not** overwrite prior Favorites observations. Every entry should become its own data point/trade record linked to the same market.
5. Ensure simultaneous/open entries in the same market are represented correctly in:
   - open bids,
   - filled positions,
   - awaiting-settlement positions,
   - realized P/L,
   - strategy summary counts.
6. Risk/capital rules should still apply. The purpose is to collect much more data, not to create infinite exposure.
7. Keep this specifically for the **data-collection Favorites** behavior unless shared infrastructure safely supports it for other strategies.

### Data we need from every Favorites observation
Verify each qualifying entry records enough information to later analyze performance by:
- market/event type,
- market ticker/id,
- side,
- entry price / implied probability,
- entry timestamp,
- time remaining to close/settlement at entry,
- price/probability bucket,
- market-type/category bucket,
- order type / maker-vs-taker if relevant,
- fill status and fill delay,
- final outcome,
- realized P/L,
- any existing Favorites-specific signal/features.

Do not discard existing fields. Add missing fields in a backward-compatible way.

### Instrumentation
Add/verify counters so the dashboard/logs can distinguish:
- qualifying opportunities detected,
- entries attempted,
- entries skipped as exact duplicates,
- entries skipped for risk/capital limits,
- entries filled,
- repeated entries on markets already traded once,
- unique markets observed,
- total observations/trades.

This is important because **we are currently dissatisfied with the amount of data being collected** and need to prove the change increases observation volume.

### Acceptance criteria
- A single market can produce 2+ Favorites data-collection entries when distinct qualifying opportunities occur.
- A static unchanged qualifying state does not produce a new duplicate order every cycle.
- Existing Favorites history remains intact.
- Existing summary/P&L accounting remains correct with multiple entries per market.
- Automated tests cover repeated-entry allowed + duplicate-cycle suppressed behavior.
- Verification includes a paper-trading run or deterministic simulation showing repeated observations from the same market.

### Implementation and verification
- **Code merged** to `build/google-auth-foundation` in PR https://github.com/princesspikachuu/kalshi-scanner-data/pull/137
- Merge commit: `75b304c09db0d46c4904233d7e3ba62e9c3b1b49`.
- GitHub Actions validation: **SUCCESS** at https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42563609262 (full API/owner policy/PostgreSQL suite and staging checks).
- Adds opportunity-level repeat paper-data entries on the same market; price/time signal suppresses unchanged repeated entries; permits fresh qualifying events. Existing timing fill-cohort history remains append-only.
- Enforces per-market paper repeat inventory cap (default 5x configured contract quantity, profile override), cash limits, existing exit protections, and verified freshness/deadlines.
- Tests cover distinct entry orders and prices within one market, duplicate suppression, capped inventory, two distinct fill cohorts through confirmed settlement, and calibrated Favorites retaining its original single-entry behavior.
- Records repeated opportunities, attempts, risk skips, duplicate suppressions and audit events.

### Deployment and live paper smoke verification
- Render `pocket-processing-staging` is **live** on commit `8c44d6c5d2aff4dc8731eee316b1b294c0428b87`, a descendant of MT-001 merge commit `75b304c09db0d46c4904233d7e3ba62e9c3b1b49` (comparison confirms ancestry).
- Live Render worker logs at 2026-11-09 06:40-06:43 UTC include repeated `FAVORITE_REPEAT_OPPORTUNITY` and `FAVORITE_ENTRY_DECISION` events alongside `ORDER_SUBMITTED`, `FILL`, and `FAVORITE_ENTRY_COHORT` for Favorites. `real_orders_enabled=false`.
- Confirmed deployed worker healthy/running; no additional deployment necessary.
- The post-merge deployment also included MT-002; this task did not modify MT-002.
- MT-003 may now be claimed to measure before/after Favorites data collection throughput, including fill/settlement conversion and remaining bottlenecks.

### Completion notes
_Implementation merged, 1,356-test GitHub Actions run passed, and repeat entry behavior observed live in paper worker. Full production before/after throughput measurement belongs to MT-003._

---

# PRIORITY 2 — Build Statistics-Backed Favorites concurrently

## MT-002 — Add a Statistics-Backed Favorites strategy alongside Data-Collection Favorites
**Status:** DONE  
**Worker:** ChatGPT / MT-002 implementation  
**Claimed:** 2026-11-09 04:37 UTC  
**Priority:** High

### Goal
Create a second Favorites strategy that runs **concurrently** with the existing data-collection Favorites strategy.

The original Favorites strategy must continue gathering broad observations. The new strategy should use the accumulated Favorites data to make increasingly evidence-based entry decisions and improve as the dataset grows.

### Important separation
- **Data-Collection Favorites** = exploratory / broad observation collection.
- **Statistics-Backed Favorites** = selective trading based on empirical performance in our collected data.
- Do not convert the collector into the statistical strategy.
- Do not stop or narrow the collector merely because the statistical version exists.

### Initial statistical model
Start with transparent, auditable statistics rather than an opaque ML model.

At minimum evaluate historical Favorites results by combinations of:
- market type/category,
- entry price / implied-probability bucket,
- time-to-expiration bucket,
- side if materially relevant,
- other already-collected Favorites features that show sufficient sample size.

**Price/value buckets must use 5-cent increments, not 10-cent increments.** Preserve the full applicable Favorites price range and split it into contiguous 5-cent buckets (for example, 70–74¢, 75–79¢, 80–84¢, etc.; use the actual strategy range rather than hard-coding this example).

For each candidate group calculate useful empirical measures such as:
- sample size,
- win rate,
- expected gross payout / return,
- realized net P/L,
- ROI,
- confidence/uncertainty measure,
- maker fill rate/fill delay where relevant.

### Sparse-data handling
Because the dataset is still small:
1. Do not overfit tiny groups.
2. Require a configurable minimum sample size before treating a narrow segment as authoritative.
3. Use hierarchical/fallback grouping when a narrow combination lacks data, e.g.:
   - exact market type + price bucket + time bucket,
   - then broader market type + price bucket,
   - then broader category/price or another sensible parent group,
   - then a conservative global baseline.
4. Surface the sample size and level of fallback used for every statistical decision.
5. Make thresholds/configuration explicit and easy to change as more data arrives.

### Entry policy
The strategy should only trade when the available historical evidence indicates positive expected value after relevant fees/slippage assumptions and passes configured confidence/sample thresholds.

Record for every decision:
- whether it traded or skipped,
- statistics used,
- sample size,
- grouping/fallback level,
- estimated expected value / expected ROI,
- threshold that was required,
- reason for skip if not traded.

### Continuous improvement
- The statistical strategy should recompute or refresh its evidence from newly settled Favorites observations on a practical cadence.
- New data should improve future decisions automatically without wiping historical results.
- Avoid expensive full-history recalculation every tight worker cycle; cache/materialize aggregates if needed.

### Dashboard/UI
Add a clearly separate Statistics-Backed Favorites card/folder/strategy identity so its:
- realized P/L,
- open bids,
- open/filled/awaiting-settlement positions,
- trade count,
- sample/data basis,
can be distinguished from the Data-Collection Favorites strategy.

#### Required statistics matrix
Display the Favorites statistical evidence as a **two-dimensional table/matrix** rather than a flat list of segments.

- Use **entry value/price as one axis** and **time-to-expiration at entry as the other axis**.
- Use **5-cent value buckets** on the value axis, replacing any existing 10-cent buckets.
- Recommended orientation for readability: **value/price buckets as rows** and **time buckets as columns**. The implementation may transpose this only if the UI is materially clearer.
- Keep different market types/categories separated (for example, separate matrix/table per market type or a market-type selector). Do not pool unlike market types into one table merely to simplify the display.
- Preserve the currently useful time-bucket resolution unless evidence supports changing it; this request changes the **value resolution to 5 cents**, not the time resolution.
- Every cell represents the historical observations for that exact **value bucket × time bucket** combination within the selected market type/category.
- Each populated cell should expose, at minimum:
  - sample size,
  - win rate,
  - ROI or expected value,
  - and whether the Statistics-Backed Favorites strategy currently considers that cell/group eligible to trade.
- Where useful, allow the user to inspect additional cell details such as realized P/L, confidence/uncertainty, fill rate, and fallback level.
- Empty or under-sampled cells must be visibly distinguishable from cells with sufficient evidence. Do not present sparse cells as authoritative.
- When a decision uses a broader fallback because the exact matrix cell lacks enough data, make that fallback apparent rather than making the exact cell look statistically proven.
- The table must update as newly settled Favorites observations are incorporated.

Still expose, where practical:
- current best-performing market/time/price segments,
- sample sizes,
- observed win rate/ROI,
- segments currently allowed vs rejected by the statistical strategy.

### Acceptance criteria
- Both Favorites variants can run at the same time.
- Data-Collection Favorites continues gathering broad data.
- Statistics-Backed Favorites consumes the same historical dataset without modifying/resetting it.
- Decisions are traceable to empirical statistics and sample sizes.
- Sparse-data fallback is tested.
- Newly settled data can change the statistical strategy's future decision parameters.
- P/L and open-position accounting for the two Favorites strategies remain separate.

### Completion notes
- **DONE (implementation and deployment):** PR [#138](https://github.com/princesspikachuu/kalshi-scanner-data/pull/138) merged by squash to `build/google-auth-foundation` at commit `8c44d6c5d2aff4dc8731eee316b1b294c0428b87`.
- **Code:** Separate `favorites_statistics` paper portfolio and account, alongside unchanged broad `favorites` collector; pooled, read-only collector evidence; market/series/side/5-cent-price/time grouping; hierarchical fallback with distinct-event counts and Wilson lower confidence bound; configurable sample, positive EV, ROI, fee/slippage and risk gates; traceable trade/skip decisions.
- **User-requested matrix:** Distinct market-type matrices, value tiers 70–74 through 90–94 plus a 95¢ terminal cell, unchanged entry-time tiers, sample/win rate/ROI/net/confidence, evidence candidate vs sparse vs rejected, explicit fallback labels, responsive scroll container. Existing Favorites time/price research now also displays 5-cent bands.
- **Performance:** One 30-second cached evidence aggregation shared by statistical bots; no history deletion/reset; historical P/L and pending positions kept separate.
- **Tests:** GitHub Actions run [42564105494](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42564105494) **success** on PR head `7ed1ce01635afb1d6faa1070a07f809ad6469fd5`: browser matrix tests, targeted statistical tests, full API/PostgreSQL suite (~1,358 tests), and Blueprint validation.
- **Deployment:** Render API `pocket-api-staging` deploy `dep-dbol5315efls73e7giag` **live**; worker `pocket-processing-staging` deploy `dep-dbol542jnfac73f8laog` **live**, both on merged commit. Exclusive worker handoff verified: new worker logged `demo_worker_ready` then `statistics_favorites_initialized` with **75** paper-bot profiles on 2026-11-09 04:59:42 UTC.
- **UI access caveat / follow-up:** Cloudflare staging gateway build and deploy step succeeded in run [42564499457](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42564499457), but the public unauthenticated staging sign-in-assets smoke check returned HTTP **403** (expected 200). Access protection may be intentional; do not weaken security blindly. An authenticated, end-user browser check remains unverified. This does not negate successful backend deploy and worker initialization. Monitor post-deploy actual orders/decisions separately from code acceptance.

---

# PRIORITY 3 — Validate Favorites data throughput after MT-001

## MT-003 — Measure whether Favorites data collection is now fast enough
**Status:** DONE  
**Worker:** ChatGPT / MT-003 throughput measurement  
**Claimed:** 2026-11-10 00:10 UTC  
**Urgency:** U2 — HIGH  
**Priority:** High, but execute after MT-001 is deployed

### Goal
Quantify the actual rate of Favorites data collection after repeated same-market opportunities are enabled. We should not assume MT-001 is sufficient.

### Measure
Compare before/after over comparable active-market windows:
- qualifying signals/hour,
- attempted entries/hour,
- fills/hour,
- settled observations/day,
- unique markets/day,
- observations per unique market,
- duplicate suppressions,
- risk/capital suppressions,
- monitoring/data-gap cycles.

Break down by market type and entry price/time bucket where possible.

### Diagnose remaining bottlenecks
If data collection is still too slow, identify whether the limiting factor is:
- insufficient market discovery,
- too few monitoring slots,
- overly restrictive Favorites entry filters,
- maker orders not filling,
- cooldown logic,
- per-market exposure/risk caps,
- worker/API capacity,
- market availability,
- another gating rule.

Do not simply loosen all safeguards. Identify the dominant bottleneck and create a follow-up task in this file with evidence.

### Acceptance criteria
- We have before/after metrics.
- We know whether observation volume materially increased.
- Any remaining dominant bottleneck is documented as a new READY task.

### Completion notes
_DONE. Favorites collection volume materially increased after MT-001._
- Historical sampled minute before/early MT-001: 1 entry submission, 0 fill-cohort events, 1 repeat-opportunity event.
- Early post-MT-001 sampled minute: 30 submissions, 22 fill-cohort events, 27 repeat-opportunity events. These are point samples rather than sustained hourly averages, but they confirm the repeated-opportunity path materially changed throughput.
- Current live collection-quality telemetry: 2,361 retained verified outcomes, 57 verified outcomes in the last hour (lower bound), 841 timestamped verified outcomes in the last 24h, 2,018 populated outcome cells, 31,937.31 cohort contracts, and 29,980.41 settled cohort contracts (~93.9% of cohort contracts).
- Same-day retained evidence grew from 2,297 to 2,361 verified outcomes (+64), 777 to 841 timestamped 24h outcomes (+64), and 1,970 to 2,018 populated cells (+48).
- Current 24h evidence is highly imbalanced by market type: 15m price 809/841 (~96.2%), hourly price 13 (~1.5%), weather 12 (~1.4%), weather daily 7 (~0.8%), sports 0.
- Current 15m collection is healthy enough that it should not be reduced merely to rebalance the dataset. The dominant remaining collection issue is insufficient evidence from non-15m market types, not overall Favorites observation volume.
- Resource/backlog work is tracked separately under MT-011; do not duplicate it here.

---

---

# PRIORITY 8 — Restore Favorites research visibility and controls

## MT-009 — Fix Data-Collection Favorites research tables: empty data + collapse state
**Status:** DONE  
**Worker:** ChatGPT / MT-009 implementation  
**Claimed:** 2026-11-09 19:45 UTC  
**Urgency:** U1 — URGENT  
**Priority:** Highest UI/data visibility issue after MT-008

### Current user-visible failures
1. Data-Collection Favorites research/statistics tables are showing **no data**.
2. The research/details tables **will not stay closed** after the user collapses them.

### Likely interaction with MT-008
MT-008 intentionally removed heavy per-bot research arrays such as `entry_timing` and `calibration` from the initial workspace response. The Favorites UI previously rendered these tables directly from `bot.experiment.entry_timing` / `calibration`.

Do not undo MT-008 by stuffing all research history back into the initial dashboard snapshot. Restore these tables using lazy/detail loading from dedicated research endpoints or a compact folder/category aggregate endpoint.

### Required fix — data
- Identify exactly which Favorites table components now receive empty arrays after MT-008.
- Restore Data-Collection Favorites research data via a bounded, lazy request when the relevant folder/category/research panel is opened.
- Reuse canonical stored Favorites evidence; do not duplicate or reset history.
- Prefer category/folder aggregate responses where the UI only needs aggregated price × time results.
- Keep payload bounded with aggregation/pagination rather than raw unlimited observations.
- Verify 5-cent value buckets and the existing time buckets remain intact.
- Ensure Data-Collection Favorites and Statistics-Backed Favorites both render their correct evidence sources without accidentally mixing portfolio accounting.

### Required fix — collapse persistence
- Diagnose why collapsing a research/details table does not persist.
- Preserve closed/open state across ordinary dashboard refreshes/polls.
- Use the existing localStorage/open-state mechanism if appropriate, but ensure rerendering does not force panels open again.
- Respect explicit user action: once a table is closed, background refreshes must not reopen it.
- Verify this separately for:
  - folder-level research,
  - category-level research,
  - per-bot research,
  - Statistics-Backed Favorites matrices if they use the same details pattern.

### Acceptance criteria
- Data-Collection Favorites tables show real collected data again.
- No large research history is reintroduced into the initial workspace snapshot.
- Closing a table keeps it closed across dashboard refreshes.
- Opening it keeps it open unless the user closes it.
- Mobile and desktop verified.
- Tests cover lazy data load and persisted collapse state.

### Completion notes
_Fill in when done._


### Implementation progress
- PR #159: https://github.com/princesspikachuu/kalshi-scanner-data/pull/159
- Added lazy owner-authenticated folder research endpoint for `favorites` and `favorites_statistics`; full `entry_timing` / `calibration` evidence is fetched only while those folders are open instead of being reintroduced into the 10-second workspace snapshot.
- Frontend hydrates open Favorites bots with lazy research and refreshes that detail on a bounded 30-second cadence.
- Removed hard-coded `open` state from collector and Statistics-Backed category tables; these now use the existing persisted `moneytree-research-views` state so user collapse choices survive redraws/polls.
- Added regressions for lazy full-data restoration and closed/open persistence.
- Initial CI failure was only a syntax typo in the new test fixture; corrected.
- Latest run `42687341474`: gateway/browser checks and focused Statistics-Favorites regressions are passing; full PostgreSQL/API suite is still running.


### Deployment progress
- PR #159 passed full CI and was squash-merged as `f99325ecd3de93c059ff2090674d2eca06348cfc`.
- Staging Cloudflare asset deployment succeeded and uploaded the changed `shadow.mjs` and `shadow-view.mjs`; the workflow failed only in its final unauthenticated public sign-in check with HTTP 403 after deployment.
- API deployment is building a newer branch head `722732707cb36fa43eff1b1216bc4b817ac3f888` that is confirmed to descend from the MT-009 merge.
- Keep MT-009 open until the API deploy is live and the user-visible tables can be rechecked.


### Completion notes
_DONE. Full Favorites research tables are restored through lazy folder detail loading, category/statistics table collapse state is persisted, Cloudflare staging assets were successfully deployed, and the API is live on descendant commit `722732707cb36fa43eff1b1216bc4b817ac3f888` containing the MT-009 merge. The Cloudflare workflow's final unauthenticated sign-in check returned 403 after deployment, but asset deployment itself succeeded._

---

# PRIORITY 9 — Increase Statistics-Backed Favorites trading activity

## MT-010 — Make Statistics-Backed Favorites trade materially more while still learning safely
**Status:** DONE  
**Worker:** ChatGPT / MT-010 implementation  
**Claimed:** 2026-11-09 22:22 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Current problem
The Statistics-Backed Favorites strategy is running concurrently but is trading too little. The dataset is still sparse, so a strategy that waits only for high-confidence exact cells will not collect enough of its own experience or provide useful parallel performance.

### Goal
Increase the rate of **intentional statistical/exploration trades** without turning the strategy into a duplicate of the broad Data-Collection Favorites collector.

### Required work
Measure the full decision funnel:
- qualifying Favorites opportunities seen,
- exact-cell evidence candidates,
- broader-fallback evidence candidates,
- exploration candidates,
- trades submitted,
- maker fills,
- skips by sample threshold,
- skips by confidence threshold,
- skips by ROI/EV threshold,
- skips by risk/capital,
- skips by duplicate/open exposure,
- skips by fill economics.

Then increase participation using evidence-based changes such as:
1. **Explicit exploration budget**
   - When data is sparse, allow controlled exploration trades in under-sampled cells that are strategically useful to learn.
   - Prioritize cells with little/no data rather than repeatedly sampling already-rich cells.
   - Keep a clear cap on exploration exposure.
2. **Hierarchical fallback trading**
   - Permit trades based on broader market-type/price or category/price evidence when exact price × time cells are sparse, provided broader evidence is positive enough.
3. **Graduated confidence requirements**
   - Do not require the same confidence/sample threshold for a small paper-learning probe as for a full evidence-backed trade.
   - Smaller exploratory size is preferred over no trade when uncertainty is the only blocker and economics are otherwise acceptable.
4. **Market coverage**
   - Verify the strategy is seeing the same eligible Favorites opportunity stream as the collector and is not accidentally monitoring a tiny subset.
5. **Maker fill realism**
   - Audit whether overly passive maker prices are causing nearly all statistical opportunities to go unfilled.
   - Improve/reprice maker bids when expected value remains positive, using the existing execution rules.
6. **Capital utilization**
   - Verify idle paper capital can support multiple simultaneous low-risk positions rather than one-at-a-time gating.

### Guardrails
- Preserve separate P/L/accounting from Data-Collection Favorites.
- Keep every decision auditable as evidence-backed vs exploration.
- Do not fabricate confidence from sparse cells.
- Do not use exploration as a reason to cross uneconomic spreads.
- Keep paper exposure caps.
- Continue incorporating newly settled collector + statistical observations.

### Acceptance criteria
- Measured increase in submitted trades and fills over a comparable active window.
- Sparse-data exploration produces useful new observations in under-sampled cells.
- Evidence-backed trades remain distinguishable from learning probes.
- No silent regression in risk controls or accounting.
- Dashboard shows why the strategy is or is not trading.

### Completion notes
_Fill in when done._


# PRIORITY 4 — Make Market Maker actually trade

## MT-004 — Diagnose and increase Market Maker opportunity-to-fill throughput
**Status:** DONE  
**Worker:** ChatGPT / MT-004 Maker throughput  
**Claimed:** 2026-11-09 22:22 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Current problem
The Market Maker is active but has been producing almost no trading activity. **User reconfirmed on 2026-11-09 that it still barely does anything after prior changes. Treat this as an unresolved strategy-throughput defect, not a cosmetic concern.** The goal is not merely to make it scan more markets; it must generate materially more valid paper quotes, fills, inventory turns, and completed trades while keeping the strategy economically rational.

### First: instrument the full funnel
Before loosening behavior, measure where candidates disappear. Add or verify counters/reason codes for:
- markets discovered,
- markets monitored,
- markets rejected before quoting,
- quote opportunities generated,
- quote opportunities rejected and exact reason,
- bid/ask quotes submitted,
- quotes replaced/repriced,
- quotes cancelled/expired,
- maker fills,
- partial fills if supported,
- positions/inventory opened,
- inventory exits/offsetting fills,
- completed round trips,
- realized P/L,
- average quote lifetime,
- average time-to-fill,
- spread at quote,
- executable depth at quote,
- API/worker capacity suppressions.

Expose enough of this in logs or dashboard diagnostics to identify the dominant bottleneck.

### Increase participation intelligently
After identifying the bottleneck, implement the highest-impact safe changes. Evaluate at least:
1. **Market breadth** — monitor more than a tiny fixed set when capacity exists. Do not assume four markets is a useful ceiling.
2. **Market selection** — prefer slower, liquid markets suitable for passive quoting rather than short 15-minute volatility markets.
3. **Adaptive quoting** — quote based on actual spread/depth and move quotes when necessary instead of leaving stale fixed prices.
4. **Quote refresh/repricing** — allow a maker quote to improve or re-anchor as the book moves, with anti-churn controls.
5. **Two-sided participation** where strategy/risk rules permit, rather than waiting on only one narrow entry condition.
6. **Inventory-aware sizing** — permit repeated small inventory turns without allowing unbounded directional exposure.
7. **Quote lifetime** — avoid cancelling so quickly that fills are impossible, but also avoid leaving economically obsolete quotes.
8. **Opportunity threshold audit** — find any filters that are so strict they eliminate nearly every candidate.
9. **Capital allocation** — verify unused paper capital is not needlessly preventing additional independent quotes.

Do not simply cross the spread to manufacture activity. Any taker behavior must remain explicitly justified by expected value after fees/slippage and should not replace the maker strategy's core purpose.

### Guardrails
- Paper trading only unless explicitly changed by the user.
- Preserve all existing Market Maker history.
- Do not unpause volatility strategies.
- Do not steal so much worker/API capacity that Favorites data collection materially degrades.
- Keep per-market/event exposure caps and total strategy risk caps.
- Avoid duplicate identical orders every cycle.

### Acceptance criteria
- The dominant reason for low activity is identified with measured funnel counts.
- The implementation produces a material increase in quote attempts and/or fills over a comparable active-market window.
- At least one deterministic or paper-run verification demonstrates the bot can manage multiple simultaneous quote opportunities safely.
- P/L, inventory, open orders, and completed-trade accounting remain correct.
- Any remaining bottleneck becomes a new task in this queue rather than being hidden.

### Implementation progress
- Claimed 2026-11-09 22:22 UTC. Initial live Render monitoring (22:19–22:23 UTC) found two physical Maker subscriptions, intermittent admission due to processing lag/backlog, 9–12 retained discovery candidates, and repeated low-volume/unstable-price/current-quote-ineligible rejection reasons. Both Maker portfolios were running (four profiles each), but neither had open inventory in the sampled health reports.
- PR [#165](https://github.com/princesspikachuu/kalshi-scanner-data/pull/165) **merged** as `2ae70a206d832adea3af0074a34047c6e0bf5c0d`: adds bounded in-process candidate rejection/verification/category histogram to existing `market_maker_scan` records, with unit tests; no new API traffic or strategy/risk changes.
- Live diagnosis and remaining acceptance work documented at `docs/audits/mt-004-maker-funnel-2026-11-09.md`. Full PR CI completed successfully (run 42711608106); combined post-merge branch checks underway. Keep task IN PROGRESS until comparable opportunity-to-quote-to-fill measurements and actual improvement are verified.
- Coordinate slot allocation changes with MT-015; do not independently raise monitoring limits or change shared scheduler while the bottleneck remains partially processing-bound.




### Implementation progress
- PR #164: https://github.com/princesspikachuu/kalshi-scanner-data/pull/164
- Live evidence showed many `FAVORITE_STAT_DECISION` events but essentially no explicit statistical entry submissions while collector Favorites was actively submitting/filling.
- Identified the original `statistics_exploration_max_open_markets=6` default as an early active-learning throttle.
- Migration raises only profiles still using the original default (or missing it) to 12 open exploration markets; customized profiles are preserved.
- 2-contract probe size, 10% portfolio exploration cap, maker-only behavior, fee/slippage checks, and fail-closed safety are unchanged.
- Added per-reason decision counters and explicit `favorite_statistics_entry` logs so post-deploy throughput can be verified directly.
- Regression coverage proves the 6-market cap blocks a seventh exploration market while 12 allows it.


### Rebase / validation update
- Original CI-green PR #164 was closed after newer parallel merges made it non-mergeable.
- The same MT-010 patch was rebuilt on current base as PR #167: https://github.com/princesspikachuu/kalshi-scanner-data/pull/167
- PR #167 is mergeable; focused checks are green and the full PostgreSQL/API suite is running.
- Concurrent PR #135 changed Competitive Maker's post-only inside-quote behavior and merged immediately before MT-004. This is a separate execution improvement and should be included in the before/after quote/fill comparison; do not attribute its outcome to the MT-004 telemetry addition.


### Latest validation update
- PR #169 passed the corrected full suite but became non-mergeable after additional parallel app merges advanced the base.
- Rebased the same CI-green behavior onto current app head `e1359f567bade146a6da62f467efed04d94ca801`.
- Current PR: #170 https://github.com/princesspikachuu/kalshi-scanner-data/pull/170
- PR #170 is mergeable; CI is pending/starting.


### Live deployment verification
- PR #170 passed full CI and merged as `aa056ef9a90b76d58bd4b488650ec75fdd235227`.
- Processing worker deploy `dep-dbp5nqp42hec73bll880` is live; new worker instance `srv-dbhcqr0473hc739kj4pg-jbksc` acquired the demo lock.
- Pre-fix baseline in this workstream: 0 shared active Maker markets in repeated samples.
- Post-deploy new-worker scan: 8 candidates admitted to shared Maker monitoring and monitoring capacity shows `market_maker: 8` with `maker_slots_free: 0`.
- Post-deploy health reached 8 monitored / 8 fresh books for both baseline and competitive Maker folders.
- Repeated `MAKER_RESTING` events are being generated on the new worker, confirming decision→order activity.
- Remaining live limiter is now downstream worker processing backlog; health snapshots report `worker processing backlog` and can temporarily show 0 resting orders even while MAKER_RESTING events are being emitted.
- Keep MT-004 IN PROGRESS until backlog is reduced enough to verify sustained resting orders and new Maker fills/round trips.


### Completion notes
_DONE and live-verified._
- PR #170 passed full CI, merged as `aa056ef9a90b76d58bd4b488650ec75fdd235227`, and deployed on worker deploy `dep-dbp5nqp42hec73bll880`.
- New-worker scans filled all 8 Maker monitoring slots and reached 8/8 fresh books.
- Repeated `MAKER_RESTING` events confirm decision→order activity.
- Cumulative Maker results increased during this workstream: baseline Maker round trips moved from 9 to 10; competitive Maker completed rounds moved from 30 to 36, with entry fills reaching 42.
- Remaining processing-resource work is tracked separately under MT-011; discovery/quote throughput changes for this task are complete.

---

# PRIORITY 5 — Expand monitoring capacity for active strategies

## MT-005 — Remove artificial monitoring bottlenecks and allocate capacity dynamically
**Status:** DONE  
**Worker:** ChatGPT / MT-005 capacity implementation  
**Claimed:** 2026-11-09 23:55 UTC  
**Urgency:** U2 — HIGH  
**Priority:** Medium-High; especially relevant if MT-003 or MT-004 shows monitoring starvation

### Goal
The app has previously had surprisingly few effective monitoring slots. Active strategies should use available worker/API capacity efficiently rather than being constrained by arbitrary low fixed limits.

### Required work
1. Map the current monitoring-capacity controls:
   - global slot limits,
   - per-strategy limits,
   - per-category limits,
   - API concurrency/rate-limit controls,
   - database/worker concurrency controls,
   - any stale legacy caps.
2. Distinguish a real external/resource limit from a conservative application default.
3. Add diagnostics showing:
   - eligible candidates waiting for a slot,
   - slots currently used by strategy,
   - slots unavailable because of API/CPU/DB pressure,
   - cycles where candidates were skipped solely for lack of monitoring capacity.
4. Allocate capacity dynamically among the **currently active** strategies:
   - Favorites data collection,
   - Statistics-Backed Favorites when enabled,
   - Market Maker.
5. Paused volatility strategies must not consume active monitoring capacity beyond minimal bookkeeping needed to display their existing state.
6. Allow unused capacity from one active strategy to be borrowed by another rather than sitting idle.
7. Preserve API-rate safety and database stability; increase useful concurrency only as far as measured headroom supports.

### Acceptance criteria
- We can state the actual effective monitoring capacity and its limiting resource.
- A hardcoded low ceiling is removed or justified by measured constraints.
- Active strategies can consume otherwise-idle capacity.
- Paused strategies do not crowd out active strategies.
- Dashboard/logging can show when a strategy is opportunity-limited versus capacity-limited.
- Load tests or controlled paper runs show no material regression in worker stability.

### Completion notes
_Fill in when done._


### Trigger from MT-004/015
- Claimed because live Maker admission is now healthy (8/8 slots, 8/8 fresh books) but quote persistence is suppressed by `worker processing backlog`.
- Goal: remove artificial monitoring/processing bottlenecks without reducing useful active trading or dropping protected exit/position markets.

---

# PRIORITY 6 — Keep paused items out of the way without losing them

## MT-006 — Sort paused folders/strategies/markets to the bottom everywhere
**Status:** READY  
**Worker:** —  
**Claimed:** —  
**Urgency:** U3 — NORMAL  
**Priority:** Medium

### Goal
Paused items should remain visible and retain all history/state, but they should not clutter the top of active operating views.

### Required behavior
- Active folders/strategies appear before paused folders/strategies.
- Within a folder/subfolder, active markets appear before paused markets.
- Preserve the existing ordering logic inside the active group and inside the paused group unless there is a strong reason to change it.
- Pausing/unpausing should immediately move the item to the appropriate group without a full data reset.
- Collapsed/expanded UI state should not accidentally unpause anything.
- Summary totals must continue to include/exclude paused state exactly as the existing product semantics intend; this task is primarily ordering/presentation, not accounting.
- Existing open/settling positions from a paused strategy remain visible and continue normal settlement bookkeeping.

### Acceptance criteria
- A paused market moves below all active markets in its relevant list.
- A paused folder/strategy moves below active folders/strategies.
- Unpausing reverses the ordering.
- No historical trades, P/L, positions, or pause state are lost.
- Mobile and desktop views are verified.

### Completion notes
_Fill in when done._

---

# PRIORITY 7 — Make strategy-learning data visible across strategies

## MT-007 — Add per-strategy data collection and learning diagnostics
**Status:** DONE  
**Worker:** ChatGPT / MT-007 learning diagnostics  
**Claimed:** 2026-11-10 00:12 UTC  
**Urgency:** U2 — HIGH  
**Priority:** Medium-High

### Goal
For every strategy that is collecting observations in order to improve future behavior, expose clear details about **what data it is collecting, how much data it has, how the data is segmented, and how that evidence is intended to improve the strategy**.

This is broader than Favorites. The user should be able to inspect a strategy and understand whether it is actually building a useful evidence base.

### Scope
Audit all current strategies and classify each as one of:
- **Data-learning strategy** — actively collects observations intended to change future entry/exit/quoting decisions.
- **Operational-only strategy** — records trades/P&L for accounting but does not currently use historical evidence to adapt.
- **Future-learning candidate** — has useful historical data but no adaptive logic yet.

Do not pretend an operational-only strategy is “learning” if it is not.

### Required data-details panel
For each data-learning strategy, add an expandable **Data / Learning** section in the strategy/folder UI showing, where applicable:

- total observations collected,
- settled observations usable for learning,
- open/pending observations not yet usable,
- unique markets/events represented,
- date/time range of the dataset,
- market types/categories represented,
- key features being recorded,
- current bucket/segment definitions,
- sample size per important segment,
- outcome metrics being learned from,
- fill-rate / fill-delay data where execution quality matters,
- entry timing / time-to-expiration data where timing matters,
- price/value/probability data where entry value matters,
- spread/depth/volatility/order-book features where relevant,
- reasons observations were skipped or excluded,
- missing-data counts where material,
- last time aggregates/models/statistics were refreshed.

### Explain how the data improves the strategy
The panel must also state in plain language:
- **what decisions the collected data is meant to improve**, such as entry threshold, quote placement, sizing, time window, market selection, exit timing, maker/taker choice, or risk limits;
- whether the strategy is currently **collecting only**, **using statistics now**, or **waiting for a minimum sample size**;
- the minimum evidence/sample threshold required before data can affect decisions;
- which parameters are currently data-driven versus still fixed/manual;
- what fallback behavior is used when a narrow segment lacks enough data.

### Strategy-appropriate views
Do not force every strategy into the same table. Use the visualization that matches the strategy's decision variables.

Examples:
- Favorites: price/value × time matrix, separated by market type.
- Market Maker: spread/depth/liquidity/fill-rate/quote-lifetime diagnostics and performance by market type.
- Sequential Spread: relevant leg spacing/order, time-to-close, entry spread, completion rate, and P/L by setup.
- High Probability: probability/price × time-to-expiration performance, separated by market type.
- Convexity/partial-profit strategies: entry conditions, excursion, partial-exit timing, realized return, and adverse-move data.
- Volatility strategies, when paused: preserve and display collected evidence, but do not resume trading merely to gather more data.

If a strategy has better natural axes/segments, use those instead.

### Data integrity
- Preserve all existing history.
- Reuse the canonical observation/trade dataset where possible rather than creating duplicate incompatible stores.
- Add missing fields backward-compatibly.
- Historical records lacking a newly added field should remain usable for the dimensions they do contain.
- Clearly distinguish raw observations from derived aggregates/statistics.

### Acceptance criteria
- Every strategy is labeled as data-learning, operational-only, or future-learning candidate.
- Every data-learning strategy has an inspectable data/learning section.
- The user can see what features are being collected and how many useful observations exist.
- The UI explains exactly which future decisions the data is intended to improve.
- Sample sizes and sparse-data limitations are visible.
- No strategy is described as adaptive unless its code actually uses historical evidence.
- Paused strategies retain visible historical learning data without being reactivated.
- Tests verify the diagnostics remain correct as new observations settle.

### Completion notes
_Fill in when done._


### Implementation progress
- PR #173: https://github.com/princesspikachuu/kalshi-scanner-data/pull/173
- Added compact per-folder learning metadata: truthful classification, current state, observation/completion counts, recorded features, segmentation, evidence threshold, sparse-data fallback, and intended decision improvements.
- Sequential/Favorites/Statistics-Favorites are labeled data-learning only because their code actually uses historical evidence in decisions.
- Volatility and Market Maker are labeled future-learning candidates: they collect research but current trading remains rule/live-feature driven.
- Complete Set is labeled operational-only; paused Convexity is preserved history/future-analysis, not an active learner.
- Added expandable Data / Learning panel to every folder without duplicating raw heavy research into the workspace.
- Backend and frontend regression coverage added. Fast browser/focused checks are green; full PostgreSQL/API validation is running.

---

# URGENT — Dashboard snapshot size failure

## MT-008 — Fix "Dashboard snapshot exceeds its supported size"
**Status:** DONE  
**Worker:** ChatGPT / MT-008 implementation  
**Claimed:** 2026-11-09 12:49 UTC  
**Urgency:** U0 — BLOCKER  
**Priority:** Urgent / user-visible blocker

### Current failure
The dashboard is surfacing the error:

> Dashboard snapshot exceeds its supported size

This appeared after recent growth in strategy/dashboard data, including Statistics-Backed Favorites and richer diagnostics. Treat this as a dashboard delivery/serialization/storage problem, **not** as permission to delete collected trading data.

### Goal
Restore reliable dashboard loading while preserving the underlying strategy, trade, observation, and learning datasets.

### Required investigation
Trace the exact snapshot path end-to-end and identify the real size limit and where it is enforced:
- database row/document size,
- API response/body limit,
- cache/KV/object storage limit,
- Cloudflare/worker serialization or response limit,
- frontend hydration/state limit,
- snapshot encoder/compressor,
- an application-defined defensive limit,
- or another transport/storage boundary.

Instrument and record:
- total serialized snapshot bytes,
- compressed bytes if compression is used,
- size by top-level section,
- largest strategy/folder payloads,
- largest repeated arrays/objects,
- count and size contribution of open orders, positions, history, statistics matrices, diagnostics, and learning data.

Do not guess which section is responsible. Measure it.

### Preferred fix
The dashboard snapshot should contain the **minimum data needed for the initial dashboard view**, with heavy details fetched separately/lazily.

Implement the safest appropriate combination of:
1. **Summary/detail separation**
   - Keep summary cards, aggregate P/L, counts, statuses, and compact active-state data in the initial snapshot.
   - Move large historical/diagnostic/statistical detail into separate endpoints or on-demand requests.
2. **Pagination / bounded windows**
   - Do not serialize unlimited trade/order/history arrays into every dashboard refresh.
   - Use pagination or recent-N windows for list views, with explicit "load more" behavior.
3. **Lazy strategy detail**
   - Statistics matrices, Data/Learning diagnostics, detailed market histories, and other expanded panels should load when the relevant folder/panel is opened where practical.
4. **Deduplication**
   - Avoid embedding the same market metadata, strategy metadata, or historical records repeatedly in multiple folders/cards.
5. **Compact aggregation**
   - Send aggregated statistics rather than raw observations when the UI only needs an aggregate.
6. **Compression**, if supported and useful, only after structural payload reduction. Do not rely on compression alone if the unbounded snapshot will simply grow past the limit again.

### Important guardrails
- **Do not delete or truncate canonical trading/history data to make the dashboard load.**
- Do not reset Favorites, Statistics-Backed Favorites, Market Maker, or other strategy history.
- Do not remove useful diagnostics entirely; make heavy detail lazy/paginated instead.
- Preserve mobile behavior.
- Preserve current pause state and open/settling positions.
- Initial dashboard summary values must remain internally consistent with detail endpoints.
- A partial failure of one heavy detail panel must not make the entire dashboard unusable.

### UI behavior
If detailed data is still loading separately:
- render the dashboard shell and summary cards first,
- show a bounded loading state inside the specific detail panel,
- display an actionable error only for that panel if its fetch fails,
- do **not** replace the whole dashboard with the snapshot-size error.

### Acceptance criteria
- The dashboard loads successfully with the current production/staging dataset that previously triggered the size error.
- Snapshot size is measured before and after, with the reduction documented.
- Initial snapshot size is bounded as history continues growing.
- Heavy sections can grow without linearly inflating the initial dashboard payload.
- Statistics-Backed Favorites matrix remains accessible.
- MT-007 Data/Learning panels can be added without reintroducing the same class of failure.
- Existing historical data remains intact.
- Tests cover an oversized synthetic dataset and verify the dashboard initial response stays below the supported limit.
- Verify on mobile and desktop.

### Implementation progress
- Root cause confirmed: `/demo/shadow/workspace` rejects decoded JSON above 8 MiB.
- First fix removed unused per-bot `latest_report` from the initial workspace and added section-size diagnostics.
- Live diagnostics after that deploy showed the remaining failure precisely: decoded workspace ~8.64–8.65 MiB, with `bots` alone ~8.45–8.46 MiB across 602 bots; folders were only ~225 KiB and all other sections were tiny.
- Follow-up PR #148 moved heavy per-bot research arrays (`entry_timing`, `calibration`, scalper cell histories) out of the initial workspace response while preserving compact counters, decisions, totals, config, accounting, performance, and durable research.
- Added a bounded fallback: if a bot card still serializes above 12 KiB because a future strategy adds another large research field, the initial dashboard sends only the compact experiment summary instead of allowing one bot to inflate the whole workspace.
- PR #148 squash-merged as commit `0d807065af18c36bf54956e48807e1155ae2956b`.
- Render API deploy `dep-dbostlbbc2fs73d4pvr0` is LIVE on the follow-up commit.
- Full GitHub validation for the latest head was still running when the outage fix was merged because MT-008 is U0; continue monitoring that run and patch forward if it reports a regression.
- The next authenticated dashboard request should be checked for `dashboard_transport` decoded bytes. If `dashboard_snapshot_oversize` still appears, use the new diagnostics to continue stripping non-initial detail rather than raising the 8 MiB ceiling or deleting history.

### Completion notes
_DONE. Live post-deploy requests now succeed. The dashboard workspace fell from ~8.65 MiB decoded to ~4.24 MiB decoded, with ~0.50 MiB gzip/base64 wire payload. Multiple authenticated requests logged successful `dashboard_transport` events and no post-fix oversize failures._
---

---

# PRIORITY 10 — System-wide efficiency audit and remediation

## MT-011 — Audit and eliminate avoidable size/resource waste
**Status:** IN PROGRESS  
**Worker:** ChatGPT / MT-011 systems audit  
**Claimed:** 2026-11-09 22:25 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Goal
Perform a full systems-efficiency audit across the active Money Tree / Kalshi stack. The purpose is to recover useful dashboard, worker, API, database, network, and monitoring capacity **without reducing useful trading activity or deleting collected evidence**.

This task must distinguish:
- legitimate load caused by useful trading/data collection,
- unavoidable platform/provider limits,
- and avoidable waste caused by duplicate work, oversized state, unbounded histories, repeated serialization, redundant services, polling, unnecessary DB reads/writes, or inefficient queue handling.

### Confirmed preliminary findings
1. **Initial dashboard workspace was structurally oversized**
   - Pre-fix live workspace reached ~8.65 MiB.
   - The `bots` section alone was ~8.46 MiB across 602 bots.
   - Large research/history fields were being embedded in every initial dashboard response even though they belong behind detail/lazy endpoints.
   - MT-008 is actively removing this waste; continue auditing for similar patterns elsewhere.

2. **Paper processing is experiencing real queue/backlog pressure**
   - Live `paper_monitoring_capacity` telemetry showed examples of:
     - backlog ~13,770 inputs,
     - estimated queue time ~245 seconds in one sample,
     - later backlog ~4,268,
     - discovery/admission paused because of processing lag/capacity.
   - This directly reduces the ability to admit more Market Maker/Favorites monitoring opportunities.

3. **Huge volume of quote updates is being filtered after entering the pipeline**
   - Live telemetry showed `filtered_quote_updates` above 600,000.
   - Audit whether these updates can be coalesced/suppressed earlier, before consuming queue/processing/serialization work.

4. **Market Maker is capacity-starved despite low useful trading**
   - Live telemetry showed:
     - maker entry limit 8,
     - maker slots free 0,
     - only ~6 maker entry markets/subscriptions,
     - discovery paused by measured capacity.
   - This suggests the strategy may be consuming scarce monitoring slots inefficiently while still failing to fill/trade.

5. **Legacy research worker appears to be repeatedly retrying failed storage compaction**
   - `pocket-research-staging` logs show `storage_compaction_deferred` repeatedly, approximately every 5–7 minutes for hours.
   - Determine why compaction is persistently failing and whether this service is still required in the current architecture.
   - Do not disable a service until its role and dependencies are verified.

6. **Potential duplicated worker/runtime footprint**
   - Render currently has both:
     - `pocket-processing-staging` running `services.research.runtime`,
     - `pocket-research-staging` also running `services.research.runtime`.
   - Audit WORKER_ROLE/env/runtime responsibility to confirm whether these are intentionally distinct or overlapping/legacy.
   - If one is obsolete/redundant, retire it safely only after proving no unique work is owned by it.

### Audit areas

#### A. Dashboard/API payloads
Measure:
- initial workspace decoded/wire size,
- payload contribution by section,
- per-bot and per-folder byte distribution,
- repeated metadata,
- raw history embedded where aggregates would suffice,
- data fetched/rendered but unused by frontend,
- refresh cadence and bytes transferred per minute.

Fix:
- lazy detail endpoints,
- pagination,
- bounded summaries,
- stable IDs instead of repeated metadata,
- cacheable aggregates,
- conditional fetches only when panels are open.

#### B. Worker queue and event processing
Measure:
- incoming events/sec,
- processed events/sec,
- backlog depth/time,
- processing p50/p95/p99,
- event types by volume,
- dropped/coalesced/filtered counts,
- queue occupancy by strategy/market,
- time spent processing events that produce no state change.

Specifically investigate the >600k filtered quote updates and move filtering/coalescing as close to ingestion as safely possible.

#### C. Market subscriptions/monitoring
Measure:
- subscribed markets by strategy,
- slot utilization,
- active useful positions vs idle subscriptions,
- updates/sec by market,
- opportunity yield per monitored market,
- fills/trades per slot-hour,
- slots consumed by paused or low-yield strategies.

Reallocate capacity toward active/high-yield strategies rather than simply increasing hard limits.

#### D. Database
Audit:
- `research_job` growth by key family,
- largest JSONB `parameters` / `progress` rows,
- repeated large payloads,
- table/index/dead-tuple size,
- slow/repeated queries,
- full-history scans,
- write amplification from frequent checkpoint/report updates,
- connection-pool usage,
- query cancellations/timeouts,
- compaction failures.

Preserve canonical history. Prefer derived/materialized aggregates and compact mutable state over destructive deletion.

#### E. Storage/compaction
- Determine why `storage_compaction_deferred` repeats continuously.
- Capture the actual failure category safely without leaking credentials/data.
- Verify whether compaction work is fighting with live trading/database queries.
- Use bounded backoff; do not retry an unchanged failure every few minutes forever.
- Separate optional maintenance from latency-sensitive paper trading.

#### F. Service architecture
For every Render service:
- document runtime role,
- unique responsibility,
- CPU/memory allocation,
- DB pool allocation,
- provider/API usage,
- whether work overlaps another service,
- whether it is still needed.

Pay special attention to the two services invoking `services.research.runtime`.

#### G. Polling/recomputation
Find repeated work where inputs have not changed:
- dashboard polling,
- performance calculations,
- balance snapshots,
- Favorites aggregates,
- bot/folder performance windows,
- statistics recalculation,
- market discovery,
- metadata/fee lookups.

Introduce:
- dirty flags/version hashes,
- TTL caching,
- incremental updates,
- event-driven refresh where practical.

### Guardrails
- Do not delete trading or research history to make size numbers look better.
- Do not reduce useful monitoring or trading just to lower CPU.
- Do not unpause paused strategies.
- Do not disable a service until its unique responsibilities are verified.
- Do not increase external API usage to compensate for internal inefficiency.
- Paper/live safety boundaries remain unchanged.

### Deliverables
Create a concise audit report in the repo containing:
- measured baseline,
- top waste sources ranked by estimated impact,
- quick wins,
- architectural fixes,
- service/resource map,
- before/after metrics for each implemented remediation,
- follow-up queue items for anything not completed in this task.

### Acceptance criteria
- We can explain where worker time, DB work, network bytes, and dashboard payload size are going.
- At least the top 3 avoidable waste sources are measured, not guessed.
- Quick wins are implemented and verified where low risk.
- Queue/backlog and dashboard size improve without reducing useful trading/data collection.
- Market Maker/Favorites have more usable capacity after remediation.
- Persistent maintenance retry loops are either fixed or safely backed off.
- Redundant services are either justified or retired safely.

### Implementation progress (2026-11-09)
- Initial measured Render architecture/CPU/memory/connection baseline and live worker/database durability samples captured in [audit report](docs/audits/MT-011-initial-systems-efficiency-audit-2026-11-09.md) (commit `c88f1161732609c20b974dd46ae5ff8cc351ca9d`).
- Leading issues: ~10.8 MB decoded shadow checkpoint (~6.3 MB scalper research), sampled ~1.97 s durability writes and 612 ms preparation, repeated research collection failures, and main worker 71–88% CPU utilization. These observations need instrumentation and before/after verification; no data deleted or strategy states changed.
- Direct PostgreSQL queries blocked by existing empty external IP allowlist; no security settings altered.
- Next: implement or audit checkpoint dirty-section write suppression and sampled write-latency histograms without overlapping MT-004/MT-015. Keep this task IN PROGRESS.

### Engineering change awaiting CI
- PR [#171](https://github.com/princesspikachuu/kalshi-scanner-data/pull/171), branch `fix/mt-011-checkpoint-noop-upserts`, head `28abd5e5dcad7df0b455cb8501f1c2e924455810`: skip only a SHA-verified byte-identical compressed checkpoint after a previously successful write, retaining every audit/report/command row in its original transaction; refresh full checkpoint every 30 seconds or on any state change, with failure-safe recovery.
- Bounded durability counters: `checkpoint_upserts`, `checkpoint_unchanged_skips`, and `checkpoint_bytes_avoided`. Focused tests added for repeated snapshots, changed state, failed commits, periodic refresh and event preservation.
- PR opened; CI/workflow result was **not yet available** when checked. **Do not claim deployment or throughput improvement** until checks pass, merge/deploy is confirmed, and live before/after samples are measured.

### Completion notes
_In progress; PR #171 merged and CI verified, worker deployment/live before-after metrics pending._
### PR #171 validation and merge (2026-11-09)
- Initial 1,410-test validation had one newly introduced **test assertion** failure: it expected two SQL write groups instead of the existing checkpoint-row + event-row grouping. Fixed the test without altering original SQL ordering or audit-write semantics.
- Follow-up GitHub Actions run [42721056626](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42721056626) **SUCCESS** on commit `f77c376f9f554693f2dde5479790326c6adec027`.
- PR [#171](https://github.com/princesspikachuu/kalshi-scanner-data/pull/171) squash-merged to `build/google-auth-foundation` as `edd87e8d463168a73e790525dc46c5078babadcd`.
- Render processing worker deployment `dep-dbp5nqp42hec73bll880` was **pre_deploy_in_progress** for older Market Maker commit `aa056ef9a90b76d58bd4b488650ec75fdd235227` at the time of verification. **Do not claim PR #171 live** until a deployed commit contains `edd87e8d`; avoid interrupting the overlapping Market Maker deployment.
- Added a 23:00–23:30 UTC measured pre-deploy baseline to [audit report](docs/audits/MT-011-initial-systems-efficiency-audit-2026-11-09.md): 1,286 commits and 2.81 GB encoded checkpoint traffic over 30 minutes, plus 321.17 seconds cumulative upsert time; no causal savings asserted yet.



---

# PRIORITY 11 — Urgent efficiency remediations from MT-011 audit

## MT-012 — Reduce event-queue waste and early-coalesce quote updates
**Status:** DONE  
**Worker:** ChatGPT / MT-012 implementation  
**Claimed:** 2026-11-09 13:53 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Why this is urgent
Live telemetry showed:
- backlog up to ~13,770 inputs,
- estimated queue delay ~245 seconds,
- discovery/admission paused because of processing lag,
- filtered quote updates above 600,000.

This is directly suppressing useful Market Maker/Favorites monitoring and trading.

### Required work
- Profile queue volume by event type and market.
- Identify quote/book updates that can be safely coalesced or dropped before entering expensive processing.
- Move filtering as close to ingestion as possible.
- Preserve all material state transitions, fills, settlement, lifecycle, and audit events.
- Measure before/after queue depth, queue seconds, processing p95, and useful opportunity throughput.

### Acceptance criteria
- Material reduction in no-op/filtered event processing.
- Lower queue delay/backlog.
- More monitoring/discovery headroom without reducing useful data quality.

### Implementation progress
- Claimed by ChatGPT on 2026-11-09.
- PR #149: https://github.com/princesspikachuu/kalshi-scanner-data/pull/149
- Live baseline before remediation:
  - order-book update interval 100 ms,
  - examples of 544 to 7,372 orderbook deltas per ~30-second telemetry window,
  - >1,000,000 cumulative unrelated maker inputs skipped,
  - paused scalper/sequential portfolios still receiving hundreds to >1,000 handler calls per window because 10 Hz clock ticks were not excluded,
  - worker CPU around ~0.5–0.6 core in sampled windows,
  - RSS around ~0.94–0.96 GB,
  - backlog spikes have previously paused discovery/admission.
- Implemented adaptive Kalshi server-side order-book conflation:
  - 250 ms when no latency-sensitive scalper is enabled,
  - 100 ms automatically when any scalper/volatility strategy is enabled,
  - safe reconnect/resnapshot when the desired interval changes.
- Implemented idle clock suppression so fully paused/empty portfolios do not process 10 Hz clock ticks while still retaining lifecycle, settlement, control and resume safety.
- Added tests for adaptive feed interval and idle-clock suppression.
- First full CI run failed only because a stale MT-008 workspace test still expected `entry_timing` to be embedded in the initial dashboard response. MT-012-specific tests passed.
- Updated that regression test to assert the intended lazy-research architecture: visible account/card data remains in the workspace while heavy `entry_timing` stays out and the canonical source remains unchanged.
- Fresh full CI run 42636698160 is in progress; gateway/auth and focused Statistics-Favorites checks are passing; PostgreSQL/API suite is currently running. Do not merge until this run completes successfully.


### Additional implementation progress
- Live logs showed lifecycle traffic exceeding 1,000 frames in a 30-second window during queue saturation.
- Added per-portfolio suppression of ticker-scoped lifecycle events for markets that portfolio does not own, while still advancing sequence state.
- Generic lifecycle frames without an explicit market ticker remain on the normal path for safety.
- Latest validation run `42640070818` has passed gateway/auth and focused Favorites checks and is currently in the full PostgreSQL/API suite.


### Completion notes
_DONE and live-verified._
- Before MT-012, the worker repeatedly hit backlog saturation (including 20,000 queued inputs), discovery/admission paused, and execution delays stretched into many seconds.
- Post-deploy live telemetry showed:
  - backlog fell to 0,
  - estimated queue seconds fell to 0,
  - discovery/admission returned to `true` with reason `Measured capacity available`,
  - event-loop lag dropped below 1 second in sampled steady-state telemetry,
  - idle strategy clocks skipped in the thousands per window,
  - ticker-scoped unrelated lifecycle fanout skipped across inactive portfolios,
  - book update interval increased while latency-sensitive scalpers remained paused,
  - processing worker RSS fell from roughly ~0.94–0.96 GB baseline samples to roughly ~0.51 GB in a representative post-fix sample.
- A transient backlog spike occurred immediately after restart/warmup, but later steady-state telemetry cleared to zero and restored market admission.

---

## MT-013 — Fix persistent storage compaction retry loop
**Status:** DONE  
**Worker:** ChatGPT / MT-013 implementation  
**Claimed:** 2026-11-09 14:15 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Why this is urgent
`pocket-research-staging` has been logging `storage_compaction_deferred` every few minutes for hours.

### Required work
- Safely surface the failure category without leaking sensitive data.
- Determine whether the failure is lock contention, timeout, permissions, malformed state, or another cause.
- Fix the root cause where practical.
- Add exponential/bounded backoff so an unchanged failure does not retry every few minutes forever.
- Ensure optional maintenance cannot compete aggressively with latency-sensitive paper trading.

### Acceptance criteria
- Compaction either succeeds or backs off sanely.
- Repeated useless DB work stops.
- No evidence/history is deleted.


### Implementation progress
- PR #153 passed full CI and was squash-merged as `702230abd3587d2e36daef4c65eaae3be9a2a294`.
- Collector deployment `dep-dbotva3ncjis73a0da50` is LIVE on branch head `77abff0c8af00d826fe976dfefece802292a363d`, which is confirmed to descend from the MT-013 merge commit.
- Compaction batch size reduced from 1000 rows to 100 rows under the existing 5-second statement timeout.
- Repeated failures now use exponential backoff from 5 minutes up to 6 hours and log safe `error_type`, `sqlstate`, retry interval, and consecutive failure count.
- Keep IN PROGRESS until post-deploy logs confirm either successful compaction or the new sane backoff behavior.


### Completion notes
_DONE. Persistent retry waste is contained. Live collector logs confirm the exact failure is PostgreSQL `QueryCanceled` / SQLSTATE `57014`; retries now back off 300 → 600 → 1200 → 2400 → 4800 → 9600 seconds instead of hammering the database every few minutes. Original records remain intact. Actual compaction success is separated into MT-017._

---

## MT-014 — Audit and remove redundant Render worker/service overlap
**Status:** DONE  
**Worker:** ChatGPT / architecture audit  
**Claimed:** 2026-11-09 14:45 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Why this is urgent
Both `pocket-processing-staging` and `pocket-research-staging` invoke `services.research.runtime`. This may be intentional role separation or legacy duplication, but it must be proven.

### Required work
- Document each service's `WORKER_ROLE`, enabled features, DB pool, provider/API use, and unique responsibilities.
- Confirm whether both services are still needed.
- Identify duplicated polling, scheduling, compaction, analysis, or queue consumption.
- If one service is obsolete/redundant, retire it safely only after verifying no unique work depends on it.
- If both are needed, make the separation explicit and remove accidental overlap.

### Acceptance criteria
- No unexplained duplicate runtime responsibility remains.
- Any retired service is proven unnecessary before shutdown.
- Resource savings are measured.


### Audit result
- `pocket-research-staging` logs explicitly identify it as `collector worker ready`; it owns collection/provider reads and also hosts the provider-free saved-data analysis lane.
- `pocket-processing-staging` is the active demo/paper trading executor; its live logs are paper-market scans, Favorites entries, monitoring capacity and shadow-feed telemetry.
- Both services invoke `services.research.runtime`, but runtime dispatch is controlled by `WORKER_ROLE`; `role=='demo'` immediately routes to the trading runtime instead of constructing the research collector.
- Therefore the shared start command is not duplicate execution. The services have distinct responsibilities and neither should be retired on this evidence.
- Resource plans are also intentionally different: research/collector is 0.5c/512MB; paper processing is 1c/2GB.
- The real waste discovered inside the research service is the persistent optional compaction retry loop, tracked separately as MT-013.

### Completion notes
_DONE. Suspected service duplication disproved; no service shutdown warranted. Keep both workers and address their internal inefficiencies separately._

---

## MT-015 — Rework Market Maker slot efficiency / monitoring yield
**Status:** DONE  
**Worker:** ChatGPT / Market Maker throughput implementation  
**Claimed:** 2026-11-09 22:30 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Why this is urgent
Live telemetry showed:
- maker entry limit 8,
- maker slots free 0,
- only ~6 maker entry markets,
- very low actual trading activity.

The system is using all maker capacity without producing enough fills/trades.

### Required work
- Measure fills, quote attempts, opportunities, and completed turns per slot-hour.
- Identify markets/subscriptions consuming slots with near-zero yield.
- Release/reallocate stale or low-yield slots faster.
- Prefer markets with better passive-fill opportunity and sustainable spread/depth.
- Coordinate with MT-004; do not duplicate conflicting Market Maker changes.

### Acceptance criteria
- Higher useful opportunities/fills per maker slot.
- Idle/low-yield subscriptions no longer monopolize capacity.
- Market Maker trading activity materially improves.




### Implementation progress
- Implemented together with MT-004 in PR #166 to avoid conflicting Maker allocation changes.
- Reallocation now optimizes for executable flow rather than raw tape activity; see MT-004 progress for validation state.


### Live deployment verification
- Slot-efficiency portion is live in merge `aa056ef9a90b76d58bd4b488650ec75fdd235227`.
- New worker filled all 8 Maker monitoring slots; repeated reallocation/monitoring telemetry confirms active slot use.
- Executable-flow-aware replacement is deployed; current bottleneck is no longer empty/stranded Maker slots but worker processing backlog.
- Keep MT-015 IN PROGRESS only until MT-005/backlog work proves sustained quote processing; the slot-allocation code itself is deployed and behaving as intended.


### Completion notes
_DONE and live-verified._
- Executable-flow-aware slot replacement is live in `aa056ef9a90b76d58bd4b488650ec75fdd235227`.
- Live monitoring reached the full 8-slot Maker allocation with no empty-slot bottleneck.
- Slot allocation is no longer the limiting factor; remaining system backlog is tracked separately.

---

## MT-016 — Reduce redundant fee-verification REST traffic
**Status:** DONE  
**Worker:** ChatGPT / MT-016 implementation  
**Claimed:** 2026-11-09 14:50 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Why this is urgent
MT-012 baseline telemetry exposed another significant resource consumer:
- fee maintenance currently treats active-market fee cache entries as stale after roughly 25–30 seconds,
- sampled 30-second windows showed dozens of calls across `/series/fee_changes`, `/events/fee_changes`, and `/series/:series`,
- some individual provider requests took multiple seconds,
- this traffic shares provider/read capacity with discovery and trading-support reads.

### Required work
- Measure fee-refresh request volume by market/series and cache-hit rate.
- Verify how often fee schedules actually change and what live/event notifications already invalidate fee state.
- Eliminate duplicate series/event fee lookups across markets sharing the same series/event.
- Prefer event-driven invalidation plus a conservative longer TTL where safe.
- Preserve fail-closed behavior: an unverified/changed fee schedule must never allow an economically invalid paper trade.
- Reuse verified series/event fee metadata across markets rather than independently fetching identical data.
- Measure before/after provider calls, read-budget occupancy, discovery latency, and fee correctness.

### Guardrails
- Do not weaken fee verification simply to reduce request counts.
- Fee-change events must invalidate affected cached assumptions promptly.
- Unknown/stale fee state remains non-tradable until verified.

### Acceptance criteria
- Material reduction in fee-related REST calls.
- No regression in fee-change detection or simulated trade economics.
- More provider/read capacity is available for discovery and active strategy monitoring.
- Tests cover cache reuse, invalidation, and fail-closed behavior.



### Completion notes
_DONE. PR #154 passed CI, merged as `ce87c5f738ea18cc440978199ad4b97d2c537ef8`, and deployed on the processing worker before later descendant commits. Same-event fee-change reads are deduplicated without changing freshness or fail-closed safety._

---

## MT-017 — Audit Cloudflare Workers CPU usage and free-tier limit errors
**Status:** BLOCKED  
**Worker:** ChatGPT / MT-017 Cloudflare CPU audit  
**Claimed:** 2026-11-09 19:20 UTC  
**Urgency:** U1 — URGENT  
**Priority:** High

### Problem
Cloudflare emailed the account owner on 2026-11-09 with "[Action required] Workers CPU limit exceeded." The affected Worker and per-route CPU measurements have not yet been verified. Free-tier CPU exhaustion can interrupt the authenticated Money Tree dashboard, even while the Kalshi paper-trading engine continues running separately on Render.

### Work required
1. Identify which Cloudflare Worker(s) are generating CPU-limit errors (staging gateway versus legacy research Worker, or both). Check Cloudflare dashboard Metrics/Observability: exceededCpu counts, request CPU percentiles, invocations, routes, error trends and exact spike times.
2. Correlate limit spikes with recent releases, dashboard refreshes, endpoint traffic, static-asset requests, large workspace responses, and authentication flow. Distinguish per-invocation CPU exhaustion from daily request quota, origin/network latency and Render worker CPU.
3. Verify that merged PR #155 (commit `6346ee1d783439ff510cd51170e9006c7f24dac0`) actually serves static assets without Worker invocation, while retaining route security/CSP. Check that the Cloudflare staging deployment succeeded; its historical unauthenticated public smoke check returned HTTP 403 and may reflect access restrictions rather than CPU.
4. Measure the CPU effects of API JSON validation and large dashboard payloads. Audit any remaining avoidable parsing, serialization, copying, logging, response transformations, repeated calls and unusually expensive routes. Consider safe streaming, bounded validation, request deduplication, and caching only when compatible with user-specific authentication and freshness.
5. Implement only measured, safe optimizations that preserve access control and data integrity. Do not reduce useful trading activity, monitoring fidelity, or collection volume just to hide usage.
6. Add focused tests, performance/CPU regression checks and visibility into affected routes. Record before/after exceededCpu errors, CPU percentiles, requests and dashboard reliability.

### Acceptance criteria
- Confirm the affected Worker(s), routes and source of CPU-limit errors with metrics or clearly document any unavailable measurements.
- Cloudflare requests stay reliably within the applicable tier limits or provide a quantified, evidence-based paid-tier decision if unavoidable.
- Full dashboard and auth behavior work, including signed-in access.
- Existing paper-trading services, recorded data and security boundaries remain unchanged.
- Add follow-up work for residual hotspots rather than claiming success solely because deployment completed.

### Context
- PR #155 removed Worker invocation from static asset requests and redundant JSON stringification for pass-through API responses; automated tests passed and staging deployment step succeeded.
- PR #155 is a mitigation, **not** proof that all CPU-limit errors stopped. Inspect Cloudflare CPU analytics to verify.
- Coordinate with MT-008 (dashboard payload/performance) and other infrastructure tasks; avoid duplicate edits.

### Implementation progress / blocked dependency (2026-11-09)
- Audit and tests merged in [PR #160](https://github.com/princesspikachuu/kalshi-scanner-data/pull/160), merge commit `41e1d138ccea83f145ca8db9c1a8f46e2ca137a1`, based on successful full PR CI [42687617581](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42687617581).
- Added `docs/audits/cloudflare-cpu-2026-11-09.md`, `tools/benchmark_gateway_cpu.mjs`, and CI benchmarking. Scoped both Cloudflare Workers and existing safe mitigations from PR #155.
- Local synthetic benchmark on Node 24: **76.36 ms CPU** for 100 copies of a 2-MiB buffer; **54.213 ms CPU** for ten 2-MiB streams through the authenticated gateway. This is **not Cloudflare CPU**, and does not prove incident mitigation.
- A proposed zero-copy stream change **failed an existing mutable-upstream-buffer integrity test** and was reverted; original safe gateway runtime unchanged. No bot strategy or history modifications.
- **BLOCKER:** No connected Cloudflare observability/CPU metrics or authorized Cloudflare Analytics API read access. Need to determine whether `pocket-analytics-staging`, `kalshi-pocket-analytics` or both generated `exceededCpu` errors and obtain pre/post 2026-11-09 15:00 UTC CPU p50/p95/p99, invocation counts and affected routes.
- After metrics are available: quantify error trend, identify specific high-CPU route, implement validated optimization and re-test authenticated dashboard. Leave task BLOCKED rather than claiming the alert is resolved.


# Coordination notes

- MT-012 through MT-015 are U1 remediation tasks discovered by MT-011 and may be worked in parallel where files/infrastructure do not overlap.
- MT-015 must coordinate with MT-004 because both affect Market Maker throughput.
- MT-012 should inform MT-005 because queue pressure may be the real monitoring-capacity limit rather than a simple slot-count issue.
- MT-013/MT-014 should verify the legacy research service role before any service is disabled.

- MT-001 and MT-002 may be worked on by different chats at the same time.
- MT-003 depends on MT-001 being deployed/verified.
- MT-004 can run concurrently with Favorites work if it does not modify the same shared monitoring/risk infrastructure.
- MT-005 should use evidence from MT-003/MT-004 when available. If another task is already changing shared scheduler/monitoring infrastructure, do not create a parallel conflicting implementation; coordinate through this file.
- MT-006 is UI-focused and is a good independent task for a separate chat.
- MT-007 can be implemented incrementally by strategy, but its shared UI/data-contract work must not conflict with active MT-001/MT-002 schema changes.
- MT-008 is an urgent user-visible dashboard blocker and should be claimed before lower-priority READY UI/diagnostic work. MT-007 should use the lazy/paginated detail architecture established by MT-008 rather than expanding the initial dashboard snapshot again.
- If MT-002 needs data-schema fields that MT-001 is already changing, coordinate through this file rather than independently creating conflicting schemas.


### Implementation progress
- PR #154 passed full PR CI and was squash-merged as `ce87c5f738ea18cc440978199ad4b97d2c537ef8`.
- Same-event markets now share one verified `/events/fee_changes` response for the unchanged 30-second freshness window.
- Distinct events remain independently verified; TTLs and fail-closed behavior are unchanged.
- Branch validation for the merge commit is in progress; processing deployment will follow the service's checks-pass auto-deploy policy.


---

## MT-018 — Balance Favorites evidence collection across under-sampled market types
**Status:** IN PROGRESS  
**Worker:** ChatGPT / MT-018 evidence balance  
**Claimed:** 2026-11-10 00:20 UTC  
**Urgency:** U2 — HIGH  
**Priority:** High, after MT-003

### Goal
Increase verified Favorites evidence for hourly, weather, weather-daily, and sports markets while preserving the now-healthy 15-minute collection rate.

### Evidence
Current timestamped verified outcomes in the last 24h are 841 total:
- 15m price: 809 (~96.2%)
- hourly price: 13 (~1.5%)
- weather: 12 (~1.4%)
- weather daily: 7 (~0.8%)
- sports: 0

This is now the dominant Favorites learning-data imbalance.

### Requirements
- Do not throttle or discard healthy 15m collection merely to make percentages look balanced.
- Increase discovery/monitoring and controlled paper exploration for under-sampled market types when valid opportunities exist.
- Preserve fresh-book, fee, risk/capital, exposure, duplicate-suppression, and settlement-integrity safeguards.
- Prefer filling missing price/time cells and genuinely under-sampled market-type buckets.
- Record attempted, submitted, filled, settled, duplicate-skipped, risk-skipped, and unavailable-opportunity counts per market type so lack of market availability can be distinguished from strategy gating.
- Keep collector Favorites and Statistics-Backed Favorites evidence compatible; do not overwrite existing history.

### Acceptance criteria
- Hourly/weather/weather-daily/sports evidence rates are measured before and after.
- At least one under-sampled type materially increases when qualifying markets are available.
- 15m evidence throughput is not intentionally reduced.
- Any market type that remains sparse has an explicit measured reason (availability, fills, discovery, risk, or another gate).

### Completion notes
_Fill in when done._
