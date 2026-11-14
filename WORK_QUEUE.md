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
**Status:** IN PROGRESS — P0/U0, remains blocked on external operator evidence  
**Worker:** ChatGPT / storage-outage investigation  
**Claimed:** 2026-11-10 17:30 UTC  
**Priority:** Before MT-011 throughput verification or any resumed trading

**Full historical record, preserved byte-for-byte:** [MT-019 investigation and checkpoints](docs/audits/MT-019-work-queue-history-2026-11-12.md). This externalized 148,170 characters of previous MT-019 checkpoints and findings without deleting the investigation or touching trading data. For up-to-date state, follow this shorter active checkpoint, not older historical statuses.

### MT-019 owner WAL-directory permission also denied (2026-11-13 PT)
- User privately connected as verified owner `pocket_staging` in Render Shell and performed read-only permission check for `pg_catalog.pg_ls_waldir()`. Result: **`Owner WAL inspection: permission required`**. Runtime and owner both unable to inspect live `pg_wal` bytes via SQL; do not try to bypass with broader SQL grants. WAL occupancy is **still unknown**, not zero; physical disk safe-to-reclaim gate remains open. Seek provider-side size/retention evidence or supported pg_stat views (cumulative counters are NOT WAL directory occupancy). Continue non-destructive dedicated role setup/API hold checks; **no cleanup deletion until safe**.

### MT-019 WAL directory privileges unavailable to runtime account (2026-11-13 PT)
- Authorized read-only Render processing Shell checked `pg_catalog.pg_ls_waldir()`: reported **`WAL directory inspection: permission required`** for current `pocket_research_runtime` user. No WAL byte value was obtained. Do not interpret access denial as absence of WAL, or grant runtime account server-file access merely to inspect. No SQL writes were made. Next prefer provider-managed metric or owner-only read-only privilege check; render disk usage screenshot is percent of 15 GB, not WAL headroom. No bulk archive/deletion before WAL/physical safety gate.

### MT-019 R2 archive writer round-trip passed (2026-11-13 PT)
- Operator ran isolated `services.demo.maintenance.object_store` R2 writer test from processing Render Shell: generated random object under `mt019/connection-tests/<uuid>`, uploaded with `IfNoneMatch='*'`, read object back and compared SHA-256. User reported **PASS**. Script attempted deletion of that exact newly-created temporary object; user did not provide the cleanup line, so **object deletion not independently verified**. This verifies current R2 writer connectivity and integrity for the test payload only, **not whole trading history or backup coverage**, and does not activate any archival. Normal app role still not authorized to delete. Remaining gates: dedicated isolated maintenance login (currently NOLOGIN), API hold/drain and all writer quiescence, physical disk/WAL headroom, complete archive record proof before first restricted diagnostic reclaim.

### MT-019 PUBLIC cannot execute reclaim function (2026-11-13 PT)
- Authorized internal Render read-only inspection of `pg_proc.proacl` / `aclexplode` confirmed `PUBLIC can execute cleanup: False` for `public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb)`. Together with prior exact 14-field role grant check, the installed fence is inaccessible to PUBLIC and normal app login cannot directly delete. `pocket_archive_maintenance` remains NOLOGIN; no archive or deletion executed. Continue R2 scoped writer upload/readback verification, private isolated SCRAM credential, writer hold/drain, actual physical/WAL safety before any cleanup batch.

### MT-019 least-privilege archive role grants independently verified (2026-11-13 PT)
- Operator ran read-only live role privilege inspection through existing internal Render worker DATABASE_URL. Output for `pocket_archive_maintenance`: `rolcanlogin=false`, `rolcreaterole=false`, `rolsuper=false`, `rolinherit=false`, `rolreplication=false`, `rolbypassrls=false`, `has_table SELECT=true`, `INSERT=false`, `UPDATE=false`, `DELETE=false`, `TRUNCATE=false`, `public schema CREATE=false`, `has_function EXECUTE=true`, `pg_auth_members member count=0`. All fourteen live assertions match planned isolated NOLOGIN role (but no PUBLIC function EXECUTE audit yet). **Do not claim archive/delete has occurred.** Dedicated role SCRAM credential still needs owner-only private creation and isolated use; no broader worker rights. Remaining gates R2 write/readback, API hold/drain, verified physical/WAL headroom and independent financial/archive restore checks.

### MT-019 owner-installed least-privilege fence (2026-11-13 PT)
- User ran operator-only `infra/archive-maintenance-role.sql` via private `pocket_staging` owner connection in Render Shell. Output: `Restricted archive role installed: True`, `Protected cleanup function installed: True`. These establish SQL object presence only, **not yet live privilege verification or independent functional test**. Installer creates `pocket_archive_maintenance` NOLOGIN and `public.mt_reclaim_shadow_diagnostics` restricted SECURITY DEFINER. Owner URL was unset afterward. Do NOT rerun non-idempotent installer; do not issue any archive/delete until live grants, role isolation, R2 write/readback, API writer quiescence, physical/WAL headroom, financial recoverability are verified. Next read-only SQL verify role attributes, table/schema privileges and function EXECUTE public revocation using normal `DATABASE_URL`.

### MT-019 privately verified database owner connection (2026-11-13 PT)
- User entered Render internal `pocket_staging` owner URL privately in processing Shell, ran read-only permissions check, and received `Connected as: pocket_staging`, `Can create roles: True`, `Superuser: False`, `research_job owner: pocket_staging`. Their runtime account remains `pocket_research_runtime` and must not be elevated. Previous instructions told them to `unset OWNER_DATABASE_URL` after the check; do not assume the secret remains available or ask them to disclose it. This confirms owner can install isolated role/function but not that installation or data reclamation occurred. Before any archival/deletion: verify R2 write+readback, API quiescence, physical/WAL safety and scoped role credentials, then controlled trial. No rows have been reclaimed by this step.

### MT-019 runtime account privilege verified (2026-11-13 PT)
- Operator ran read-only PostgreSQL role/owner check in Render processing shell. Connection `current_user=pocket_research_runtime`, owner of `public.research_job=pocket_staging`, `rolcreaterole=false`, `rolsuper=false`. The runtime credential is **not authorized** to install `pocket_archive_maintenance`; preserve this isolation. Restricted role/function both confirmed absent in prior check, while R2 write env *presence* checked only. Next owner-only installation requires privately sourced owner connection from Render database, plus independent physical disk/WAL safety, API quiescence, reliable R2 write+readback, and rotation of previously exposed owner credentials. No SQL privilege elevation, maintenance SQL application, archive, or delete yet.

### MT-019 live restricted-role readiness result (2026-11-13 PT)
- Authorized processing-worker Render Shell reported `R2 archive configuration: PRESENT` (only env presence, **not verified write/readback**) and live SQL `Restricted archive role exists: False`, `Protected cleanup function exists: False`. Therefore the least-privilege reclaim role/fence is NOT installed. Do **not** use the ordinary worker `DATABASE_URL` to perform DELETE, bypass safeguards, or imply archival is authorized. Next read-only inspection of current user and `research_job` ownership plus create-role privileges, then isolate maintenance account; independently verify physical disk/WAL headroom and API writer hold before any reclaim.

### MT-019 archivable vs protected shadow payload sample (2026-11-13 PT)
- Authorized Render Shell bounded `research_job TABLESAMPLE SYSTEM(0.2) REPEATABLE(31)` plus `CASE` for exact six diagnostic kinds, `succeeded`, age >24h and `NOT (progress ? 'archive')` measured: **Other records 3,676 rows / 2,900,810 sampled JSON bytes; Eligible diagnostics 959 rows / 2,162,799 bytes; Protected or ineligible shadow events 2,428 rows / 1,404,988 bytes**. Eligible share **33.4% of all sampled JSON payload bytes**, ~60.6% of sampled shadow JSON payload bytes. These are estimates from a tiny block sample, not byte-reclaimable disk accounting; DO NOT project 33.4% directly onto DB physical usage. Eligible diagnostics satisfy preliminary archive filter, not complete safety gates; no records deleted. Validate bulk R2 archive write/readback, complete manifests, writer quiescence, least-privilege maintenance, actual filesystem and WAL safety before any reclaim. A readonly R2 token alone cannot archive new rows.

### MT-019 bounded research_job payload sample (2026-11-13 PT)
- Operator ran read-only `research_job TABLESAMPLE SYSTEM(0.2) REPEATABLE(31)` with grouped `pg_column_size(parameters)+pg_column_size(progress)`. Output: `individual shadow events`: **3,387 sampled rows, 3,567,787 sampled JSON bytes**; `other research records`: **3,536 rows, 2,345,695 bytes**; `other demo records`: **140 rows, 555,115 bytes**. No `diagnostic batches` were represented by the grouping. Approx **55.2% of sampled payload bytes** occurred in the `demo/shadow/event/` namespace. The category is broader than the six archiver-allowlisted diagnostic event kinds; **do not interpret 55.2% as reclaimable storage**, because sample covers only payload not table/TOAST/index/WAL, and mixes protected financial/control originals. No archival/deletion occurred.
- Next safe evidence: bounded sample split for six allowlisted event kinds with succeeded, older than 24h and no archive progress flag, versus protected/ineligible shadow rows and other namespaces. Estimate only rough payload share, then plan complete R2 readback, physical disk/WAL safety and scoped maintenance before any delete.

### MT-019 compressed diagnostic batch preview found zero candidates (2026-11-13 PT)
- Authorized Render Shell **read-only** `RECOVERY_DATABASE_URL="$DATABASE_URL" python -m services.demo.shadow_batch_archive_recovery --age-hours 24 --batch-size 8` returned `batch_rows=0`, `original_events=0`, `mode=preview`, `eligible_sample_only=true`, `no_writes=true`. Does not show all compressed batch history absent; only no first-page eligible rows.
- Next: safe, bounded read-only `research_job TABLESAMPLE SYSTEM` by `idempotency_key` family and approximate JSON bytes with query timeout; validate whether diagnostic source owns meaningful bytes before archive/delete planning. Keep financial/control originals protected and physical/WAL gates intact.

### MT-019 preview sample of aged safe diagnostic originals (2026-11-13 PT)
- In an authorized Render Shell the operator ran **read-only** `RECOVERY_DATABASE_URL="$DATABASE_URL" python -m services.demo.shadow_archive_recovery --age-hours 24 --batch-size 100`. Output: mode `preview`, `eligible_in_sample=100` of `batch_limit=100`, hot_hours=24; event types: `SCALPER_OBSERVATION_BATCH` 61; `FAVORITE_STAT_DECISION` 27; `FAVORITE_ENTRY_DECISION` 6; `FAVORITE_REPEAT_OPPORTUNITY` 3; `FAVORITE_ENTRY_COHORT` 2; `FAVORITE_TRIAL_QUALITY` 1. One index-ordered page, **NOT** total eligible count, byte estimate, archived/readback proof, or permission to reclaim.
- Existing operator diagnostics in `services/research/storage_audit.py` include read-only `research_job TABLESAMPLE SYSTEM(1) REPEATABLE(31)` grouped by key namespace and sampled JSON bytes; use a small, read-only bounded measurement to estimate relative family byte shares, especially TOAST-heavy diagnostic batches vs protected financial/control data. Existing `services/demo/shadow_batch_archive_recovery.py` separately has default preview and `--batch-size` max 8; verify packed-batch candidates before any plan. Keep WAL/physical safety and writer quiescence gates.

### MT-019 operator read-only footprint confirmed (2026-11-13 PT)
- Authorized internal Render Shell ran `RECOVERY_DATABASE_URL="$DATABASE_URL" python -m services.demo.shadow_pg_storage_footprint --execute-readonly`; read-only contract `mt019-readonly-pg-logical-footprint-v1`, database `pocket_staging`, logical database size **9,127,331,507 bytes**. `research_job` **6,198,140,928 bytes total**, **2,801,238,016 heap**, **982,048,768 indexes**, remainder ~2.415 GB TOAST/related storage. `research_dataset` **1,351,368,704**; `collection_page` **445,038,592**; `raw_archive` **286,326,784**; `research_campaign_work` **277,192,704**; `research_dataset_artifact` **227,467,264**; `research_artifact` **225,239,040**. `research_job` ~67.9% of logical DB. Stale/suspicious stats for `research_job`: n_live_tup=0, n_dead_tup=11: **do not infer empty table** or safe reclaim.
- All physical disk/WAL headroom and all-time R2 coverage flags still false. Separately user confirmed private R2 read-only list-objects connection SUCCESSFUL, but this proves only credentials and listing, not independent archived-original readbacks. Neither result permits deletion or restoration. Next evidence: bounded preview (`RECOVERY_DATABASE_URL="$DATABASE_URL" python -m services.demo.shadow_archive_recovery --age-hours 24 --batch-size 100`) and detailed read-only counts/byte shares by allowlisted diagnostics vs protected events, then controlled archival gate review. Don't execute until gates satisfied.

### MT-019 correction — graph percentage drop is NOT verified storage reclamation (2026-11-13 PT)
- Operator correctly notes the database capacity was **increased from 10 GB to 15 GB**, and the chart's lower utilization percentage should **NOT** be characterized as actual bytes freed. At Nov 13 15:00 PST the screenshot shows **88.15% of 15 GB occupied (approximately 13.22 GB used, 1.78 GB unoccupied)**. There is no comparable absolute occupied-bytes baseline across the capacity increase that proves any meaningful storage reduction. The previously verified 10-row diagnostic archive/deletion is trivial in disk terms; PostgreSQL row deletion also does not guarantee smaller physical files. Treat prior language about 'dropping from ~100% to 88%' as a capacity-denominator change/ambiguous graph, **not evidence that cleanup worked**.
- Continue focusing on read-only current relation/index/TOAST footprint, identifying historical nonfinancial originals eligible for verified R2 offload, and separately establishing physical disk/WAL safety before any SQL deletion/repack. Preserve all financial/control and unique historical records. No storage reclaimed by this note.

### MT-019 shift to measurable safe storage reduction — 2026-11-13 PT
- Operator prefers continuing efforts to **reduce 88.15% physical disk usage**, not making Render support first stop. Do not restart collection/trading, increase billed disk or run unsafe VACUUM FULL/pg_repack to force the chart down; 15 GB disk has approximately 1.78 GB currently unoccupied, insufficient to blindly rewrite large tables. Normal VACUUM may make pages reusable inside PostgreSQL but does not reliably shrink used physical files or the Render graph.
- Fresh retrospective read-only Render logs (2026-11-09 23:35 UTC) measured logical database **8,816,957,107 bytes**, with `research_job` **5,897,060,352 bytes** (~66.9% of logical DB; table+TOAST 4,953,161,728, indexes 943,898,624); live tuple estimate 3,134,733 and dead tuple estimate 43,658. The majority of recent logical growth Nov 7–9 was in `research_job`. These are HISTORICAL, NOT current table sizes, and `research_job` mixes valuable financial/control and disposable old diagnostics; never truncate/drop it.
- Next actionable safe internal probe, without database firewall or credential change: from already-authorized Render processing worker Shell with existing `RECOVERY_DATABASE_URL`, run `python -m services.demo.shadow_pg_storage_footprint --execute-readonly`; this is a bounded, read-only current database logical/table size census with no payload/event reads or mutation. Check separately a small read-only `pg_stat_activity`/WAL state if authorized. Compare sizes against physical Render graph and archive manifests. Scope an independently verified *small* eligible R2 offload ONLY after WAL/headroom and scoped SQL maintenance access gates; index pruning only if duplicate/nonessential indexes can be proved, not guessed.
- Physical disk current 13.22 GB used vs Nov 11 *historical* logical DB 9.13 GB suggests a multi-GB difference, but **its cause is unverified** (WAL, other DB files, provider accounting, timestamp differences). Do not label the difference as WAL or reclaimable bloat without actual evidence. Render disk remains 88.15% used on operator screenshot; safe physical capacity margin not established.

### MT-019 operator physical disk evidence — 2026-11-13 15:00 PST
- **Operator-provided Render Dashboard > PostgreSQL Metrics > Disk Usage screenshot** (2026-11-13 15:00 PST tooltip): **88.15% occupied persistent disk**. DB provisioned volume remains **15 GB**; equivalent approximate current occupied **13.22 GB** and unoccupied **1.78 GB** (**11.85%**), subject to provider display/rounding. Historical chart showed near **100% around Nov 10**, declining to high 80s by Nov 11 and staying roughly flat through Nov 13. This is an **observed physical disk utilization metric**, not proof of adequate write/WAL headroom or capacity after changes. Do **not** recommend restart, reclamation, VACUUM FULL, pg_repack or automatic archiving from this single number.
- **Still blocking:** Actual `pg_wal` directory size/retention and space safety assessment (prior `pg_ls_waldir()` was permission denied), current rate/peak assessment, independent R2 READ/full originals and catalog verification, scoped maintenance role and secret rotation, all-writer/API drain, authoritative venue settlement and cash/lot/fees. Ask Render Support for read-only WAL occupancy/retention, whether the 88.15% physical reading includes WAL and any other significant on-volume consumers, and whether ~1.78 GB remaining is safe for the planned bounded archival/reclamation. No changes to production until reviewed. Proven physical usage alone does not close MT-019.

### MT-019 independent engineering closeout — all code/CI/deployment checks complete (2026-11-12 PT)
- **FINAL PR #226** `fix/mt019-control-backup-tail-boundary` merged squash `1d31c86d370a355564425f61253bd290a8915b7e` from head `013b557e1b35a2d9c29aef369478d43fcfe14837`. Full premerge GitHub CI `43361374939` **SUCCESS** and postmerge CI `43361766006` **SUCCESS**, including disposable PostgreSQL tests. It prevents silently "complete" control backups if previously unseen malformed/legacy control keys sort above the V2 index window. Both in-memory and spooled backups fail closed before R2 publication, and all source records remain intact.
- **Collector deployment verified:** Render exact merged #226 release `1d31c86d370a355564425f61253bd290a8915b7e` LIVE at **2026-11-13 03:56:31 UTC**. Its exact startup `storage-recovery-hold-v1` log at **03:56:21 UTC** confirms `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`, and `predeploy_database_check=deferred`. No collector or managed PostgreSQL error-level log entries were returned for the inspected deployment window. API remains on its older manual version; research worker remains on the previously verified hold. No API migration, credential, R2 or production SQL action performed.
- **INDEPENDENT ENGINEERING WORK COMPLETE.** All identified safe, accessible MT-019 code fixes, unit/disposable PostgreSQL CI, and held collector deployment verification are finished. Full operator handoff: `docs/audits/MT-019-independent-operator-handoff.md` (on main); detailed final safeguard: `docs/audits/MT-019-control-backup-tail-coverage.md` (production branch). **Keep MT-019 OPEN / P0 / U0:** actual physical Render volume free disk and `pg_wal` headroom, independent R2 READ and exhaustive hot/packed/legacy manifest/cold originals, isolated scoped SQL maintenance account and exposed DB secret rotation, complete API/all-writer quiescence, and authoritative venue settlement + paper wallet/partial exit/cash/fees reconciliation remain operator-only gates. Do not re-enable collection, trading, automatic archiving, reclamation, deletion or training on CI evidence. No additional independent code is presently warranted.

### MT-019 deployment and post-merge acceptance checkpoint — 2026-11-12 PT
- **PR #225 fully verified and LIVE**: exact tested head `0e2d6abb5791cd18591cbaeff379750147c4667d`, merged squash `064c12bab71445418a7a469f49eda0887ab99be7`, full premerge CI `43350408874` SUCCESS and postmerge CI `43354831041` SUCCESS. Render collector deployment `dep-dbr7ngm7bikc73elctj0` LIVE at 2026-11-13 02:54:34 UTC. **Exact new predeploy startup log** 02:54:23 UTC confirms `storage-recovery-hold-v1`, `collection_enabled=false`, `trading_enabled=false`, `worker_role=collector`, `predeploy_database_check=deferred`. No collector or PostgreSQL error-level entries in deployment window.
- Static safety acceptance: PR #225 fail-closes previously hidden raw/packed/manifest namespace keys at bare prefix or above `prefix + 'zzzz'` within one READ ONLY PostgreSQL snapshot. This is a bound correctness check, **not** proof all-time archive coverage, settlement, complete P/L or readiness to restart.
- Live Render configuration read-only: collector autoDeploy=yes on `build/google-auth-foundation`; API autoDeploy=no and research worker autoDeploy=no on the same branch. API still earlier manual version and can run DB migration on deploy; **do not deploy for diagnostics**. DB `pocket-db-staging` AVAILABLE, provisioned 15 GB, disk autoscaling OFF, IP allowlist empty. Read-only Render DB metrics 22:00–03:00 UTC show CPU ~0.006–0.007 cores, memory ~316–321 MB, 1–2 active connections. They **do not** report filesystem free disk, WAL occupancy, archive integrity, or global writer quiescence.
- **Independent, safely accessible implementation checks completed for now.** Further recovery requires operator-only proof of actual physical Render Disk Usage current/peak/trend and `pg_wal` headroom; independently scoped R2 READ and exhaustive hot/raw/packed/legacy manifest/R2 verified original enumeration; separate least-privileged SQL maintenance role; rotate exposed DB password; API/in-flight/all-writer drain; venue-authoritative settlement and paper wallet lot/partial exit/cash/fees reconciliation. Keep `MT-019` IN PROGRESS and keep trading/collection/automatic archiving/reclaim/deletion OFF. No production SQL/R2 mutation, IAM/allowlist, pricing, billing or worker setting change in this continuation.

### MT-019 new boundary-integrity checkpoint — 2026-11-12 PT
- **DRAFT PR #225** `fix/mt019-index-key-boundary-guard`, current head `0e2d6abb5791cd18591cbaeff379750147c4667d`; full CI run `43350408874` in progress at checkpoint (first job initializing). Offline SQL scans use `idempotency_key < prefix+'zzzz'` and could silently overlook a bare-prefix row or malformed/legacy key above this upper key while declaring indexed range scanned. New fail-closed guard performs 2 indexed, same-snapshot READ ONLY existence queries per allowlisted namespace and raises if those hidden keys exist. Wired to `read_postgres_snapshot_window`, `scan_postgres_index_snapshot`, and `audit_manifest_namespace_snapshot`; unit tests and disposable PostgreSQL regressions verify source rows retained. **Do not merge before full exact-head CI success.** No production SQL/R2 reads or writes, API/worker deployment, credentials, network/allowlist, trading/collection or archive changes.
- Recent Render review still shows PostgreSQL available (15 GB, autoscaling OFF, empty allowlist) and last held collector LIVE `cb2f1643`; physical free disk/WAL, scoped R2 READ, archive maintenance role, credential rotation, source completeness and settlement/cash/lot/fee reconciliation are hard blockers. Never treat static tests as whole-history or safe-restart proof.

### Continued verification — 2026-11-13 01:16 UTC (November 12 PT)
- **No new PR or production change necessary in this pass.** The earlier operator-only read-only diagnostic PR #223 remains merged, with full GitHub CI and postmerge CI successful; exact collector commit `cb2f1643507ff9144982a0c1243538c9c23f637e` is LIVE. The 2026-11-12 23:07:04 UTC startup receipt confirms collection=false and trading=false. Research worker remains on `585252f2`, with its held startup receipt previously verified; API remains on older manual `93c86efc` (migration predeploy).
- PostgreSQL still shows AVAILABLE, 15 GB allocated, disk autoscaling OFF, and no external IP allowlist. Read-only Render log queries for 2026-11-12 22:30–2026-11-13 01:30 UTC found **zero error-level entries** in the database, collector and research worker; no new archive operations were executed by this chat. Zero error logs do **not** verify host free space, data completeness, or all-writer quiescence.
- This chat cannot obtain live **physical Disk Usage** via the Render connection; external SQL access is deliberately blocked, and the existing operator-only logical-footprint CLI requires an authorized internal shell. Do not open networking, grant elevated roles, rotate secrets through chat, or trigger a migration for convenience. **The next useful evidence must come from the existing Render DB Metrics Disk Usage page (used/free/peak/trend) and an independently authorized WAL headroom inspection.** Then scoped R2 readback and completeness checks can proceed; a complete restart still needs API/all-writer drain and settlement/cash/lot/fees reconciliation. Retain the recovery hold and keep MT-019 IN PROGRESS.
- Shared work queue now has the full original historical investigation preserved separately under `docs/audits/MT-019-work-queue-history-2026-11-12.md`, through docs-only PR #224. No other task contents changed by this pass.

### Latest verified checkpoint — 2026-11-12 UTC

- **PR #223 fully verified:** [one-shot read-only PostgreSQL logical footprint](https://github.com/princesspikachuu/kalshi-scanner-data/pull/223) merged as `cb2f1643507ff9144982a0c1243538c9c23f637e`. Exact-head full CI `43322930742` and postmerge CI `43325376828` both SUCCESS. Render collector LIVE on the exact merged commit since **2026-11-12 23:07:18 UTC**. Its 23:07:04 UTC `storage-recovery-hold-v1` log confirms `collection_enabled=false`, `trading_enabled=false`, role collector, DB predeploy check deferred.
- Separate research worker remains held on `585252f2` (00:29:17 UTC recovery hold logged collection/trading OFF). API remains on older manual LIVE `93c86efc`, with a predeploy migration that must **not** run just to obtain audit endpoints.
- Render PostgreSQL `pocket-db-staging`: AVAILABLE, **15 GB provisioned**, disk autoscaling OFF, external IP allowlist **empty**. The connected Render SQL reader is blocked by that deliberate network boundary; **do not open the allowlist** for diagnostics.
- Independently verified historical facts: the **4,190-record** control snapshot with **98 R2 chunks** had verified readback; one earlier **10-row** diagnostic R2 archive and exact source-ID reclaim was verified. Last older logical PostgreSQL footprint was `9,127,331,507` bytes (Nov 11 UTC). These are *not* physical free disk or WAL headroom, global history recovery, or safe-to-restart proof.
- Read-only Render review found successful periodic WAL archiving/recycling and no error-level database logs in the inspected window; neither establishes physical capacity. The merged #223 diagnostic is **not yet executed on production**, and reports only logical DB/table sizes if explicitly invoked from an already authorized internal Render shell.
- Recent maintenance/archive scan log searches did not surface new archive-scan events in the inspected held-worker window. Absence of those entries does **not** prove database-wide writer quiescence. All trading, collection, automatic archival and deletion stay OFF.

### Still-blocking recovery gates

- **Physical disk and WAL:** Record actual Render PostgreSQL [Metrics → Disk Usage](https://dashboard.render.com/d/dpg-dbgcrl6c6qcc73f1hi1g-a) (current value, recent peak and trend) and separately verify `pg_wal` occupancy/headroom. A 15 GB allocation, `pg_database_size()`, cumulative `pg_stat_wal`, CPU and connection metrics are insufficient.
- **Access/authority:** Independently scoped R2 READ-only credential and verified object/manifest readbacks; least-privileged archive maintenance SQL account/function; rotate the previously exposed PostgreSQL credential. Do not paste secrets into GitHub or chat.
- **Actual data completeness:** Stable complete hot raw+packed+legacy/current manifest+R2 original enumeration, orphan/unknown manifest inventory and original-ID dedup; authoritative venue settlement plus fully reconciled paper-wallet positions, partial exits, costs, fees and cash. Existing bounded/offline tests explicitly do not prove all-time Favorites P/L or training readiness.
- **Writer drain:** If maintenance becomes necessary, coordinate API `MT_API_RECOVERY_HOLD` and verify all API instances/in-flight requests and other writers stopped. Last confirmed API flag was FALSE. Never assert `--writers-stopped` from the two worker holds alone.

### Next safe action

1. Obtain actual Render physical disk-usage and WAL-headroom evidence through an already authorized operator interface. No network/credential/billing changes merely to inspect.
2. Optionally run `python -m services.demo.shadow_pg_storage_footprint --execute-readonly` **only** in an existing private Render Shell with `RECOVERY_DATABASE_URL` already configured; it does not certify physical space. See [logical footprint runbook](docs/audits/MT-019-readonly-pg-footprint.md).
3. Continue bounded, non-mutating SQL/R2 and settlement reconciliation only after appropriate source access exists. **Never** resume deletion, bulk archival, trading, collection or training solely from code/CI tests. Keep MT-019 IN PROGRESS.


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
