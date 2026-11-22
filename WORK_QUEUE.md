# Money Tree / Kalshi Shared Work Queue

This file is the coordination source of truth for ChatGPT/Codex implementation chats working on this repository.

**MANDATORY CHAT STARTUP BOOTSTRAP:** The user opens a new chat by sending **only its exact numeric ID** (e.g. `1.2`). **Before the assistant names itself or answers**, read this `main:WORK_QUEUE.md` and [`main:docs/CHAT_INDEX.md`](docs/CHAT_INDEX.md) from the connected GitHub repository. The bare `stream.round` string is the **entire intended ChatGPT title**: no descriptive topic and no `Money Tree — Chat` prefix. Treat `1.10` and `1.1` as different string IDs, not decimals. Detailed startup sequence is in `docs/CHAT_INDEX.md`; the Project's own instructions must tell every new chat to fetch these files.


## ACTIVE PROJECT-WIDE SCOPE — regular High-Probability Favorites ONLY (2026-11-21)

**User directive: ALL development, debugging, analysis, performance, storage, deployment, and operational work must be directly relevant to the REGULAR High-Probability Favorites strategy. This is the sole current project priority until the user explicitly changes it.**

- **IN SCOPE:** regular High-Probability Favorites trading behavior, opportunities and fills, its own data collection and research, observation-level outcome/uncertainty tables and dashboard, and fixes required to keep its paper trades, data, settlements, backups, and worker services operating safely and reliably. Shared infrastructure work is allowed **only when demonstrably needed** for regular Favorites or to prevent loss/corruption of its existing records.
- **OUT OF SCOPE:** **Statistics-Backed Favorites (even though it shares the Favorites name)**; Market Maker; Convexity; Sequential Spread; Complete Set; Volatility Scalper; and all other strategies, new strategy experiments, and unrelated features. Do not implement, optimize, analyze, revive, schedule, or resume these.
- **IMMEDIATE WORKFLOW RULE:** Before starting **or continuing** any task, including one already claimed `IN PROGRESS`, check that its next actions directly serve regular High-Probability Favorites. If not, safely checkpoint and mark the task `PAUSED — out of current Favorites scope` or leave a clear pause note for its owner; do not keep working merely because the task was already claimed or has a U0/U1 label. Exception: minimum essential action to prevent imminent data loss/security failure, with no expansion into other strategy work.
- **QUEUE RULE:** Only claim or advance tasks directly relevant to regular High-Probability Favorites. Other `READY` tasks are *not actionable* under the present scope, regardless of urgency. The scope directive overrides prior queue ordering and older handoff language; leave old task details and historical evidence intact.
- **SAFETY:** Keep all other strategies paused. Never enable Statistics-Backed Favorites, other bots, or LIVE real orders. Preserve existing histories, positions, financial ledgers, and verified backups.
- **COORDINATION:** Every parallel ChatGPT/Codex development chat should read this directive from `WORK_QUEUE.md` on `main` before acting, even when its application code lives on `build/google-auth-foundation`. Any work handoff, new issue, or PR must state how it serves **regular** High-Probability Favorites. This directive remains in effect until explicitly revoked by the user.


**NEW U1 — URGENT REGULAR FAVORITES THROUGHPUT:** [MT-030 — Investigate why regular Favorites traded so little November 21](#mt-030--investigate-low-regular-favorites-trade-throughput-on-november-21-2026). This is a high-priority, actionable READY task; do not divert into Statistics-Backed Favorites or another strategy.

### USER CLARIFICATION — event-based research, NO DAY-CLUSTER REQUIREMENT (2026-11-21)
- **Prediction-market research is evaluated per distinct verified Kalshi exchange event/outcome, not per calendar day.** The user explicitly does not want a requirement for 20 unique trading/event dates or calendar-day-cluster-adjusted inference before using event-level Favorites research. Do not use "only 4–7 dates" as an evidence blocker or next priority.
- Keep deduplicating repeated contracts, partial fills, multiple bids, price/time cohort appearances, and correlated threshold markets sharing the SAME underlying exchange event; preserve one event-level hypothetical held ROI observation with authoritative outcome and fee/cost basis. Entries without known outcome do not count; known-outcome historical exits are treated as held ONLY for derived research, without modifying original ledgers.
- Priority: actual event-level settled sample count, event-level win probability and calibration against market entry price, fee-aware hypothetical hold ROI, exact-only vs estimated-attribution sensitivity, nominal uncertainty/margin of error, and separate price/time research bucket evidence. Treat selection/multiple-comparisons and genuine overlapping underlying events carefully; do not add a date-diversity gate.
- MT-029's completed date parsing/cluster telemetry may remain as a historical **optional diagnostic**, not a mandate, trading setting, readiness check, or justification to stall other Favorites work. Historical MT-029 observations remain factual, but its recommendation to collect >=20 dates is **superseded by this user clarification**. No need to rewrite or delete source data, or modify the current running system based solely on this clarification.

### November 21, 2026 — Chat 02 orphaned-task and stale-PR audit (read only)
- **User-confirmed active chats: only Chats 01, 02, 03, 04.** At snapshot, 35 MT tasks: 27 DONE, 7 IN PROGRESS, 1 BLOCKED. No existing task ownership is changed by this review.
- **Needs owner reconciliation:** MT-019 (P0 Favorites history/backup and operator verification), MT-011 (U1 Favorites-only memory/resource efficiency), MT-030 (U1 broad Favorites throughput), all still attributed to unnamed prior ChatGPT workers. MT-030 may fit Chat 03 but must be explicitly claimed; MT-011 and MT-019 must not silently imply an active owner.
- **Do not reclaim active numbered work:** MT-018 and MT-034 = Chat 01; MT-035 = Chat 03; MT-033 = Chat 04; Chat 02 handles read-only deployment/health. PR #340 and #341 have merged, but task DONE still requires owner-led deployment/runtime acceptance; PR #342 remains draft.
- **Shared infrastructure correction (user clarification):** MT-017 Cloudflare Workers CPU audit is **IN SCOPE** because the common staging dashboard, authentication and gateway serve regular Favorites, even though paper execution runs on Render. MT-017 remains **BLOCKED** on actual Cloudflare CPU analytics/authorized access, not paused for scope reasons. Old PRs #247, #157, #124, #125 need owner review for supersession, not automatic merge. Older other-strategy PRs stay paused.
- **Full read-only audit:** [Unfinished tasks, owner reconciliation, legacy open PRs and issues](docs/audits/2026-11-21-money-tree-unfinished-task-audit.md). This snapshot is not an instruction to change ownership, run old scripts or drop records; obey the latest queue and explicit code claims.

## How implementation chats must use this file

### Chat naming and handoff rule — STREAM.ROUND (user directive, 2026-11-21)

**Mandatory read-before-work:** Every Money Tree chat must read `main:WORK_QUEUE.md` (this file, authoritative task claims and scope) and `main:docs/CHAT_INDEX.md` (stream/round register and handoff conventions) **before selecting its name, continuing a task, assigning an owner, or changing source code**. These files belong to repository `princesspikachuu/kalshi-scanner-data`. Do not rely on a previous conversation's memory or a stale copied queue; re-fetch current `main`.

**BARE-NUMBER TITLE RULE — USER CLARIFICATION (2026-11-22 UTC), OVERRIDES OLDER DESCRIPTIVE TITLE RULES:** The user's **first message will be only the exact stream.round ID** (`1.1`, `2.1`, `1.10`, etc.). This is sufficient and intentional. The **entire requested sidebar chat title is exactly that number**; topics are changeable and belong only in registry/task metadata. **Before identifying itself or producing its first substantive reply**, the assistant must use GitHub tools to read the latest `main:WORK_QUEUE.md` and `main:docs/CHAT_INDEX.md`, verify its predecessor and ownership, and then start its reply with **only the numeric ID on the first line**. Do not ask for a verbose first user message. The GitHub rules are not auto-injected into future chats, so this bootstrap must also be in the Money Tree Project instructions. The assistant cannot rename or inspect the actual ChatGPT sidebar title: if auto-generated incorrectly, only the user can correct it manually. Never claim a GitHub registration renamed the sidebar. See `docs/CHAT_INDEX.md` for the mandatory ordered startup steps.

**Identifier and sidebar title format:** Exactly `<stream>.<round>` (e.g., `2.1`), **with no topic or prefix**. The stream number identifies a long-lived work lane; the suffix identifies successive conversation rounds. GitHub documentation may mention lane topics for internal context, never as the requested ChatGPT sidebar title. The current four lanes are:

| Stream | Historical round-0 lane (topic is metadata only) | Round-1 successor ID |
| --- | --- | --- |
| **1** | **Chat 1.0 — Discovery Optimization**, owner of MT-018/MT-034 and PR #314 follow-up | **Chat 1.1** |
| **2** | **Chat 2.0 — Deployment Verification**, this ongoing deployment/health/coordination thread | **Chat 2.1** |
| **3** | **Chat 3.0 — Trading Throughput**, finance/regular Favorites follow-up (MT-035 claimed; confirm MT-030 ownership) | **Chat 3.1** |
| **4** | **Chat 4.0 — Profitability Validation**, forward-only regular Favorites (MT-033) | **Chat 4.1** |

**Historical naming snapshot:** Round-0 conversations were 1.0, 2.0, 3.0, 4.0; the live/current state and next unused numbers must always be read from `main:docs/CHAT_INDEX.md`. When a stream moves to a *new conversation*, increment only that stream's round: `1.0 → 1.1 → 1.2 → ... → 1.9 → 1.10 → 1.11 → 1.12`, similarly for 2, 3, 4. **These are two-part literal labels, not decimal numbers:** never parse them as floating-point, drop a trailing zero, or treat 1.10 as equal to 1.1. Do not advance a round merely because an existing conversation continues.

**Registry and ownership mechanics:**
- At the start of each **new successor conversation**, check the latest `main:docs/CHAT_INDEX.md` and this queue, reserve its unique `<stream>.<next-round>` there with a short descriptive topic, predecessor ID, and focus, and update the registry with the latest GitHub file SHA. If another chat already claimed it, refresh and use the next unclaimed suffix; do not create duplicate threads with one label. Do not create Chat 5.0 or other streams unless the user approves expanding beyond four.
- Every opening substantive reply starts with the exact numeric ID **alone on its first line** and every handoff preserves that ID; the requested sidebar title is that numeric ID only (the assistant cannot rename the chat in the app). Keep that exact ID for the life of the conversation. Existing old `Chat 01`, `02`, `03`, `04` historical labels refer to their respective **round-0** streams; preserve historical task records and translate these aliases to **1.0–4.0** when referencing owners.
- A chat-number or successor version is **not a task claim**. Continue only explicitly owned `IN PROGRESS` tasks or claim an eligible `READY` task using the latest queue SHA. Before an old chat retires, save a handoff in the queue with task state, current branch/PR/CI/deploy, blockers and next steps, and have the successor explicitly take over that task in the queue; no automatic ownership transfer.
- Chat labels are distinct from `MT-###` task IDs, GitHub PRs, issues, and Render service IDs. All development remains governed by the **regular High-Probability Favorites only** priority, including necessary shared Cloudflare/Render infrastructure, and the prohibition on activating other strategies or LIVE orders.


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
**First enforce the ACTIVE PROJECT-WIDE SCOPE directive above: only regular High-Probability Favorites work is eligible.** Among *eligible* tasks, sort by urgency (U0 → U4), then by dependency/readiness, then by the existing Priority text. Previously claimed unrelated work must be checkpointed and paused rather than finished under its old claim.

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
- **Current user intent (2026-11-21): REGULAR High-Probability Favorites is the ONLY strategy to work on, not merely the only active paper-trading strategy. Statistics-Backed Favorites is expressly EXCLUDED.** The top-of-file ACTIVE PROJECT-WIDE SCOPE directive governs all ongoing development chats. Latest verified runtime sample: 75 Favorites bots, zero running bots in other portfolios, real orders disabled. Do not resume any paused strategy or enable live orders. Preserve historical research, held-risk settlement and existing paper orders.

---


# PRIORITY 0 — URGENT DATABASE OUTAGE & RUNAWAY STORAGE

## MT-019 — Recover automatically suspended Render Postgres and stop uncontrolled paper-history growth
**Status:** IN PROGRESS — P0/U0, financial reconciliation complete; settlement/restart acceptance pending  
**Worker:** ChatGPT / storage-outage investigation  
**Claimed:** 2026-11-10 17:30 UTC  
**Priority:** Before MT-011 throughput verification or any resumed trading

**Full historical record, preserved byte-for-byte:** [MT-019 investigation and checkpoints](docs/audits/MT-019-work-queue-history-2026-11-12.md). This externalized 148,170 characters of previous MT-019 checkpoints and findings without deleting the investigation or touching trading data. For up-to-date state, follow this shorter active checkpoint, not older historical statuses.


### MT-023 read-only settlement observation for MT-019 owner (2026-11-21)
Regular-Favorites-only `favorites_trading_diagnostics` stayed at 22 expired lots / 7 markets under `expired_no_recorded_settlement` in consecutive 20:13–20:16 UTC snapshots, with 37 still-open lots and no unknown-market lots. These are lots, **not independent event counts**; no conclusion about authoritative venue finality. MT-019 owner should check actual finalized markets and audited settlement path, preserving cash, source and storage. MT-023 will not modify payout processing.

### MT-019 progress — 2026-11-21 regular Favorites safety, two backup PRs integrated

- **PR #321 merged `a91ea4f`, exact CI passed and Render worker deployed live** at 19:53:39 UTC. New worker recorded exclusive startup and readiness at 19:55:45 UTC; at 19:56:02 UTC, 75 regular High-Probability Favorites bots ran, **0 Statistics-Backed Favorites**, paper fills continued and real orders were disabled. The optional `MT_CONTROL_BACKUP_CHUNK_REUSE_ENABLED` remains **OFF**. Keep it off pending audit of actual R2 bucket lifecycle rules and restore tests for older shared chunks.
- **PR #325 merged `05f7508`** after exact-head API/PostgreSQL CI passed. Adds verified-backup-only `favorites_shadow_bot_sizes`: fixed, nonsensitive regular-Favorites vs all-other-bots counts/bytes/largest row, reconciling to `scope_sizes.shadow_bots`. No new SQL, any bot activity, source data deletion, manifest change or stored health change. Postmerge CI and Render verification were still pending at the checkpoint; do not treat merge as deployment.
- **Next measurement:** first successful backup after both #320 and #325 should expose `scope_sizes` and `favorites_shadow_bot_sizes`; reconcile total bytes, identify which source contributes growth, and design *lossless* cold-history segments with full verified reconstruction. Last verified 19:13:19 UTC Nov 21: 9,719 records, 300 chunks, 605,951,586 staged bytes; the 1 GiB staged budget is temporary. Preserve all history and never delete verified R2 roots/chunks.
- **Scope override:** only **regular** High-Probability Favorites and infrastructure directly protecting its paper research/ledger. Do not develop/resume Statistics-Backed Favorites or any other strategy; do not enable LIVE orders.

### MT-019 update — 2026-11-21: regular Favorites backup safety

**Only regular High-Probability Favorites is in active development scope; Statistics-Backed Favorites and every other strategy are excluded.** Backup/recovery work here is allowed only to protect or improve regular Favorites and its existing financial/research records; do not reactivate other strategies.

- PR [#321](https://github.com/princesspikachuu/kalshi-scanner-data/pull/321) **merged** into `build/google-auth-foundation` as `a91ea4f55426cb90b27c985dd145e0ae140977f6` after exact-head API/PostgreSQL CI success (run `44942598998`). It adds *optional* verified immutable R2 chunk reuse; **`MT_CONTROL_BACKUP_CHUNK_REUSE_ENABLED` remains default OFF**. The new retention regression proves that deleting an older shared part can invalidate a newer root, so no lifecycle expiration or R2 deletion is authorized.
- Post-merge validation runs `44942957468` (push) and `44942962401` (PR) were **in progress** at this checkpoint. Do not claim Render deployed merge commit until its checks-pass release is live and Favorites paper worker behavior verified.
- Last verified complete backup at 2026-11-21 19:13:19 UTC had 9,719 rows, 300 R2 parts, 605,951,586 staged bytes and 458,336,453 compressed bytes, with independent verified recovery catalog. No newer success containing `scope_sizes` observed yet. Follow the next verified backup's per-scope bytes/counts before choosing lossless cold-history storage targets. The 1 GiB staging cap is a temporary bridge.
- R2 lifecycle **must be checked against actual bucket settings** before enabling reuse. Cloudflare's default seven-day cleanup of unfinished multipart uploads is not object expiration; custom expiry rules affecting `demo/backups/` or the whole bucket would be unsafe. Do not delete verified roots/chunks, original Favorites observations, held positions, settlements, or financial ledgers.
- Latest read-only checkpoint telemetry: roughly 12.46 MB decoded, including 7.23 MB paused-scalper research and 3.69 MB exit evidence; this identifies unrelated hot-checkpoint overhead but **does not** establish R2 backup per-scope growth. Reduction requires lossless reconstruction and an independent restore test. Tracking: issue [#238](https://github.com/princesspikachuu/kalshi-scanner-data/issues/238).


### MT-019 complete bot catalog loading — 2026-11-16 UTC

Codex storage continuation retains ownership. Preventive catalog-completeness implementation: PR #237 merged as `2b5e5e0e1b47fbc104c15300cc78b896bcdd71c3`, reviewed head `5aa7a9e2f1b8861cf02fcb6ec09444fbcaa16418`. Hosted PostgreSQL CI `43969713474` passes all 1,809 tests, including a synthetic namespace above the old fixed limit. Startup, control refresh and workspace API now share a 4,096-control reader plus overflow sentinel. The SQL uses both range bounds AND exact starts_with matching, follows the namespace index, and preserves former UUID consumer order locally. Paused/retired controls are retained; source/overflow failures never become partial successes. Files: `services/paper_demo/shadow/bot_catalog.py`, DemoStore reader, worker/API integration, tests and `docs/audits/MT-019-complete-bot-catalog.md`. Do not infer a live catalog overflow from a range-only query: exact-prefix matching is required for every operational inspection. No operational counts, financial results, private archive references or rollout status are published here; consult the private evidence before continuing.

### MT-019 held paper payout processing — 2026-11-16 UTC

Codex storage continuation retains ownership. Implementation: PR #236 merged as `d6012598d1f81a73b209b4fc4ebaaf4fc02544fe`, reviewed head `68914268beb2b9c2ab6f99b3cfaae9335893da16`. Hosted PostgreSQL CI `43966469061` passes all 1,804 tests, including rollback, checkpoint conflict, advisory-fence exclusion, idempotence and final-report conflict cases. Files: `services/demo/held_paper_settlement.py`, its tests, shared payout-only method in `services/paper_demo/shadow/core.py`, and `docs/audits/MT-019-held-paper-settlements.md`. The library has no automatic startup registration. Merge is not evidence of operational execution, deployment or restart. Operational evidence belongs in the existing private archive; consult it before continuing. Keep private financial records, settlement status, storage measurements and archive references out of this public implementation checkpoint.

### MT-019 current-session financial reconciliation — 2026-11-16 UTC

Codex storage continuation retains MT-019 ownership. The requested read-only cash/fee/settlement reconciliation is COMPLETE for the captured current paper sessions. No financial state changed.

- A bounded keyset scan captured original financial events and controls from one repeatable-read, read-only PostgreSQL snapshot. Cash links were replayed independently from configured initial funding, including partial exits, fees, collateral netting and recorded settlements. Every captured wallet's cash, deposits and aggregate remaining market/side quantities matched. Recorded fill fee totals also matched independently retained active plus retired report totals; the root portfolio requires its retained final reports rather than pruned hot statistics.
- Every captured settlement marker agreed with authoritative finalized/settled venue outcomes. Pending closed-market payouts and remaining entry-fee realization passed a preview using independent copies of the existing wallet model. Those payouts have NOT been booked. Preserve the source checkpoint and use the existing serialized, audited settlement recovery path; do not manually reset cash.
- Original financial source rows, public venue originals, original checkpoint, replay results and the preview were saved to the existing private R2 archive as fully readback-verified multipart evidence. A separate root catalog and receipt were subsequently reread and verified. A fresh read-only SQL comparison confirmed the checkpoint remained unchanged. Private balances, market lists and archive references are deliberately excluded from this public queue.
- Reusable pure checker and regression tests: PR #235, head `e655fc839cbfb5a200f22d95f3975e4b94f875fa`, branch `feat/mt019-financial-reconciliation`; files `services/demo/shadow_cash_reconciliation.py`, its tests, and `docs/audits/MT-019-paper-cash-reconciliation.md`. Local suite passes 1,795 tests (299 PostgreSQL checks skipped locally). Hosted PostgreSQL CI run `43962769013` passed all 1,795 tests including the real PostgreSQL checks. PR #235 merged as `a55c1227e000ecd934f37aa8204ae9dcde0e41c9`. This is an offline additive verifier with no runtime startup integration; merge is not evidence that settlement processing or a restart occurred.
- Next: confirmed payout processing under an audited checkpoint fence; refreshed physical growth/WAL acceptance and staged restart preserving intentional strategy pauses. Disable held-backup-only mode before paper execution while retaining ordinary multipart backups; never restore the maintenance connection to the paper executor. Both held maintenance roles remain configured, collection/trading and API holds remain in place.
- Scope: recorded cash, fees, aggregate quantities and venue outcomes for captured current sessions. This does not certify exact historical lot-cost attribution, historical fee schedules, all-time cold history, strategy profitability, or restart readiness. No training acceptance or live trading is authorized.
- The deliberately altered example URL is not evidence of a real credential exposure. Do not repeat a rotation gate based solely on that example; establish concrete exposure evidence before reopening that issue.

### MT-019 separate archive worker and recurring held backups live — 2026-11-16 UTC

- Private maintenance connection was verified against the intended database and restricted non-owner role. Diagnostic archiving moved to the existing separate research worker, using the same exclusive advisory lease and bounded verified-retention path. Clean cycles and exactly one archive lease were observed after handoff. The unused maintenance connection was removed from the processing service; no new service, instance, plan or grant was added.
- PR #234 merged as `3c595b627c90a3453c12de218a3eee7e0d5c11ba`. Full PostgreSQL CI passes all 1,785 tests. New files: `services/demo/held_control_backup.py`, scheduling/lease/failure tests, and `docs/audits/MT-019-held-control-backups.md`; startup routing and recovery exclusion guards updated. It is default OFF, requires an explicitly disabled held collector and the existing non-owner runtime role, and starts no ordinary worker.
- Backup-only supervision is now live on the existing processing service, with both backup opt-ins true, both diagnostic-retention flags false, the recovery hold true and collection false. Two automatic checks recognized the current verified multipart snapshot and correctly avoided re-upload. A separate single backup lease was independently observed alongside the archive lease. Next daily backup is due when the existing verified snapshot reaches 24 hours; a complete scheduled backup at that future due time is not yet observed. Errors park for review, rather than unbounded retry.
- Read-only saved-wallet structural checks passed. A bounded GET-only venue preflight exhausted currently saved closed-market inventory and found matching finalized/settled yes/no outcomes. These checks neither settled positions nor reconciled all historical fills, partial exits, fees or cash. No balances, orders or positions were changed.
- MT-019 remains IN PROGRESS. Next: deterministic financial reconciliation and any reviewed settlement repair, evidence of earlier exposed credential rotation, refreshed physical growth/WAL acceptance and a staged restart preserving intentional strategy pauses. All trading/collection and API recovery holds remain in place. Before paper execution, disable backup-only mode while retaining ordinary multipart backups; never restore the maintenance credential to the paper executor.

### MT-019 continuation: archive placement and held backup cadence — 2026-11-16 UTC

Codex storage continuation retains the existing MT-019 claim. Owner completed the private connection setup. Current independent work: verify restricted authority, move the existing archive-only role under the shared lease, and implement an explicit default-OFF backup-only held worker so recurring control snapshots can run before paper trading resumes. Preserve all financial state, recovery holds and existing service capacity. No trading/collection restart is included.

### MT-019 next private configuration handoff — 2026-11-16 UTC

The proposed existing separate archive worker was checked without exposing credentials. Its private maintenance connection is absent from both saved configuration and the running environment. Owner must copy the existing restricted maintenance URL privately into that worker, saving without deployment; do not paste secrets into chat or GitHub. Keep the currently working archiver and all trading/collection holds intact. After private setup, validate scoped authority, deploy current code with holds, transfer the exclusive archive lease, then address recurring backup and financial/restart acceptance. No service transfer or strategy restart has occurred.

### MT-019 backup timeout fixed and restart preparation verified — 2026-11-16 UTC

- PR #233 merged as `32b01b1fa00b337c1310278e272f39e534e38b4b`, full PostgreSQL CI passes all 1,773 tests, and the held processing deployment is live. Control backup upper-tail probes now have a collation-verified enclosing upper bound, preserving hidden-key rejection without scanning unrelated history. Files: `services/demo/control_backup_v2.py`, backup tests, `docs/audits/MT-019-control-backup-bounded-probe.md`.
- A fresh multipart control snapshot completed with full R2 readback and durable backup-health/catalog verification. Automatic retention resumed after exclusive lease handoff on the replacement worker; trading and collection remain paused.
- Checkpoint transport/hash/schema and basic open-lot checks passed. A comparison against only hot per-market statistics is NOT full cash reconciliation: settled-market statistics are deliberately pruned by the host. Preserve the checkpoint and use historical financial evidence for reconciliation; do not reset balances to force an equality.
- Next: place archiving on an existing separate worker before restoring paper execution; verify recurring multipart backup cadence; complete historical financial/settlement acceptance and credential-rotation evidence; staged restart with physical growth monitoring and intentional strategy pauses preserved. MT-019 remains IN PROGRESS.

### MT-019 current restart preparation — 2026-11-16 UTC

- Active worker: Codex storage continuation, continuing the existing MT-019 assignment. Previous dated checkpoints below are historical and must not override this checkpoint.
- Backlog archival and full original readback verification are complete. PRs #230–#232 are merged; the independently scoped API archive reader is verified, and the existing held worker now runs bounded continuous diagnostic retention. Keep the working archive-only configuration intact while preparing restart.
- Trading and collection remain held. Current work: refresh verified multipart control backup, inspect checkpoint/account recovery without mutation, establish recurring backup cadence and a worker placement that preserves archiving alongside paper execution, then run restart acceptance. Preserve intentional strategy pauses.
- Remaining acceptance includes credential-rotation evidence, financial reconciliation and sustainable physical storage monitoring. Do not treat diagnostic archive completion as financial or whole-history reconciliation. No new billing or infrastructure expansion is authorized by this checkpoint.

### MT-019 storage reduction merged and deployed in recovery hold — 2026-11-13 PT
- User continued the reviewed rollout and explicitly selected Render **My Workspace**, `tea-dbfv1fl9el5s73bcuefg`; reuse this confirmed workspace ID for subsequent calls.
- [PR #227](https://github.com/princesspikachuu/kalshi-scanner-data/pull/227) squash merged as `be54b6f2bcb4bf0bcadf7a930c9f9e247679383b`. Exact PR CI 43543538523 and both merged-commit runs **43544829630 (push), 43544834865 (PR)** SUCCESS. Full PostgreSQL suite: all 1,726 tests passed. Bounded online diagnostic retention and optional four-slot status remain default OFF; unchanged checkpoint rewrites removed.
- **Correction to earlier API predeploy warning:** although its command says `python -m services.api.manage migrate`, historical deployed receipt (Nov 11 23:05:04 UTC) proves `RUNTIME_DB_PROFILE=api` selected read-only `staging-database-audit-v2`, not DDL. No migrations/manage/config changes exist between old API and this release. This chat explicitly set `RUNTIME_DB_PROFILE=api` and `MT_API_RECOVERY_HOLD=true`; environment update triggered reader-first deployment. API exact commit LIVE **2026-11-14 02:16:16 UTC**, deploy `dep-dbrs84dg1s2s73df52d0`. Its new predeploy read-only receipt confirms migrations match and isolated profile api. New startup complete 02:16:10; prior API instance exited 02:18:15. Health/ready independently HTTP 200. API recovery hold rejects non-health handlers, applies read-only pooled sessions and skips optional startup writes. **Dashboard/sign-in are intentionally unavailable during maintenance.** Trusted-proxy 503 was not independently observed (shell gateway request received Cloudflare 1010/403); do not claim exhaustive global writer-quiescence from deployment alone.
- Processing worker auto-deployed exact merge LIVE **02:16:22 UTC**, deploy `dep-dbrs87tbedkc73bh4bdg`; exact 02:16:05 startup receipt confirms collection=false/trading=false/collector/recovery-hold and deferred DB predeploy. Separate research service remains held on prior `585252f2`, manual deploy OFF. No manual duplicate processing deploy. Zero API/processing error-level logs returned for 02:14:35–02:31 UTC.
- Authenticated Render dashboard Info now displays **58.67% used of 15 GB**, autoscaling disabled, external SQL traffic still blocked. Metrics > Disk Usage showed **no data** for both 12h and 7d; the new summary is NOT established physical free space, WAL occupancy, or proof this chat reclaimed anything. No SQL/R2 rows were archived/deleted in this continuation.
- Remaining concrete operator requirements: last verified maintenance role is NOLOGIN (private isolated login/credential activation needed); prove current physical/WAL safety and all writer drain; verify R2 originals/receipts for each chosen batch. Existing stopped-writer recovery tools handle initial backlog. Online retention refuses recovery hold and must not be enabled by bypassing those checks. Status reader is deployed, but split writing stays OFF until a later accepted rollout/restart. Keep trading/collection and all automatic reclamation OFF. Runbook: `docs/audits/MT-019-sustainable-storage.md`.

### MT-019 API recovery hold live setting confirmed OFF (2026-11-13 PT)
- Operator inspected `pocket-api-staging` Render Environment: `MT_API_RECOVERY_HOLD=false`. GitHub implementation `docs/audits/MT-019-api-write-quiescence.md` confirms setting it true requires a successful API redeploy, API startup then uses read-only pooled sessions, rejects non-health paths with 503, and skips live-bot initialization; sign-in/dashboard temporarily unavailable. Existing API predeploy runs `python -m services.api.manage migrate` (potential DB-write migration), so **do not toggle/deploy casually** before coordinated maintenance window, disk/WAL safety and separate archive credential. Setting false means writer quiescence unproven; maintain recovery hold on both workers. No deletion or API flag changes made.

### MT-019 live connection snapshot: API still connected (2026-11-13 PT)
- Operator ran `pg_stat_activity` read-only grouping by username/state via restricted processing Render Shell: `('pocket_api_runtime', None, 1)` and `('pocket_research_runtime','active',1)`. The active research connection is likely the operator's own query; `None` for API state is insufficient privilege to see query state, **NOT proof API inactive**. `pocket_api_runtime` connection remains and API recovery hold/draindown NOT verified. API's predeploy on redeploy executes a migration; don't casually redeploy just to enable hold. Explicit coordinated hold and drain required before archive reclaim. No deletion occurred.

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
**Status:** DONE — PR #308 merged, staging frontend deployed and asset-verified  
**Worker:** ChatGPT / MT-006 paused-first dashboard ordering  
**Claimed:** 2026-11-21 18:24 UTC  
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
- **Implementation:** PR [#308](https://github.com/princesspikachuu/kalshi-scanner-data/pull/308) merged into `build/google-auth-foundation` as `3aa642a9f2e447aa768bfda11822561b3b67ed15` on 2026-11-21.
- **Files:** `apps/web/shadow-view.mjs` (sort active market-type subfolders ahead of paused-only types, and keep nonretired running markets first); `tests/test_strategy_folders.mjs` (three new regression cases). Existing top-level folder and Maker individual market sorting retained.
- **Verification:** PR head `be79ad43a6af8f287c95a1e62ff73440d3390b7d` passed GitHub Actions API/PostgreSQL + Node dashboard suite (`44935686622`); new tests cover pause/unpause, categories, retired markets, preserved expanded state, held settlement positions and Maker market pause controls. Separate staging frontend deployment (`44936050890`) succeeded and verified published assets match merge commit.
- **Safety:** No worker execution, live trading, storage, history, position accounting, or pause state logic changed. Mobile and desktop use the same responsive DOM ordering; authenticated viewport screenshots were not available for independent visual review.

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

### Chat 02 independent read-only RAM audit (2026-11-22 02:51 UTC)
- [Render memory audit report](docs/audits/chat-02-staging-memory-audit-2026-11-21.md), read-only and separate from MT-011 implementation. Historical processing-worker failures: **five explicitly OOM-killed server_failed events** on 2026-11-21 06:03–07:14 UTC (Nov 20 Pacific), including repeated failures on one instance. Highest five-minute sample 1.947 GiB / 2 GiB.
- Latest deployed regular-Favorites-only processing worker `618370c6` sample at 2026-11-22 02:50 UTC: **0.913 GiB / 2 GiB** (~45.7%), short post-startup plateau; `paper_monitoring_capacity` at 02:51 UTC reports **admitting=true, backlog=0, p95 lag ~16 ms, RSS ~47%**, with 75 regular Favorites bots active, all others paused, real orders disabled. API ~38% / 0.5 GiB; research ~16% / 0.5 GiB. No new OOM events in the observed post-deploy window. **Long-run memory-leak status unknown**; per-component memory breakdown not measured.
- **MT-011 owner retains exclusive memory optimization/profiling work.** Chat 02 did not edit runtime code, deployment, server capacity, retention, history, balances, or trading controls. Use this as an operational baseline; distinguish earlier OOM from current no-pressure state.

### New investigation lead (from MT-021 runtime verification, 2026-11-21)
- The per-second hosted health path in `services/paper_demo/shadow/host.py` still computes `strategy_books=sum(... for e,f,ps in self.experiments.portfolios.values() for t,m in e.markets.items() ...)` across **all** portfolio market dictionaries. Fully paused, unexposed portfolios still incur iteration over their retained market records even when they cannot add entry-ready books. This is a **code-level potential CPU waste**, not yet quantified by profiling.
- Assess a safe whole-portfolio fast path **only** when there are no enabled bots, held lots, or pending/resting orders. Preserve the held-risk and restart/resume semantics, and keep canonical market records, settlement, wallet, Favorites evidence and public fee readiness unchanged. Add deterministic tests and a diagnostic before claiming savings.
- Coordinate with open PR [#124](https://github.com/princesspikachuu/kalshi-scanner-data/pull/124), which also modifies `host.py`, and PR [#314](https://github.com/princesspikachuu/kalshi-scanner-data/pull/314), which owns discovery scheduling. MT-021 skipped 9 legacy fee checks, but does **not** solve the separate all-portfolio scan. This finding is for existing MT-011 owner; no new task claimed or source change made.
- **Measured follow-up (2026-11-21 19:26–19:30 UTC):** On the live worker, eight ~30-second monitoring cycles emitted **40 `volatility_scalper_health` log lines (18,104 JSON bytes)** and **16 `market_maker_health` log lines (6,584 JSON bytes)**. All seven emitting portfolios were paused, with 0 orders and 0 positions. The hosted `host.py` logging loop still calculates `monitored`, `fresh_books`, `reasons`, and optional `quote_diagnostics` on their retained historical markets; the 56 log lines alone consumed **24,688 JSON bytes** in the sampled ~4 minutes. An additional eight `favorites_statistics` diagnostics lines (~5.7 KB) were generated with the Statistics strategy paused. These counts establish needless reporting/scan work, **not measured CPU/RAM savings**. The `pipeline_sample` report also loops through all portfolios and serialized ~63.7 KB across eight samples; compare performance before altering that diagnostic. Prefer gating detailed idle diagnostics on actual enabled bots or outstanding exposure, with a bounded summary that still makes paused status visible. Keep canonical data, settlements and resuming safety unchanged; coordinate source edits with existing MT-011 owner and PR #124/#125 touching `host.py`.

- **Post-PR #319 API fallback (2026-11-21 19:29–19:31 UTC):** The API at deployed commit `ea0b22c7` logged `shadow_workspace_history_degraded` after a `financial_metrics` SQLSTATE 57014/5,003ms query cancellation, then kept returning `dashboard_transport` snapshots. Subsequent normal responses sampled ~3.0 MB decoded / ~508–511 KB gzip-base64 wire, ~866–1,155ms JSON serialization and ~1.18–1.51s total request time. The successful fallback eliminates the historical-scan-caused 503 in sampled traffic but leaves sizeable 10-second browser polling/serialization overhead; measure and optimize the remaining payload without dropping live Favorites observations. The timed-out legacy history scan still retries after a bounded 90-second cooldown. PR #319 owns the fallback implementation and deployed API; don't duplicate or revert it.

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
**Status:** IN PROGRESS — second read-only Cloudflare Analytics query HTTP 400 confirmed; PR #348 safer diagnostic merged, awaiting user manual rerun and verified provider access  
**Worker:** Money Tree — Chat 2.1: Deployment Verification (successor to 2.0; read-only Cloudflare observability)  
**Claimed:** 2026-11-09 19:20 UTC; user integration request 2026-11-21 Pacific
**Urgency:** U1 — URGENT  
**Priority:** High

### Scope clarification — user directive, November 21, 2026
- **This task is in scope and broadly relevant to Money Tree infrastructure**, because the shared Cloudflare gateway and authenticated dashboard present regular High-Probability Favorites trading/research data and errors can interrupt access to those functions. Render-based paper execution itself runs independently and must not be assumed to have crashed because the Cloudflare Worker exceeded CPU.
- Keep **BLOCKED**, *not* `PAUSED — out of scope`, until actual Cloudflare per-Worker CPU/exceededCpu telemetry or an authorized diagnostic path is available; do not infer CPU-limit resolution from successful asset deployment or the unauthenticated HTTP 403 root-page check.
- Previous generic ChatGPT worker is not assumed active; reserve task for deliberate assignment/handoff to one of active streams before code changes. Protect current Favorites-only scope, authentication, rate guards, source history and paper-only execution.

### Chat 2.0 active handoff — read-only integration setup (2026-11-21 Pacific)
### Live query failure and fix — 2026-11-22 UTC
- User supplied both required GitHub secrets (values masked) and manually ran read-only Cloudflare CPU workflow [#44979977136](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44979977136). **All seven offline tests passed; query step failed HTTP 400.** This was NOT a Render worker/API deployment failure, and no token values or raw Cloudflare responses were printed.
- Cloudflare's official newer GraphQL example declares datetime filter variables as `Time!`, whereas initial bridge used `string`. [Fix PR #345](https://github.com/princesspikachuu/kalshi-scanner-data/pull/345) corrects types and adds read-only minimal query fallback on HTTP 400. Detailed `exceeded_cpu` is explicitly `null` when unavailable, never incorrectly zero.
- PR #345 merged as `1da5fc7d54b171e643498523c3569bf7726ea831`; exact PR-head [offline CI #44980183173](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980183173) **SUCCESS**. Current audited branch `main` contains the fix. No Cloudflare/Render runtime changes, no LIVE/paper order modifications or history writes.
- **Next action:** user reruns [manual Cloudflare CPU workflow](https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/cloudflare-cpu-readonly.yml) on `main` for `last_24h`, then Chat 2.0 reads sanitized Actions summary. **Do not claim live CPU metrics fixed until an actual successful run**. Task intentionally remains open.

- **Setup implementation complete:** [PR #344](https://github.com/princesspikachuu/kalshi-scanner-data/pull/344) safely squash-merged as `85b205c2907c73a22b0689ae2e5259fa23360d61` to `main`. Exact-PR-head GitHub Actions [run 44979430401](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44979430401) passed **all seven** offline parsing/credential-exposure tests. The workflow file is on `main`, is manual-only, and has `contents:read`; no Cloudflare query, Worker deployment, trading setting, or history mutation was performed.
- **Next user-only prerequisite:** create Cloudflare Account Analytics Read token scoped to Money Tree's account, save it as GitHub **Repository secret** `CLOUDFLARE_OBSERVABILITY_TOKEN` alongside existing `CLOUDFLARE_ACCOUNT_ID`, and manually dispatch `cloudflare-cpu-readonly.yml` from `main`. Read-only metrics will be public aggregate numbers in this PUBLIC GitHub repository's Actions logs. Do not print tokens or raw logs.
- **Task remains BLOCKED on actual authorized metrics**. Once a manual run succeeds, Chat 2.0 should read its sanitized summary via GitHub, distinguish `exceededCpu` from HTTP 403 and Render CPU, and then document measured CPU causes. No access credential has been added by the assistant.

- User explicitly opted for programmatic read-only observability. A direct Cloudflare plugin is not currently available in ChatGPT. Prepare a narrowly scoped, manual-only GitHub Actions query bridge to Cloudflare Account Analytics Read GraphQL API (no Worker deployment/writes, database or R2 access).
- Store the analytics token only in a GitHub Actions secret, not in chat, code, action inputs, or printed logs. GitHub repository is PUBLIC and aggregate workflow logs will be publicly visible: print no raw Cloudflare traces, request paths, IPs, identities, secrets, or event bodies.
- Await the user's creation of the scoped Cloudflare token and GitHub secret before claiming live observations. The remaining blocker is credential onboarding, not a resolved CPU issue.
- **Draft [PR #344](https://github.com/princesspikachuu/kalshi-scanner-data/pull/344)** prepared on the manual-only GitHub Actions bridge branch. The workflow requires a new `CLOUDFLARE_OBSERVABILITY_TOKEN` repository secret (Account Analytics Read only); it will not query Cloudflare until the user sets up the token and manually runs the workflow from `main`. No public metrics collected or secret connected yet; validation of the new PR tests is pending.

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


### Second HTTP400 and safe staged diagnostic, Chat 2.0 (2026-11-22 UTC)
- Manual Cloudflare read-only audit [GitHub run #44980433098](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980433098) reported **all 11 offline tests passing**, then HTTP 400 from the Cloudflare GraphQL metrics request after three query variants; both configured GitHub secrets were present, values masked. **No Render/Worker deployment failed.** Exact provider error category remains unknown because raw errors intentionally are not printed in PUBLIC Actions logs.
- **Follow-up [PR #348](https://github.com/princesspikachuu/kalshi-scanner-data/pull/348)** (merged `80df3fc186569d24d7486de65f6b1e764d79ec76` to main; exact PR-head [17 offline tests passed](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980642663)). Adds a read-only, credential-redacting three-stage fallback diagnostic: Cloudflare viewer authorization, account visibility, Workers aggregate dataset, plus **account-ID secret shape** validation. The printed result `MT017_SAFE_PREFLIGHT` uses only fixed safe labels, not provider messages/IDs/IPs/paths/token data. Last query fallback now uses Cloudflare's documented nullable string variables.
- **Next:** user must manually rerun [MT-017 Cloudflare CPU (read-only)](https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/cloudflare-cpu-readonly.yml) on `main` with `last_24h` to obtain a sanitized preflight or aggregate CPU report. Do **not** request credentials in chat, bypass the public-log redaction, loosen permissions, or infer CPU fixed without a successful provider response. No other task ownership changes.

### Chat 2.1 ownership continuation (2026-11-22 UTC)
- Stream 2 successor **2.1** registered in `main:docs/CHAT_INDEX.md` (commit `ce859ebc`). Existing MT-017 read-only Cloudflare CPU analytics diagnostic ownership transferred from Chat 2.0 to Chat 2.1; task remains **IN PROGRESS**, with external provider metrics still blocked by HTTP 400. No application, trading, Cloudflare, or Render changes authorized by the transfer.
- Start by checking PR #350 postmerge checks and the latest Cloudflare read-only Actions audit status; next safe run is one manual `last_24h` audit on `main` if still required. Preserve redaction, secrets and historical records.

### Chat 2.0 Cloudflare GraphQL third-run triage and token verification (2026-11-22 UTC)
- **Actual failed run:** [GitHub Actions #44980816586](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980816586) had **17/17 passing offline tests** and reached Cloudflare; the audit returned **HTTP 400 (unclassified)**. Safe preflight reported `{"stage":"viewer","result":"failed"}` using the generic `viewer { __typename }` GraphQL probe. Account visibility/dataset/CPU data was **not queried successfully**; worker/API deployment has not failed. Both necessary GitHub secrets are present, but presence does **not** prove Cloudflare accepts the token.
- **Targeted source fix:** [PR #350](https://github.com/princesspikachuu/kalshi-scanner-data/pull/350) merged **`872720ae930ba37b0aa3d3534f894696c8889c80`**, with [exact PR-head CI #44981061519](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981061519) passing **22 privacy/contract unit tests**. It switches the viewer preflight to Cloudflare's **documented `viewer { budget }`** query, normalizes query to one line, recognizes documented parse/auth error classes, and, only if the analytics query fails, calls documented Cloudflare **GET token verify** (user and account token) to report *only* active/disabled/expired or sanitized HTTP status. No credentials, raw Cloudflare text, IDs, expiration times, IPs or request traces in public logs; no trading, Cloudflare Worker/DNS/R2 or Render configuration changes.
- **Next safe action:** confirm post-merge CI for PR #350, then one controlled manual audit run from `main` with `last_24h`; read `MT017_TOKEN_VERIFY` and `MT017_SAFE_PREFLIGHT` fixed-label outputs. If token is verified active but GraphQL viewer still returns HTTP 400, stop blind code/credential changes and diagnose Cloudflare GraphQL availability/permissions with provider evidence, using a private support channel if raw provider details are needed. MT-017 **remains blocked on live metric access** until actual Worker CPU/over-limit figures are received.


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
### Chat 1.1 — PR #347 safe merge and release gates (2026-11-22 UTC)
- **MERGED** [PR #347](https://github.com/princesspikachuu/kalshi-scanner-data/pull/347) into `build/google-auth-foundation` at exact merge `2a699a2135a59e28d6d76a2b158140ea4909cab2` (03:36:55 UTC). The reviewed branch combined head `b08a0d0e045a4d45020bcf7a62d970c83ebef33e` was mergeable, 0 behind the development base, with only intended `hourly.py` + `test_favorite_scan.py` edits. Postmerge GitHub compare against previous base `bb23bd72657525b7fb3b7d29aa1bd7d8e962c104` likewise confirms **only those two files** changed.
- **CI gates PASSED BEFORE MERGE:** original head full API/PostgreSQL [#44980497045](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980497045) passed **2,211 Python tests**, explicitly including both new finance-hourly stage and malformed-first-row regressions. Combined exact-head full API/PostgreSQL [#44981085899](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981085899) **PASSED**. No historical, wallet, paper quote/order, safety/fee or other-strategy code changed.
- **POSTMERGE** push [#44981445934](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981445934) and pull-request [#44981449118](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981449118) full API/PostgreSQL jobs are **in progress at checkpoint**. **Render exact release not independently verified by Chat 1.1**: its connector requires a user-confirmed workspace. Do not claim deployment until Chat 2.0/3.1 or an authorized Render check verifies exact live SHA, singleton lock, 75 regular Favorites only, no other enabled strategies, real orders disabled and new bounded `paper_hourly_scan.by_category` count basis.
- **MT-018 REMAINS IN PROGRESS.** Monday Nov 23 funded weekday FX/Treasury/index sessions must still establish distinct provider-listed active events → fresh book/fee-qualified maker quote → actual paper BUY fill → official settled outcome, or record exact absent/gated reasons. No diagnosis of original weekday no-fill simply from passing these tests.


### Chat 1.1 — PR #347 exact combined-head checkpoint (2026-11-22 UTC)
- [Draft PR #347](https://github.com/princesspikachuu/kalshi-scanner-data/pull/347) passed original exact-head full API/PostgreSQL [workflow #44980497045](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980497045) at `e94ea04a5aa7c01c39282ff409f72f72d7c9c140`. Since Chat 3.1's disjoint PR #346 merged, the scanner owner reconciled the PR branch via a two-parent commit `b08a0d0e045a4d45020bcf7a62d970c83ebef33e` onto new development base `bb23bd72657525b7fb3b7d29aa1bd7d8e962c104` (former PR head second parent). Fresh GitHub compare reports **ahead 3, behind 0** and ONLY `services/paper_demo/shadow/hourly.py` and `services/api/tests/test_favorite_scan.py` differing. This preserves Chat 3.1 telemetry changes untouched.
- New exact combined-head full API/PostgreSQL [workflow #44981085899](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981085899) **in progress** at checkpoint. **Do not mark ready, merge or deploy until latest exact-head validation passes.** This PR does not yet prove any weekday finance-hourly BUY fills/settlement or Kalshi API filter semantics.
- The [official GET /markets](https://docs.kalshi.com/api-reference/market/get-markets) status + close-time filter compatibility table conflicts with a published [Aug 28, 2026 live query observation](https://github.com/jlucasmcrell/oracle-trader/blob/main/docs/kalshi-shortterm-data.md#31-get-markets--listfilter-markets) which successfully returned open listings with close-time filtering. Do not change `status=open` based solely on docs; bounded verified weekday comparison required. [Issue #339 updated](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339#issuecomment-7073607027).


### Chat 1.1 — Kalshi Get Markets filter contract discrepancy (read-only; 2026-11-22 UTC)
- Official [Kalshi Get Markets docs](https://docs.kalshi.com/api-reference/market/get-markets) list `min_close_ts/max_close_ts` as compatible with `status=closed` **or omitted status**; `status=open` is explicitly listed with created-time filters. Our hosted hourly/weather discovery currently combine `status=open` with close-time bounds. `ProductionData.call` passes query fields unchanged.
- **UNVERIFIED compatibility concern, not proven weekday finance no-fill cause.** The Saturday worker had successful hourly scans, so do not assume a systemic HTTP 400. A future authorized, bounded weekday provider comparison of the combined query versus documented close-time-only query should establish response status, applied filters, pagination and distinct active events before changing code. No extra live probe, fee/risk bypass or unrestricted REST burst is authorized in this note.
- Recorded for MT-018 and MT-035 coordination in [issue #339 comment](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339#issuecomment-7073534883). PR #347 does not modify query compatibility.

### Chat 1.1 — MT-018 draft PR #347 stage-visibility checkpoint (2026-11-22 UTC)
- [Draft PR #347](https://github.com/princesspikachuu/kalshi-scanner-data/pull/347) on branch `feat/mt018-hourly-listing-stage-visibility-20261121`, head `e94ea04a5aa7c01c39282ff409f72f72d7c9c140`, based cleanly on deployed `c980217225fa0f14bfd04de6a4b98e08d062ae5b` with **only** `hourly.py` and `test_favorite_scan.py` changed (2 commits, zero behind-base commits at branch creation). **DRAFT / CI NOT YET VERIFIED / NOT DEPLOYED.**
- The currently live hourly scanner's "No active markets closing within one hour" message conflates no returned market pages with records that have the wrong status, future opens, or out-of-window closes. Draft adds bounded **per-page** category counts and compact per-series `hourly_coverage.reason` stage summaries, reused by Chat 3.1's read-only MT-035 monitor. These counts are provider page appearances, **not distinct events or observed tradeable opportunities**.
- A malformed single market `open_time` or `close_time` can currently throw from `runner.ts` during the hourly list comprehension, skipping later valid records. Draft safely rejects only that malformed record without authorizing any extra entry, and adds both pure and integrated finance-hourly regressions. No venue reads, quote/risk/fee/hold-to-settlement policy, wallet, live-order, history, R2 or other-strategy activity changes. Preserve 15m throughput.
- **Current release lineage verification:** #343 postmerge full API/PostgreSQL workflow [44978692073](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978692073) **PASSED**; GitHub ancestry confirms #343 merge `9158a089` is an ancestor of #342 merge `c9802172`. Chat 3.1's [verified Render log report](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339#issuecomment-7073424429) records `c9802172` deployed at 03:11:23 UTC with singleton worker ready 03:13:29 UTC. Thus the #343 page-continuation fix is in that observed runtime build, although **no weekday finance-hourly BUY fill or settlement yet**.
- Coordination: PR #346 belongs to Chat 3.1 and changes its separate MT-035 telemetry without touching `hourly.py`. PR #347 stays draft until exact-head focused and full hosted API/PostgreSQL CI pass and latest base is reconciled; Monday Nov 23 funded weekday venue evidence still required for [issue #339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339).


**Status:** IN PROGRESS — transferred from Chat 1.0 to successor Chat 1.1; weekday finance runtime acceptance pending  
**Worker:** Money Tree — Chat 1.1: Discovery Optimization (successor to Chat 1.0 / legacy Chat 01)  
**Claimed:** 2026-11-10 00:20 UTC; handoff confirmed 2026-11-22 UTC following user correction  
**Urgency:** U2 — HIGH  
**Priority:** High, after MT-003

### Chat 1.1 successor ownership — 2026-11-22 UTC
- New conversation **Money Tree — Chat 1.1: Discovery Optimization** registered at `main:docs/CHAT_INDEX.md`, follows Chat 1.0. MT-018 is transferred to Chat 1.1; scanner listing/pagination (`hourly.py`, `weather.py`) remains exclusive to this lane. Chat 3 owns MT-035 non-scanner finance entry diagnostics and MT-030 quote/cash audit; Chat 2 owns runtime deployment verification.
- PR #314, #335, #341, #343 are merged. PR #343 exact-head full API/PostgreSQL and focused Favorites tests passed; its **postmerge and exact Render deployment/runtime effect still require verification**. Finance-hourly **weekday** actual BUY fills and authoritative settled outcomes remain unverified (issue #339); do not mark MT-018 DONE solely based on CI.
- Only regular High Probability Favorites is in scope. Do not activate other strategies or LIVE orders; preserve all event history and paper ledgers.

### Ownership clarification — 2026-11-22 UTC, Money Tree Chat 01
The user confirmed they have **no ChatGPT chat named MT-018** and do not know if its old generic worker is active. An `IN PROGRESS` queue entry is not evidence of a live chat session. Related PR #335 was merged and issue #333 closed; no current unmerged MT-018 scanner implementation PR was found on GitHub at handoff. **Chat 01 now owns the remaining MT-018 regular Favorites discovery work**, particularly hourly/weekday finance and the paginated premature-sleep risk. Other chats must avoid overlapping scanner edits and coordinate through [issue #339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339) / this queue. Chat 03 owns separate quote/fill/cash audit. The small distinct MT-034 wake-helper draft PR #341 remains under Chat 01 and will be verified/closed before new scanner code changes. Preserve original event histories, paper wallets, settlement and fee protections; Statistics-Backed Favorites/other strategies remain paused and no real orders enabled.

### Chat 01 — MT-018 incomplete-page wake fix merged [PR #343](https://github.com/princesspikachuu/kalshi-scanner-data/pull/343) (2026-11-22 UTC)
- Isolated branch `fix/mt018-incomplete-page-wake-guard-20261121`, latest head `33294420f2685c8f5204e953dc4be42c6fc4d3e9`, safely reconciled onto merged MT-034 #341 base `447ff4dd6129e4dd39e2a13511b699b349ee3805`; compare has only three intended files and no behind-base commits.
- **Source-level reproducible bug:** `hourly.py` and `weather.py` could install a long future entry wake on **an incomplete** venue `/markets` listing and reset its continuation cursor, skipping a currently eligible event on the next page. They now permit long future sleep **only on complete single-page listings** (incoming and outgoing cursors both empty), continue incomplete pages under existing bounded rate/cadence, and label incomplete listing in per-series diagnostics. It also keeps original `min_close_ts/max_close_ts` query bounds unchanged across cursor pages (small, restart-local dictionaries reset on page completion or a new known cash/day session), preserving proper page continuity.
- Two synthetic **independent-event** second-page admission regressions added to `services/api/tests/test_favorite_scan.py`, including the configured finance-hourly `KXUSDCADAH` series and hourly weather. They assert no long sleep, cursor preserved, identical API query bounds on page 2, cursor snapshot cleanup after complete pagination, and a downstream paper-market enqueue after passing existing entry/fee checks. No live missed finance event/fill is *yet* established; Issue #339's weekday finance funnel remains open, not solved by this alone.
- Exact-head hosted full API/PostgreSQL [run 44978340966](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978340966) and focused Favorites [run 44978340972](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978340972) **both PASSED**. PR #343 **merged** to development as exact SHA `9158a0899f457d20606401df7699d88bf3f4f79d`; postmerge full [run 44978692073](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978692073) is **running**. Render release and additional real independent fills **not verified**; do not treat weekday finance-hourly as solved. Do not alter paused strategies, real exchange trading, R2, historical evidence, cash, risk/fees or settlement.

### PR #314 pagination/future-wake safety note for MT-018 owner (Chat 01, 2026-11-22 UTC)
Source-only concern, **not proven live**: both `hourly.py` (lines 101–132) and `weather.py` (lines 87–103) can receive an incomplete `/markets` response with a nonempty continuation cursor, find only a **future** venue entry time on that first page, set a long persisted wake, and reset their page cursor to `''`. An eligible distinct event on a later page could then be missed. The sports scanner protects incomplete pagination separately. Two-page deterministic regression and an owner's bounded safe fix requested in [#278](https://github.com/princesspikachuu/kalshi-scanner-data/issues/278) and [#339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339). **MT-018 retains scanner ownership**. Do not duplicate edits, weaken fees, freshness, settlement or memory/read budgets, or infer actual weekday no-fills solely from this hypothetical risk.


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

### MT-023 read-only coverage evidence (2026-11-21, for MT-018 owner)
Existing authenticated API `favorites_timed_rollup` snapshots around 20:09–20:12 UTC report **finance-hourly 0/11 bots with entry-timing rows**, weather-hourly 4/8, crypto-hourly 7/9, commodities-hourly 4/5, sports 4/7, and finance-15m 10/11. Overall 53/75 regular Favorites bots have timing rows. These are **bot-level record coverage**, not distinct settled event counts or availability evidence. Investigate no-trade hourly-finance gating/opportunity availability with your existing MT-018 owner scope; do not suppress healthy 15m collection. MT-023's draft PR #326 will measure independently settled event coverage without changing trading.

### High-priority 15m discovery dependency audit (2026-11-22 ~01:21Z; MT-026 investigator, for MT-018 owner)
**Likely P1 regression:** Current worker has 75 enabled regular Favorites bots, zero other enabled bots, worker RSS ~1.03GB (49% of 2GiB), backlog 0 and capacity admitting. The newest hour has **0 known verified 15m outcomes** (4 weather only). Source inspection suggests `ForwardRun.discover_once` loops only legacy `self.profiles` (host.py ~147-155, runner.py ~165-175) and `legacy_discovery_required` (runner.py ~131-141) gates **only** the disabled legacy Convexity bot. There is no separate hosted Favorites 15m discovery coroutine (host.py ~789-800). Regular Favorites appears unable to receive newly listed 15m contracts when the old strategy is paused. Verify with reproducible hosted tests; fix 15m discovery for enabled regular Favorites without activating Convexity. Preserve fee, fresh-book, venue open_time, business hours, rollover, admission rate/RSS protections, existing orders/positions, and paper-only trading. Track isolated reproduction and safety acceptance in [Issue #333](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333); supporting source audit in issue [#278 comment](https://github.com/princesspikachuu/kalshi-scanner-data/issues/278#issuecomment-7072191318). **MT-018 retains exclusive scanner ownership**; MT-026 only modifies quote-telemetry grouping.

### Issue #333 focused discovery fix in progress (regular Favorites, 2026-11-21 PST)
- [Draft PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335), branch `fix/mt018-333-regular-favorites-15m-discovery-20261121`, head `892af087e54e18abc54704dd3e06a66aa5dbb770`. Focused `runner.py` discovery admission + dedicated integration regression file, preserving MT-018 owner and all other scanners.
- A disabled legacy Convexity bot no longer blocks listing **when the matching regular Favorites 15m collector is enabled**. Includes measured admission guard and expired risk-free legacy rollover while retaining any exposed legacy position's settlement. No legacy orders enabled, no fee verification or venue schedule bypass.
- Exact-head full API/PostgreSQL CI [run #44973586349](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44973586349) was still running at checkpoint. **Do not merge or claim deployed** until it passes. Confirm post-merge CI, exact Render SHA, singleton worker, fresh 15m monitoring/verified events or documented venue unavailability, 75 regular Favorites bots and all other bots paused.

### Issue #333 15-minute Favorites-only discovery safety checkpoint (2026-11-22 UTC)
- Draft [PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335) current head **`e0dc966dd050dfb843b6357079c60f2c1586f8e5`**, based on concurrent MT-030-integrated development SHA `ce0765c902c4b37a6a8d3c9404210a317551b2c4`; isolated `runner.py`, `host.py`, 12 dedicated scanner/routing tests. Initial draft CI had test fixture KeyErrors due missing legacy `version` metadata; corrected in latest commit. Full exact-head CI [44974546927](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974546927) in progress, Favorites focused green. **NOT MERGED/DEPLOYED.**
- Crucial safety: newly listed Favorites-only 15m markets are routed to the existing regular Favorites paper ExperimentSuite only, **never to the inactive legacy Convexity engine/checkpoint**. Legacy `self.selected` retains its unconfirmed contracts until authoritative settlement; dedicated Favorites-held positions retain existing REST settlement polling; direct active 15m subscription persists through worker restart. Live verified fee metadata startup warmup and ongoing refresh include active, subscribed Favorites-only 15m markets without waking paused flat strategies. Measured queue/memory/rate guard, published open_time/weekend-DST wake and one-contract maker entry unaffected. Other scanners and wallets untouched.
- Owner MT-018, subtask [Issue #333](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333). Do not claim fixed until exact-head API/PostgreSQL passes, safe merge and exact Render singleton worker verifications confirm fresh eligible 15m subscriptions or explain venue unavailability. Keep all other bots paused and real trading disabled.

### Issue #333 PR #335 merged — final deployment check outstanding (2026-11-22 UTC)
- Scope remains regular Favorites only; **PR [#335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335) merged** as exact `618370c663b3ead89389e8453a83fee16ba21bf3` after focused Favorites [44974770666](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974770666) and full API/PostgreSQL [44974770656](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974770656) passed on its exact head. The separate concurrent MT-031 base changes are preserved.
- New 15m market admission checks enabled regular Favorites even with legacy Convexity paused. Favorites-only market never inflates/activates inactive legacy wallet; legacy pending settlement still retained. Favorite 15m book subscription, fee warmup and verification survive restarts; capacity, exchange status/open_time, schedules/DST, risk/fee/one-contract paper controls remain unchanged. Dedicated tests cover all, including empty-worker startup.
- **Still pending** two post-merge full CI runs [44975123669](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975123669) and [44975129411](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975129411), exact Render deployment and exclusive active Favorites worker, and live active 15m subscriptions or source-backed absence. Do not close Issue #333 or mark this subtask DONE until those pass. No real exchange orders enabled. See [Issue #333](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333).

### Issue #333 automatic deployment reached Render — active worker confirmation still pending
- Exact merge commit `618370c663b3ead89389e8453a83fee16ba21bf3` **passed both post-merge full integration tests**: push [44975123669](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975123669) and PR [44975129411](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975129411).
- Render `pocket-processing-staging` auto-deploy `dep-dc152bflk1mc7383ilig` verified **live** on exact SHA at 2026-11-22 **02:20:09 UTC**; replacement instance `655b7` logged `demo_lock_wait`. Subsequent log requests hit **Render 429**. **No proven new singleton worker start, 15m active book, or outcome yet**. Do not close Issue #333 or mark all MT-018 done until fresh Render logs verify the handoff, regular Favorites only, paper-only, fee + settlement health, real 15m eligible discovery, or exchange-backed lack of availability. Full checkpoint in [Issue #333](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333#issuecomment-7072851761).
- Preserve existing active worker, outstanding bids and settlement backlog; no forced restart/other strategy toggles/real-money orders.

### Completion notes
_Fill in when done._

---

### Live post-fix runtime verification — Saturday Nov 21, 18:22 PST (2026-11-22 02:22 UTC)
- **PR #335 merged** 02:14:03 UTC and the processing worker deployed exact commit `618370c663b3ead89389e8453a83fee16ba21bf3` at **02:20:09 UTC**. This is later than the user's preceding-hour dashboard observation; that preceding hour was not a valid test of the fix.
- **After deployment, 02:20:09–02:22:02 UTC:** regular Favorites 75 bots running; monitoring `admitting=true`, 0 backlog, RSS ~58%, 12 subscribed markets and **zero hourly-price or legacy-free 15m (reported complete_set=0) candidates**. `paper_strategy_health` reports weather-markets 21, hourly-markets 0. Only one new weather maker order and buy fill observed; no 15m order/market admission in current audit sample, no metadata retries. **Do not mark #333 as operationally restored based only on CI and deployment.** Check provider inventory and 15m `discover_once` skip/wake/market filter reasons and implement measured fix under MT-018 ownership.
- Sat evening absence of cash-session finance/commodity opportunities and nightly Daily Weather windows cannot explain missing around-the-clock 15m crypto. Preserve fee, freshness, RSS, settlement safeguards; do not enable paused legacy/Stats Favorites.

### Verified 15m execution on the new worker — 02:20–02:29 UTC, Nov 22
- Follow-up to the earlier 02:22 UTC zero-15m startup slice: **the merged issue #333 fix is effective**. Live worker exact SHA `618370c663b3ead89389e8453a83fee16ba21bf3`; independent regular Favorites 15m maker buys resumed at 02:22 UTC. Between 02:20:10–02:28:30 UTC the Render audit has 49 `ORDER_SUBMITTED`, 21 BUY `FILL` records but only **9 distinct exchange events**: 7 independently filled **15m crypto** events (19 fill records: BNB/DOGE/SOL/XRP/ETH/ZEC/NEAR) plus 2 hourly weather events (2 fills). BTC/HYPE also had maker entry submissions but not confirmed fills in that sample.
- 75 regular Favorites enabled; all other strategies paused, `real_orders_enabled=false`. Around 02:28:59Z, Favorites had 22 active and fresh order books, ample cash and no worker-error logs. This supersedes the earlier no-15m two-minute snapshot. **Future authoritative venue settlement of one post-fix 15m event remains outstanding** under issue #333/MT-030. See [Issue #333 follow-up](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333#issuecomment-7072938694). Do not reopen previously fixed discovery based on stale telemetry; no additional scanner code modification in this triage.

### Issue #333 resolved and closed — new 15m event settlements, 02:31 UTC Nov 22
- PR #335 delivered its intended independent regular Favorites 15m discovery on live Render SHA `618370c663b3ead89389e8453a83fee16ba21bf3`; first post-release 15m buy fills and maker submissions verified. **At 02:30:17 UTC authoritative venue settlement confirmations** arrived for five previously filled 15m events (ETH/NEAR/SOL/XRP/ZEC). At 02:30:31 UTC, `favorites_collection_quality['15m_price'].unique_verified_1h` rose from 0 to **5 distinct settled outcomes**. This fulfills issue #333's final venue-confirmed event acceptance; **[Issue #333 closed as completed](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333#issuecomment-7072953287)**. Remaining MT-018 category-balancing work still in progress (hourly-price listings, other categories), do not mark entire task complete or activate paused strategies.


## MT-020 — Stop paused-strategy discovery and repeated reporting waste
**Status:** DONE — deployed and verified on the processing worker  
**Worker:** ChatGPT / paused-strategy resource optimization  
**Claimed:** 2026-11-21 18:42 UTC  
**Urgency:** U2 — HIGH  
**Priority:** User-requested resource reduction; independent of MT-011 and MT-019 recovery

### Goal
Reduce avoidable paper-worker CPU, memory and database growth from paused, unexposed strategies, without deleting historical evidence, pausing active High Probability Favorites, changing live-trading boundaries or compromising settlement and protective exits.

### Scope / safety
- Avoid creating newly discovered markets in paused, unexposed portfolios; keep existing markets and risks until normal settlement/pruning.
- Re-enabled bots immediately join relevant currently active shared/legacy markets.
- Cache unchanged, paused-only derived research views without mutating canonical research/financial data.
- Instrument skipped work and validate resumed trading and held-position settlement behavior.
- Do not change ongoing MT-011 checkpoint implementation or MT-019 archive/backup worker.

### Completion notes
- **Implementation:** PR [#313](https://github.com/princesspikachuu/kalshi-scanner-data/pull/313), head `31cf0a1901431bd218be62f07c70bc52d5fa6239`, merged on 2026-11-21 as `5bfc69d36ff6a5816fce2c5f07cefc693f765a59` into `build/google-auth-foundation`.
- **Files:** `services/paper_demo/shadow/experiments.py` and new `services/api/tests/test_paused_market_discovery.py` (eight regression tests). Paused/unexposed portfolios skip new shared, legacy, Maker, and external discovery market allocation; held lots/working orders remain eligible. Resume backfills known active markets, with books invalid until a fresh snapshot. Reuse derived Favorites timing rows for idle paused portfolios (30-second maximum) without changing canonical observations/wallet/checkpoint.
- **Validation:** Exact PR head full API/PostgreSQL and Node validations passed, GitHub run `44937640567`; merge commit API/PostgreSQL validations `44938105762` and `44938101739` both passed. Existing fee restrictions, position/settlement operations and unrelated strategy behavior remain tested.
- **Deployment:** Render `pocket-processing-staging`, service `srv-dbhcqr0473hc739kj4pg`, deployed merge commit `5bfc69d3` at 2026-11-21 19:00:11 UTC. New instance `9kd8n` acquired exclusive paper lock and emitted `demo_worker_ready` at 19:02:17 UTC. No runtime crash observed in sampled events or post-handoff logs.
- **Measured live first cycle:** `paper_monitoring_capacity` at 19:02:43 UTC reported `paused_new_market_copies_skipped=13`, `paused_new_market_discoveries_skipped=0`, `backlog=0` and 11 subscriptions (9 protected, 2 new-entry). `shadow_pipeline_cost` counted 12 idle clock passes skipped. `paper_strategy_health` retained 75 enabled Favorites bots, zero enabled Scalper/Maker/Statistics bots. Four one-contract Favorites paper entries followed the handoff; real orders remain disabled.
- **Limits:** Existing paused-strategy research/checkpoint history and database/archive storage retained intentionally, so do not claim immediate RAM/CPU savings beyond these observed skipped-work counts. No backup/archive/R2, MT-019 or MT-011 logic changed; outstanding backup capacity investigation belongs to existing MT-019 owner.

---

## MT-021 — Avoid dormant legacy fee-readiness and monitoring work
**Status:** DONE — merged, deployed and runtime-verified  
**Worker:** ChatGPT / inactive legacy fee scope  
**Claimed:** 2026-11-21 19:09 UTC  
**Urgency:** U2 — HIGH  
**Priority:** User-requested follow-up after MT-020; High Probability Favorites remains the only enabled strategy

### Scope
- In the hosted paper-worker control/health pass, limit per-second legacy book and fee readiness calculations to selected legacy markets genuinely needed for enabled bots, existing positions or outstanding orders; leave Favorites fee verifications and subscription logic untouched.
- Preserve settlement polling and accounting even when a legacy portfolio is paused; preserve the disabled-scope behavior for standalone/simulation mode.
- Verify idle, resumed, held-position and resting-order cases with deterministic tests; measure and log the number of skipped legacy fee-readiness calculations.
- Coordinate separate legacy discovery REST scheduling with PR #314 owner; do not alter that scheduler during its active work. Keep MT-019 backup/storage and P0 PR #317 startup work untouched.

### Completion notes
- **Merged implementation:** PR [#318](https://github.com/princesspikachuu/kalshi-scanner-data/pull/318), merged into `build/google-auth-foundation` as `6d8c4057f4b9faac71ce735d665cab492b0e5d04` (2026-11-21 19:17 UTC). Hosted dormant legacy market fee/book-readiness checks are skipped while held-risk/resumed/standalone checks remain protected. Added `legacy_fee_checks_skipped` counter.
- **Validation:** Five new regression tests plus idle-fast-path assertion and focused Favorites validation passed; full exact PR-head API/PostgreSQL suite passed. Both post-merge GitHub workflow runs [44940097891](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44940097891) and [44940102515](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44940102515) completed successfully.
- **Deployment:** Render `pocket-processing-staging` automatically deployed commit `6d8c4057` at **2026-11-21 19:23:24 UTC** (deploy `dep-dc0uuuvlk1mc73fte3g0`). Replacement instance `jjdwh` initially waited for old instance `cv227` to relinquish its exclusive lock; then emitted `demo_worker_ready` at **19:25:30 UTC** with real orders disabled.
- **Measured runtime at 19:25:57 UTC:** New-instance `shadow_feed_health` logged `selected_markets=9`, `verified_fees=0`, `legacy_fee_checks_skipped=9`, `running_bots=0`, `resting_orders=0`, `pending_orders=0`, `open_contracts=0` for the legacy account. This skipped nine previously repeated local fee readiness calculations per health pass, **not nine external Kalshi HTTP calls**.
- **Favorites preserved:** Same monitoring sample had **75 enabled Favorites bots**, zero enabled bots in all other portfolios, `real_orders_enabled=false`, and `backlog=0`. New instance logged additional one-contract Favorites paper entries and paper-audit commits after readiness. No error-level logs in the sampled post-start window; previously sampled maker-entry fees were `0`. No original observations, historical positions/orders, balances or settlements were deleted or rewritten.
- **Limits:** Skipped local checks do not establish a measured CPU/RAM decrease. PR #314 continues to own separate discovery scheduling; MT-011 and MT-019 remain separately owned.

---

## MT-022 — Audit regular Favorites event-level held-profit attribution and statistical integrity
**Status:** DONE — merged, API deployed, worker ready and verified
**Worker:** ChatGPT / regular Favorites P&L evidence audit
**Claimed:** 2026-11-21 19:36 UTC
**Urgency:** U2 — HIGH
**Priority:** Direct user request; regular High-Probability Favorites only

### Goal
Independently trace regular Favorites observations from maker fills through authoritative settlement to price/time buckets and combined event-level held-to-settlement P/L. Validate fee treatment, independent event identity, repeated fills, missing outcomes, denominator selection, and uncertainty units/assumptions. Correct verified defects with isolated regression tests, without modifying the source observations, paper orders, balances, settlement or unrelated strategies.

### Coordination and boundaries
- Active [PR #322](https://github.com/princesspikachuu/kalshi-scanner-data/pull/322) already owns the regular Favorites small-sample uncertainty **display threshold**, `favorite_single.py`, `apps/web/shadow-view.mjs` and their tests. Do not edit those files or duplicate its numerical/UI changes in this task; audit underlying P/L attribution and source evidence separately.
- MT-018 owns collection balance; MT-019 owns recovery/backup; MT-011 owns general efficiency. No overlaps or strategy reactivation.
- Only regular `favorites` portfolio. Do not change Statistics-Backed Favorites strategy/metrics, other bots, live trading, fee safety gates, historical data or past settlements.
- Branch new code from `build/google-auth-foundation` (never `main`); write queue claim to `main`; use draft PR until tests and evidence confirm safety.

### Completion notes
- **User policy clarification (2026-11-21):** For regular High-Probability Favorites research, any historic early exit **with a confirmed outcome must be evaluated counterfactually as held through settlement**, using original entry quantity, cost, and entry fees. Ignore actual exit proceeds/exit fees in research; preserve actual ledger. Unknown outcomes must not count as profitability or uncertainty observations.
- **Implemented and merged PR [#323](https://github.com/princesspikachuu/kalshi-scanner-data/pull/323), merge commit `04769fa18f5cefa3c58ff7421a4548f1e1aa28eb`:** Branch `audit/mt022-regular-favorites-profit-evidence-20261121` from `build/google-auth-foundation`. A read-only derived per-event held evidence view feeds regular Favorites Detailed, Wider, Single and research detail responses, with exact fills preferred, estimated historic sizing visibly flagged, no known-outcome exits discarded, no unknown-outcome P/L invented, and no source data/positions/accounting changes. Dedicated regression tests cover known winning/losing exits, multiple entry fills, fee-inclusive basis, conservative event labels, original ledger preservation, malformed/missing outcomes and all three table views.
- **Coordination:** PR #322 previously merged the initial small-sample uncertainty safeguard; PR #324 subsequently raised numerical uncertainty's minimum to 50 event returns and labeled evidence tiers. Neither changes MT-022's event-level payout/fee accounting; Statistics-Backed Favorites untouched.
- **Validation:** Exact PR-head GitHub Actions run [44942882184](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44942882184) passed 2,080 API/PostgreSQL tests, authenticated gateway/browser checks, focused compatibility tests and infrastructure validation. Earlier three synthetic fixture failures were corrected without relaxing production event evidence rules.
- **Post-merge CI:** Merge commit `04769fa1` workflows [44943331912](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44943331912) and [44943336516](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44943336516) both completed **successfully**.
- **Deployment verified:** `pocket-processing-staging` deploy `dep-dc0vf6fb9u1s73foic3g` Live on merged commit `04769fa1` at 2026-11-21 19:57:59 UTC; replacement `c9l6c` emitted `demo_worker_ready` at 20:00:00 UTC after the exclusive paper-trading lock handoff. `pocket-api-staging` final deploy `dep-dc0vf7tlfk9s73cgsde0` Live at 19:58:49 UTC on `05f7508d`, a descendant containing MT-022 plus later independently merged regular Favorites uncertainty and storage telemetry. API logged successful `dashboard_transport` responses, no error-level logs in post-release sample.
- **Safety/operations:** New worker health at 20:00:16 and 20:00:47 UTC reported **75 running regular Favorites bots**, **zero** running unrelated bots, `real_orders_enabled=false`. Favorites monitoring reported 9 active markets; capacity backlog dropped from 25 to 0 in sampled cycles. No new Favorites paper-entry log was observed in the short initial post-handoff sample, so do not infer an observed new fill from this release check. Original settlement records, positions, early-exit financial ledger, balances and archive data remain unchanged by the read-only display transformation.

---

## MT-023 — Audit regular Favorites research completeness, bucket reconciliation and evidence progress
**Status:** DONE — derived live evidence audited; limits and next steps recorded
**Worker:** ChatGPT / MT-023 regular Favorites evidence audit
**Claimed:** 2026-11-21
**Urgency:** U2 — HIGH
**Priority:** User-approved next step after MT-022

### Goal
Independently validate *actual* regular High-Probability Favorites observation coverage and consistency: Detailed vs Wider vs Single, distinct event identities (not contracts or overlapping correlated cohorts), known hold-to-settlement historical exits, incomplete/estimated/unsettled outcomes, and 50-event uncertainty eligibility. Produce grounded coverage and profitability findings by market type/price/time with measured gaps, source and time window. Do not infer profitability or confidence from partial or correlated observations.

### Coordination and safety
- Only the regular `favorites` portfolio; exclude `favorites_statistics` and other portfolios. Real exchange orders must remain disabled and every other bot group paused.
- Coordinate with existing MT-018 (collection balance), MT-019 (history/backup), MT-011 (systems performance); avoid editing their claimed source and never change bot configuration for this audit.
- Use read-only, bounded queries with explicit market/portfolio provenance; avoid expensive full JSONB scans of mutable hot history or anything that risks the paper worker or database.
- Keep historical observations, financial ledger, positions, settlement evidence, backups and original fee data immutable.
- If the audit finds a concrete reporting defect, isolate the fix with tests and a separate PR off `build/google-auth-foundation`; don't edit the uncertainty threshold owned by PR #324 or duplicate MT-022 calculations.
- Record observed counts and limitations without publishing private financial data or raw user account/contract identifiers in this shared queue.

### Completion notes
- **Source access:** Hosted Render PostgreSQL explicitly disallows external MCP SQL when its IP allowlist is empty. Do **not** change networking or external access for this audit. API/worker logs from the authenticated service confirm rollup data; private source records remain untouched.
- **Current baseline (API `favorites_timed_rollup`, 2026-11-21 ~20:09–20:12 UTC):** 75 regular Favorites bots, 53 with timing rows. By category: crypto-15m 9/9, commodities-15m 8/8, finance-15m 10/11, crypto-hourly 7/9, commodities-hourly 4/5, **finance-hourly 0/11**, weather-hourly 4/8, weather-daily 7/7, sports 4/7. These are **bots with cohort records**, not independent settled observations, win rates or profit. Timed rollup reports no unclassified purchased quantity, but that does not validate event-level completeness. MT-018 owns follow-up on sparse hourly finance/other collection.
- **Settlement gap, read-only (worker `favorites_trading_diagnostics`, 2026-11-21 20:13–20:16 UTC):** Regular Favorites kept 75 bots active, 0 other bots, real orders off. At least six consecutive samples reported **22 expired lots across 7 markets with no recorded settlement**, alongside 37 still-open lots and no unknown-market lots. **Do not equate lots to 22 independent observations or assume the venue had finalized each market.** MT-019 already owns held settlement acceptance, venue confirmation, and risk-ledger reconciliation; don't book payouts or alter history in MT-023.
- **Evidence telemetry merged in [PR #326](https://github.com/princesspikachuu/kalshi-scanner-data/pull/326), commit `0d3250d3d985a8e025ebdd14b6b50631e088879f`:** Adds a bounded read-only `research_evidence` field to the existing once-per-minute `favorites_timed_rollup` log, reusing the same current snapshot's Detailed/Wider/Single calculations. It reports per-category unique verified settled events and hold-return counts; exact vs estimated/incomplete attribution; 50-event remaining count and numerical nominal P/L CI when available; cohort-vs-independent distinctions; unplaced Wider records; most-sampled price/time buckets; and legacy cohort counters without event IDs. No raw tickers, events, account values, extra SQL, schema or trading changes. Four regression tests included.
- **Validation/deployment:** Exact PR-head CI [44945368629](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44945368629) passed **2,094 API/PostgreSQL tests** and all four new regressions; both post-merge CI runs [44945883057](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44945883057) and [44945888461](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44945888461) passed. Final staging API commit `fd402eeb489acecc2c10430a1ac9d31f7ea4ca7e` (descendant containing MT-023) deployed **Live 2026-11-22 01:21:27 UTC**. New-instance `favorites_timed_rollup` with `research_evidence` appeared **2026-11-22 01:21:39 UTC**, API dashboard responses completed and no sampled error-level API logs; worker showed 75 regular Favorites bots, zero unrelated, real orders disabled.
- **Actual distinct settled event evidence, 2026-11-22 01:21:39 UTC (category/ROI/nominal 90% P/L bounds, percentage units):** crypto-15m **2,410 / -3.24% / [-5.17,-1.32]**; commodities-15m **1,022 / -0.47% / [-3.14,+2.20]**; finance-15m **710 / -3.20% / [-6.39,-0.01]**; crypto-hourly **219 / +1.72% / [-2.40,+5.84]**; weather-hourly **185 / -0.48% / [-4.78,+3.82]**; sports **47 / +6.04% / no interval (<50)**; commodities-hourly **24 / -16.39% / no interval (<50)**; weather-daily **19 / +4.58% / no interval (<50)**; finance-hourly **0 / no data**. These are deduplicated **within categories**, not necessarily independent across categories or time; nominal t intervals don't correct correlated event returns or sample-selection biases. No observed category supports a **statistically defensible positive edge** on this evidence alone. Negative crypto-15m and finance-15m intervals were wholly below zero, with finance upper end only -0.01%; *not* guaranteed future losses.
- **Evidence fidelity:** Across categories, 4,636 settled events have a derived held return; **3,574 (77.1%) are flagged estimated**, 1,062 exact. The original event-level entries were never mutated. Source telemetry had **73 non-outcome entry cohort rows** (not 73 missing independent market events), **7,906 Detailed event appearances** from repeated cohorts vs 4,636 category-distinct events, and **617 Wider legacy time-cohort exclusions**, not necessarily 617 unique events. All source consistency `flags` were empty and `incomplete_settled_events=0` in the derived snapshot. Neither condition proves the raw source is exhaustive.
- **Most populated potential cohorts (exploratory only):** Commodities-15m 70¢/10–15m **349 appearances, +5.87% mean held ROI** and 75¢/10–15m **182, +9.20%**; finance-15m 75¢/10–15m **90, +5.07%** and 70¢/5–10m **95, +4.08%**; crypto-hourly 90¢/15–30m **44, +8.81%**. Price/time cohorts may overlap in underlying events and no 90% P/L interval for these individual cells was calculated; do **not** equate positive observed mean with validated profitability or auto-change trading eligibility.
- **Priorities:** (1) **Exact-only sensitivity**: compare realized hypothetical held ROI/intervals for 1,062 exact event-return observations vs estimated 3,574; this is essential before trusting nominal 90% intervals. (2) MT-018: finance-hourly 0/11 timing records/0 settled events; commodities-hourly needs 26, weather-daily 31, sports 3 to reach 50 *category* settled observations. (3) MT-019: reconcile expired lots without recorded settlement against actual venue finality before booking any payout. (4) Validate actual overlap/correlation and selection bias before any market-type or bucket trading policy change. No changes to original financial records or active bots.

---

## MT-024 — Measure regular Favorites maker-bid resting lifetime and cancellation outcomes
**Status:** DONE — merged, post-merge CI passed, exact Render release and live diagnostic verified  
**Worker:** ChatGPT / regular Favorites quote lifecycle  
**Claimed:** 2026-11-21 UTC  
**Urgency:** U2 — HIGH  
**Priority:** Follow-up to issue #278 after uncapped discovery PR #314

### Goal
Determine whether regular High Probability Favorites one-contract maker bids rest long enough to fill, and distinguish orders submitted, fee/post-only rejected, canceled before any fill, canceled after partial fills, expired, still resting, and filled. Count unique ticker and event identities separately from bids/contracts; do not equate bids, fills or contracts with independent settled outcomes.

### Exclusive scope and safety
- Implement **bounded, read-only, in-memory** per-order lifecycle telemetry and a periodic compact log for the **regular `favorites` portfolio only**. No order, fee, expiry, cash, quote, cancel, price, exposure, data-retention, SQL/R2, or real-money changes.
- Do not instrument or enable `favorites_statistics` or other bots. Any generic observer must be inert by default and cannot change simulation or audit events.
- MT-018 owns weather/hourly/sports discovery and opportunity-category balancing; MT-019 owns backup; MT-011 owns general worker efficiency; MT-022/023 own settled-bucket attribution and research coverage. This task must not edit their claimed discovery/reporting code.
- Track order IDs, filled-once versus fill events, terminal outcomes, resting age and right-censored still-open orders. Preserve event identity, handle partial fills, cancellation latency and restarts; use bounded state with explicit telemetry coverage labels.
- Development base `build/google-auth-foundation`; PR draft until focused and complete CI pass; verify exact Render deploy and worker health if merged.

### Completion notes
- **Implementation:** [PR #328](https://github.com/princesspikachuu/kalshi-scanner-data/pull/328), branch `feat/mt024-favorites-quote-lifecycle-20261121`, merged into `build/google-auth-foundation` as **`fd402eeb489acecc2c10430a1ac9d31f7ea4ca7e`**. Four isolated files: new `services/paper_demo/shadow/favorite_quote_lifecycle.py`; optional inert-by-default observer in `core.py`; regular-`favorites`-only hook and 30-second log in `host.py`; new `test_favorites_quote_lifecycle.py`. No strategy orders, prices, cash, fees, exposure, settlement, checkpoint, SQL/R2, real-money or other-portfolio modifications.
- **Measured diagnostics:** 5-minute rolling ephemeral bounded tracking: max 2,048 in-memory open order references and 4,096 event tuples; unique known exchange events vs quotes; first partial fill vs repeated fill events; completed/cancelled/expired/rejected and still-resting right-censored bids; median/p90 live/resting/cancel acknowledgment ages; explicit restored, missing exchange event ID and dropped/observer error counters. A missing exchange event identity is never invented from a ticker.
- **Testing:** Exact PR head `708a8ae46619d5a00867ff884d811a6cd40213d0` passed Favorites CI run `44945966041` and full API/PostgreSQL run `44945966100`; prior revision also passed. Post-merge exact SHA CI runs `44946457083` (push) and `44946461456` (PR) both passed. Concurrent MT-023 coverage and backup maintenance changes were preserved, no conflicting file overlap.
- **Render:** `pocket-processing-staging` automatic deploy `dep-dc0vvlk8mias73cq5ncg` verified **live** at **2026-11-21 20:33:35 UTC** on exact merge SHA `fd402eeb...`. Replacement worker instance `x4kqm` recorded exclusive `shadow_worker_start_recorded` and `demo_worker_ready` at **20:34:51 UTC**, following `demo_lock_wait`. Prior worker continued until fenced handoff; no duplicate paper worker execution observed. At 20:35:31Z new instance reported **75 regular Favorites bots, 10 fresh books, two orders, zero Statistics-Backed bots, real_orders_enabled=false**, live worker RSS 320,835,584B (14.9% of 2GiB), backlog=0, admitting=true. Settlement polling preserved (four REST polls of six held markets, venue_not_final).
- **New event observed:** `favorites_quote_lifecycle` emitted first at 20:35:01Z, then a populated 20:35:31Z sample with **2 bids submitted on 2 distinct events, both resting, 29.69s median rest age, 0 fills, 0 observer errors**. Neither bid is a failed trade or an independent settled observation yet. Restart-scope counters need accumulated time and repeat quote/fill samples before judging fill rates. No 24-hour memory stability or strategy edge inferred.
- **Next owner action:** Use enough settled-event windows to compare actual maker resting times and terminal causes; MT-018 independently owns market discovery/category balancing, MT-011 owns resource growth, MT-019 backup safety, MT-023 research coverage.

---

## MT-025 — Warn when regular Favorites recovery backup coverage is overdue
**Status:** DONE — merged, validated, deployed and runtime-verified  
**Worker:** ChatGPT / regular Favorites backup freshness  
**Claimed:** 2026-11-21 UTC  
**Urgency:** U1 — URGENT  
**Priority:** Supports sole active regular High-Probability Favorites strategy; P0 MT-019 recovery safeguard

### Goal
Detect a missing, unverified or older-than-configured **recorded verified R2 backup receipt** on the existing five-minute maintenance cadence, even when an R2 connection or other maintenance stage fails. Emit only bounded, secret-free freshness measurements and an idempotent in-app alert; do not treat the recorded receipt as proof that today's R2 object remains present. Preserve the existing backup schedule and every original financial/trading/research record.

### Coordination and safety
- This is strictly regular High-Probability Favorites data-protection infrastructure under MT-019 / issue #238. Do not optimize, reactivate or modify Statistics-Backed Favorites or another strategy.
- Limit changes to freshness evaluation and maintenance hook with deterministic tests. Keep the full backup snapshot, R2 chunk reuse feature flag OFF, retention rules, active worker's lock, paper fills and real trading settings unchanged.
- On existing verified receipt within the configured backup interval, clear **only** the freshness warning; never suppress real backup failures or archival alerts.
- Use no credentials, market keys, contracts, bot identities, raw records or exception text in public alert/log output.
- Do not deploy until full API/PostgreSQL CI passes and no active branch conflict; verify Render live service and 75 regular Favorites / zero Statistics-Backed bots if merged.

### Completion notes
- **Merged:** [PR #327](https://github.com/princesspikachuu/kalshi-scanner-data/pull/327), squash commit `b303b38ffca70835b14897dedee5ba8eb146611e` in `build/google-auth-foundation` after exact PR-head full API/PostgreSQL test suite [44945912184](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44945912184) passed. Two old tests assuming only one maintenance event/alert were corrected to preserve the original backup failure assertions alongside the independent freshness warning. Both post-merge checks [44946387575](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44946387575) (push) and [44946392147](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44946392147) (PR) passed.
- **Files:** `services/demo/maintenance.py`, `services/api/tests/test_maintenance_failure_details.py`, `services/api/tests/test_backup_diagnostics.py`. The existing five-minute maintenance loop now reports age of last *recorded verified* backup receipt and raises/clears only the separate `backup-freshness` alert when missing/unverified/older than configured hours. No current R2 check is implied; `r2_rechecked=false` is explicit in logs. Exception text, object keys and record values are not emitted.
- **Deployment:** Render staging worker deployed exact `b303b38` at **2026-11-21 20:32:49 UTC**, then newer descendant `fd402eeb` (includes this commit) went LIVE at **20:33:35 UTC**. Replacement worker recorded `demo_worker_ready` at **20:34:51 UTC** after exclusive lock handoff.
- **Runtime acceptance:** `demo_backup_freshness` at **2026-11-21 20:35:52 UTC**: `state=fresh`, `recorded_verified=true`, `age_minutes=85`, `backup_interval_hours=24`, `r2_rechecked=false`. This is a fresh *recorded receipt*, not a newly uploaded or independently re-restored archive. At 20:36:02 UTC, **75** regular Favorites bots and **0** Statistics-Backed Favorites bots were running; real orders disabled. No `demo_backup_freshness_unavailable` or `demo_backup_verification_failed` in the sampled post-start window.
- **Follow-up owned by MT-019:** Await next successful complete verified backup with `scope_sizes` and `favorites_shadow_bot_sizes` for measured, lossless cold-history storage planning. Keep `MT_CONTROL_BACKUP_CHUNK_REUSE_ENABLED=false` until actual R2 lifecycle + retained-root restore audit; no new backup schedule, deleted history, or new strategy activity.

---

## MT-026 — Attribute regular Favorites maker-bid churn to market type and resting duration
**Status:** DONE — PR #329 merged, integration CI passed, exact Render worker release and categorized live telemetry verified
**Worker:** ChatGPT / Favorites paper quote-churn breakdown
**Claimed:** 2026-11-21 (local US Pacific)
**Urgency:** U2 — HIGH
**Priority:** Explain cancels vs fills after MT-024 without unsafe quote changes

### Scope
- Strictly regular High-Probability Favorites paper bids. MT-018 owns discovery balancing, MT-023 independent settlement/uncertainty, MT-011 worker resources, MT-019 backups; preserve all related concurrent code.
- Extend **existing bounded in-memory MT-024 telemetry only**, classifying each maker order by existing market metadata into 15m price, hourly price, hourly weather, daily weather, sports or unknown. Show per-type submitted bids, known distinct events, first-filled orders, canceled unfilled (resting-time bins), expiries/rejections, open right-censored orders and fill/cancel resting-time medians. Missing venue event IDs/market type must remain explicitly unknown; per-type unique events across rolling windows are NOT additive independent settled outcomes.
- No actual order/cancel/price/size, exposure, fees, cash, risk, settlement, worker scheduling, REST traffic, persistent storage, dashboard or real-money changes. Keep memory bounded and omit raw contract/order IDs from logs.
- Add isolated tests for metadata mapping, multiple bids in the same event, partial fills, censorship, rollovers, resets, unknown source, and historical counter compatibility. PR against `build/google-auth-foundation` only after exact-head tests. Automatic Render release only after successful CI and singleton/health verification.

### Evidence
- PR #328 runtime, 20:36Z to 01:21Z: 56 approximately nonoverlapping five-minute snapshots showed ~877 submissions, ~200 first-filled orders and ~646 unfilled cancellations (different order cohorts; snapshot offsets drift, not a causal fill rate). Some filled orders were repeated on the same exchange event. At 01:21Z, worker one instance at ~1.03 GB RAM (48.7% of 2 GiB), backlog 0, admission healthy; 75 regular bots, all other strategies disabled, last-hour authoritative verified event outcomes only 4 (weather). MT-018 should investigate absent fresh 15m/hourly confirmations; this task only categorizes the maker lifecycle, not discovery.
- Unknown-time historical observations are excluded from inferred recent settlement counts. No financial edge or cancellation cause asserted from rolling telemetry.

### Completion notes
- **Code and merge:** [PR #329](https://github.com/princesspikachuu/kalshi-scanner-data/pull/329), branch `feat/mt026-favorites-quote-churn-categories-20261121`, exact PR head `3f27917b73fda2f0ef07b142f7c2918f2118cb2a` merged to `build/google-auth-foundation` as **`08970db415671a9cc82856bdff0f8d75f63c51c9`**. Only modified `favorite_quote_lifecycle.py` and its dedicated tests. Added six bounded market-type buckets, separate submissions/fills/cancels/expiries/right-censored resting orders, known venue event dedup, unknown labels and five cancel-age bands. No trading, discovery, fee, risk, settlement, persistent record, other-portfolio or real-order changes.
- **CI:** exact-head full API/PostgreSQL [44971297089](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971297089) passed. Both exact merge-SHA CI runs [44971654910](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971654910) and [44971658389](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971658389) passed.
- **Render:** worker `pocket-processing-staging` auto-deploy `dep-dc14cv7b9u1s73fthev0` verified **live** at 2026-11-22 01:34:31Z on exact merge SHA. New instance `mdhp7` waited on singleton lock and recorded `shadow_worker_start_recorded` and `demo_worker_ready` at **01:36:33Z** after old `x4kqm` last observed 01:36:32Z. No duplicate paper execution observed.
- **Live verification 01:37:11Z:** 75 regular Favorites bots enabled, all other strategies including Statistics-Backed Favorites 0, 11 fresh books, 4 paper orders, `real_orders_enabled=false`. RSS 380,850,176 bytes (17.73% / 2 GiB), backlog 0, p95 lag 0.01089s, admission healthy. Seven held markets continue authoritative settlement polling, four polls returning `venue_not_final`. New populated `favorites_quote_lifecycle.by_market_type.weather` = five submitted bids on three known exchange events, one canceled without fill after 13.347 seconds correctly in 5–30s bin, four still resting and **zero** diagnostic errors. This is bid-lifecycle telemetry, not confirmed settled observations or profitable-edge proof. Full release verification logged in [PR #329 comment](https://github.com/princesspikachuu/kalshi-scanner-data/pull/329#issuecomment-7072325028).
- **Separate higher-priority discovery investigation:** suspected legacy Convexity bot gate starving active regular Favorites 15m scanner is tracked by MT-018 in [Issue #333](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333). Not fixed here. Do not reactivate other bots; test and repair hosted Favorites-only 15m discovery under its existing owner.

## MT-027 — Compare exact vs estimated held-return profitability in regular Favorites
**Status:** DONE — merged, full CI passed, staging API live and actual attribution splits verified
**Worker:** ChatGPT / regular Favorites attribution sensitivity
**Claimed:** 2026-11-22 01:23 UTC
**Urgency:** U2 — HIGH
**Priority:** Follow up on MT-023's finding that 77.1% of derived held-event returns are flagged estimated

### Scope and acceptance
- Regular High-Probability Favorites ONLY; no Statistics-Backed Favorites, Market Maker, new trading rules, balances, actual payouts, data deletion or source rewrites.
- For each existing category, compare **exact-only** and **estimated-only** event-level cost-weighted held-return subsets after consistent event deduplication. An event with any estimated cohort must remain estimated; an incomplete event must be excluded from both.
- Derive sample counts, mean hypothetical hold ROI and the current nominal 90% Student-t interval **only** where at least 50 events and both gains/losses exist; otherwise explicitly Pending/Unavailable. Clarify that neither subset is randomly sampled and that estimates/market correlations can bias even exact-only results.
- Reuse regular Favorites derived snapshot in existing once-per-minute `favorites_timed_rollup` research evidence telemetry. No additional database/R2 reads or expanded main dashboard payload. Include no raw event/market IDs, financial balances or order identities.
- Add focused source immutability, pooled-event/correlation, incomplete, mixed-attribution, fifty-event boundary, and scope regression tests. Validate with exact-head API/PostgreSQL CI; deploy only after checks and verify live log. Coordinate away from MT-018 discovery, MT-019 backup, MT-026 quote lifecycle.
### Completion notes
- **DONE — verified against live staging API, 2026-11-22 01:41:41 UTC.** [PR #330](https://github.com/princesspikachuu/kalshi-scanner-data/pull/330) merged at \`5d3504ce9d8f8d328ac3c7dac7d1d7fe555ae5fb\`. Exact-head API/PostgreSQL CI [44971441808](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971441808) passed 2,125 tests; both merged-commit runs [44971725044](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971725044) and [44971728276](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971728276) succeeded. Latest staging API deployment \`dep-dc14g43l550s73dcq7j0\` became LIVE on descendant \`4582aedcdb8fc4f9596306e12d1df587e571268d\` 01:41:33 UTC. Authenticated \`favorites_timed_rollup.research_evidence.categories[*].attribution_sensitivity\` at 01:41:41 UTC contained 9 category splits, **all counts reconciled, flags []**, no error-level API logs in sampled new-instance window. Processing worker at 01:41 UTC had 75 regular Favorites bots, 0 Statistics-Backed Favorites bots, real orders disabled. No source-history, risk, order, fee, wallet, R2, or trading changes.
- **Live exact-only vs estimated-only event-mean hypothetical held ROI %, with nominal 90% t intervals where available:** crypto-15m exact n495 **-2.50% [-6.76,+1.76]** vs estimated n1915 **-3.44% [-5.60,-1.28]**; finance-15m exact n193 **-2.84% [-8.98,+3.30]** vs estimated n517 **-3.34% [-7.08,+0.41]**; commodities-15m exact n120 **-2.29% [-9.66,+5.08]** vs estimated n902 **-0.23% [-3.09,+2.63]**; crypto-hourly exact n115 **+0.11% [-6.14,+6.36]** vs estimated n104 **+3.50% [-1.84,+8.83]**; weather-hourly exact n87 **+0.45% [-5.96,+6.86]** vs estimated n99 **-1.77% [-7.64,+4.10]**. Sports (22 exact, 25 estimated), weather-daily (11/8), commodities-hourly (20/4), finance-hourly (0/0) remain below separate 50-event thresholds and show no numerical uncertainty. All categories exact-only with qualifying intervals overlap zero; importantly, the full crypto-15m and finance-15m groups had nominal intervals below zero, but their exact-only subsets do not. Do not infer an automatically tradable positive edge.
- **Interpretation:** These are nonrandom attribution subsets, not independent strategy trials. Each distinct settled event counts once within category; estimated-only includes any event with at least one estimated cohort; incomplete excluded. 90% t intervals do not adjust for event dependence, same-day clustering, nonrandom selection or historical estimation. Concurrent MT-029 owns separate correlation study and API deploy; no duplicate deploy was initiated for MT-027.
- **Earlier checkpoints (superseded by this live verification) follow for history.**
- **Post-merge CI green for MT-027:** merge SHA `5d3504c` runs [44971725044](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971725044) and [44971728276](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971728276) both succeeded. Processing worker has already deployed this ancestor (`dep-dc14dku0tbcc73abdd10` live 01:36 UTC). The separately owned MT-029 PR #332 merged later and **owns pending shared staging API release** for its correlation log; avoid a duplicate/manual API deploy while its postmerge CI/deployment is in progress. MT-027 needs read-only `favorites_timed_rollup.research_evidence.categories[*].attribution_sensitivity` evidence from that live API before marking DONE.
- **PR #330 MERGED** to `build/google-auth-foundation` as `5d3504ce9d8f8d328ac3c7dac7d1d7fe555ae5fb`. Exact-head full API/PostgreSQL CI [44971441808](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971441808) passed **2,125 tests**. Postmerge PR run [44971728276](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971728276) succeeded; push run [44971725044](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971725044) still in progress at checkpoint. API deploy/live exact-only sensitivity not yet verified. Concurrent MT-028 merged later; do not deploy unchecked latest branch or interfere with that owner's backup work.
- Draft [PR #330](https://github.com/princesspikachuu/kalshi-scanner-data/pull/330), head `d1c619de9d0a3c060a4714d12954068a9d0d6769`, based on `build/google-auth-foundation`. It adds derived category exact-only/estimated-only sensitivity to once-per-minute `favorites_timed_rollup.research_evidence`; no trading/ledger/SQL/R2/main dashboard payload changes.
- New event-level tests cover mixed attribution, duplicate cohorts/bots, 49→50 events, gains/losses, incomplete returns, source immutability, identifier redaction and reconciliation.
- Exact-head CI [run #44971441808](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971441808) **IN PROGRESS**. No merge/deployment yet; no claim of observed live exact-only profitability.

---

---

## MT-028 — Fail closed on R2 expiration rules before optional Favorites backup chunk reuse
**Status:** DONE — PR #331 merged; full CI, Render deployment, and new paper-worker handoff verified
**Worker:** ChatGPT / MT-019 Favorites backup retention guard
**Claimed:** 2026-11-22 UTC
**Urgency:** U2 — HIGH
**Priority:** Protect regular High-Probability Favorites recovery before any future opt-in R2 reuse

### Goal
Before the normal paper-maintenance backup may use any prior immutable R2 part, make a **read-only** bucket lifecycle check via the supported R2 S3 GetBucketLifecycleConfiguration operation. Any enabled completed-object expiration rule that could match `demo/backups/`, any malformed response, or any unverified policy state must block reuse and fall back to a full, independent snapshot. Disabled rules, unrelated prefixes, and abort-incomplete-multipart-only rules cannot delete completed backup parts. Do not enable reuse or change the existing daily backup schedule, R2 objects, keys, or retention policies.

### Safety / coordination
- This is strictly backup safety for the sole active **regular High-Probability Favorites** strategy under MT-019 / issue #238. Do not develop or activate Statistics-Backed Favorites or other strategies.
- `MT_CONTROL_BACKUP_CHUNK_REUSE_ENABLED` stays default **OFF** and must remain OFF in Render until an independent actual-bucket lifecycle audit and retained-root restore is performed.
- Protect all historical observations, paper orders, financial ledgers, positions, settlements, recovery catalogs/roots and chunk references; no new SQL or R2 writes beyond the already-required independent backup when due.
- Keep API/worker service lock and paper trading behavior unchanged. Sanitize any lifecycle failure log (fixed reason only; never exception text, credentials, bucket ID or rule IDs).
- Isolate implementation in the existing optional reuse and maintenance code, mock R2 checks and run exact-head full API/PostgreSQL CI. Draft PR until verified, then check actual Render deploy and worker health if merged.

### Completion notes
- **Code merged:** [PR #331](https://github.com/princesspikachuu/kalshi-scanner-data/pull/331), squash merge `b2b00915d215a05550578e296b7a3bc6f8f94829` into `build/google-auth-foundation`. Exact PR-head GitHub Actions [44971591074](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971591074) passed full API/PostgreSQL CI on `6ed43b2aa6` with no failed jobs. Post-merge push [44971914840](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971914840) and PR [44971919024](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971919024) validation **both passed**; Render processing staging deploy `dep-dc14ebh42hec73fifhag` at exact merge commit went **live 2026-11-22 01:37:32 UTC**.
- **Changed:** `services/demo/control_backup_chunk_reuse.py`, `services/demo/maintenance.py`, and two existing API test files. Only future opted-in due backups read the bucket's lifecycle via R2 S3; any overlapping/unknown completed-object expiry or unreadable policy falls back to a new independent complete verified snapshot. No object lifecycle changes, deletion, extra SQL, strategy activation or live orders. `MT_CONTROL_BACKUP_CHUNK_REUSE_ENABLED` remains default OFF.
- **Operator blocker remains:** Actual bucket lifecycle settings and retained-root restore have not been inspected with Cloudflare access, so the reuse flag must remain OFF. Cloudflare's standard incomplete multipart cleanup is not completed-object expiry. Refer to source docs https://developers.cloudflare.com/r2/buckets/object-lifecycles/.
- **Runtime acceptance verified:** New paper worker logged `shadow_worker_start_recorded` and `demo_worker_ready` at **2026-11-22 01:39:33 UTC** after old-instance exclusive-lock handoff; at 01:39:41 UTC, **75 regular High-Probability Favorites bots** and **0 Statistics-Backed Favorites bots** were running with real orders disabled. Four fresh `favorite_paper_entry` messages followed at 01:39:42 UTC, all paper-only; sampled error-level and `demo_backup_verification_failed` logs were empty after startup. No new full backup was triggered, no lifecycle config or R2 objects changed.
- **Follow-up for MT-019 (not code acceptance):** First daily verified backup after #325 will report `scope_sizes` and `favorites_shadow_bot_sizes`; use those exact counts before any lossless archive move. Actual bucket rules and retained-root restore still require separate verification before EVER enabling optional chunk reuse; completed MT-028 guard is not that authorization.

---

## MT-029 — Audit regular Favorites event correlation and same-day clustering
**Status:** DONE — merged, staged, exact/estimated plus correlation audited; limitations documented
**Worker:** ChatGPT / regular Favorites dependency and cluster confidence audit
**Claimed:** 2026-11-22
**Urgency:** U2 — HIGH
**Priority:** User-requested continuation of MT-023 after finding overlapping cohorts and uncertain nominal confidence

### Scope and acceptance
- Regular High-Probability Favorites research only. MT-027 is **already separately assigned** exact-vs-estimated return sensitivity; do NOT edit its sensitivity module, test files, `shadow.py`, or queue task. No data rewrites, trading changes, account/fee/settlement modifications or unrelated strategy analysis.
- Audit overlap of the *same* venue event ID within/between market-type categories separately from dependence among **different events** sharing a time/day cluster. Event identity already deduplicated by Single and must never be counted as independent per fill/contract/cohort.
- For category-level ROI, group distinct independently settled event identities into *strictly parseable* venue event dates only when date patterns can be verified. Report parse coverage, distinct day clusters, largest-day concentration, cross-category repeats and (when sufficiently supported) **day-cluster-robust 90% confidence intervals** using event-equal mean with a finite-cluster correction. Label within-day dependence assumption and remaining between-day/selection/estimated-return uncertainties; never imply that one calendar day is a guaranteed independent trial.
- Use bounded read-only aggregation from the existing derived regular Favorites workspace snapshot; avoid external DB/IP allowlist changes, new SQL/R2 reads and raw event/ticker/account identifiers in logs or UI. Prefer isolated source/test code to avoid conflicting with MT-027.
- Validate parsing of real Kalshi event formats and unknown-date fallback. Add tests for correlation vs exact duplicate ID, repeated fills, malformed/incomplete returns, cluster-robust variance, sparse-day withholding, source immutability and regular-Favorites-only scope.
- Coordinate with MT-027 before joining its in-progress diagnostics; no changes to its numerical ROI/P&L or 50-event nominal uncertainty rules. Preserve full history.

### Completion notes
- **Initial evidence:** MT-023 live sample had 7,906 Detailed event appearances vs 4,636 category-deduplicated settled outcomes (3,270 additional appearances; +70.5%), so treating cohort cells as independent would inflate n. The existing Single rollup already deduplicates within categories.
- **Draft [PR #332](https://github.com/princesspikachuu/kalshi-scanner-data/pull/332), branch `audit/mt029-regular-favorites-event-correlation-20261121`:** Isolated `favorite_event_correlation.py` + tests and once/minute `favorites_event_correlation` log. Strict venue `YYMONDD` date parsing supports known weather/15m ticker examples; explicit unknown fallback. Reports same-event ID overlap across categories, date parse coverage, days and within-day concentration. Conditional CR1 cluster-robust ROI 90% interval requires >=50 event-equal returns, >=80% dated coverage, >=20 distinct event dates and both gain/loss signs, otherwise unavailable. Distinguishes dated-subset iid interval from full-history nominal interval; never asserts day independence.
- **Coordination:** MT-027 [PR #330](https://github.com/princesspikachuu/kalshi-scanner-data/pull/330) is independently in progress on exact-vs-estimated split. MT-029 does not edit `favorite_research_coverage.py` and only adds a separate log after the existing research log. Validate merge ordering/conflicts before deployment. No actual event IDs, account balances, raw source or financial state are changed.
- **Validation / merge:** PR #332 exact-head GitHub Actions [44971870096](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44971870096) passed **2,137 API/PostgreSQL tests**, eight new correlation regressions and infrastructure/gateway checks. PR #332 merged into `build/google-auth-foundation` as **`4582aedcdb8fc4f9596306e12d1df587e571268d`** after PR #330 had merged; no overlapping source edits. New code also reports day-cluster coverage separately for exact-only and estimated-only event subsets without modifying MT-027's ROI calculations.
- **Runtime of first version:** Both MT-029 postmerge workflows [44972247044](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44972247044) and [44972250290](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44972250290) passed. API/worker `4582aedc` deployed live ~01:41 UTC; 75 regular Favorites bots active, 0 other running, real exchange orders disabled, no sampled error-level logs. The first `favorites_event_correlation` at 01:41:41 UTC found **4,637 unique event IDs across nine category totals, zero IDs shared between categories**. 15m crypto/commodities/finance, hourly crypto/weather/commodities all reported **0% parseable dates** under the overly restrictive date parser; sports 47 events span only **5 event dates**, daily weather 19 across **4 event dates**. These were not enough for a defensible cluster-adjusted interval. Do not treat 0% as proof the dates don't exist.
- **Independent exact/estimated live results, same 01:41 UTC snapshot (MT-027 ownership unchanged):** Exact-only category mean ROI nominal CI includes 0 in every category where >=50 returns. Approximate examples: crypto-15m exact n=495, -2.50%, [-6.76,+1.76]; estimated n=1915, -3.44%, [-5.60,-1.28]; finance-15m exact n=193, -2.84%, [-8.98,+3.30], estimated n=517, -3.34%, [-7.08,+0.41]; crypto-hourly exact n=115 +0.11% and estimated n=104 +3.50%, both nominal bounds cross zero. Correlation still unaddressed for all nominal bounds.
- **Parser correction merged:** [PR #334](https://github.com/princesspikachuu/kalshi-scanner-data/pull/334) merged as `8fc3ad1fdb4341fe2dc60fac6f9a50b48e60732a`, expanding strict known date parsing for 15m `YYMONDDHHMM` and hourly `YYMONDDHH`, with HH/MM validity checks, extra-digit rejection and unknown fallback. Exact-head full API/PostgreSQL validation [44972869053](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44972869053) **passed 2,145 tests**, including ten correlation regressions. **Post-merge CI runs [44973236030](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44973236030) and [44973240306](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44973240306) both passed**, parser fix deployed live to API on `8fc3ad1f` at **2026-11-22 01:54:55 UTC** and processing worker at **01:54:36 UTC**. Verified first live corrected log below. No financial/strategy/historical writes.

- **Final observed event-dependency audit (API event `favorites_event_correlation`, 2026-11-22 01:55:01 UTC):** **4,637 unique regular Favorites settled event identities across categories, zero identities shared between categories**. Strict encoded event-date parsing now succeeded for **100% of outcome events in every nonempty category**, with no identifiers logged or inferred. But date diversity is tiny: crypto-15m **2,410 events on 7 dates**, max day **33.03%**; commodities-15m **1,022 on 5 dates**, max day **44.03%**; finance-15m **710 on 5 dates**, max day **46.62%**; crypto-hourly **219 on 7 dates**, max day **31.51%**; weather-hourly **186 on 7 dates**, max day **32.80%**; commodities-hourly **24 on 5 dates**, max day **37.50%**; sports **47 on 5 dates**, max day **36.17%**; weather-daily **19 on 4 dates**, max day **36.84%**; finance-hourly **0**. All derived event-level returns are placed on an encoded date in nonempty categories, but **NO category has >=20 independent proxy date clusters; NO day-cluster-adjusted 90% interval is reported.** This is insufficient evidence to quantify serial/within-day correlation's impact on the nominal 90% P/L intervals. 50 independent ticker events are NOT 50 independent date clusters.
- **Attribution sensitivity (API `favorites_timed_rollup`, same release):** 4,637 event-level hypothetical held returns across categories (1,063 exact-only / 3,574 estimated-only; approximately **77.1% estimated**). Every adequately sampled **exact-only** category ROI nominal 90% interval includes zero; don't claim a positive or negative reproducible financial edge from this model. Estimated and exact subsamples are nonrandom and cluster risk remains unquantified. Repeated Detailed cohorts previously overstated independent event count if naively summed, but Single already deduplicates. User-requested actual historical exits with authoritative outcome continue to be included counterfactually as held; actual sale records/balances stay intact.
- **Operational verification:** Both staging API and paper worker live on `8fc3ad1f`. Post-release worker `paper_strategy_health` at 01:54:43 and 01:55:13 UTC showed **75 running regular Favorites bots**, zero others, `real_orders_enabled=false`, no sampled error-level API or worker logs. Worker `demo_worker_ready` marker was not observed in narrow window, but health reports confirmed paper-strategy operation; no claim of new paper fills.
- **Interpretation / next action:** Current derived workspace view captures **only 4–7 encoded market dates** per populated category (possibly affected by bounded research retention); don't infer that historical archive has no older outcomes. Retain all source data and assess retained/archived date coverage separately, then collect or securely recover >=20 distinct dates per category before day-cluster-adjusted inference. Even >=20 does not prove independence between dates; consider autocorrelation and a frozen out-of-time confirmation cohort before changing Favorites entry selection. 184 populated price/time cells create multiple-testing/selection bias; no strategy-selection or live-order changes justified now.

- **User clarification supersedes date gate (2026-11-21):** Day-cluster thresholds and the previous >=20-event-date recommendation are **NOT requirements** for prediction-market Favorites analysis. Date diversity is optional context, not a readiness gate. Use independently deduplicated settled market events as the observation denominator, verify entry-cost/held-outcome attribution, exact vs estimated ROI and event-based uncertainty by price/time bucket. Do not prioritize more calendar dates just to satisfy MT-029's day-cluster test.

---

## MT-030 — Investigate low regular Favorites trade throughput on November 21, 2026
**Status:** IN PROGRESS — main 15m discovery bottleneck FIXED and six independent paper first-filled events verified; venue settlements and comparable throughput still pending
**Worker:** ChatGPT / MT-030 Favorites trading slowdown audit (claimed 2026-11-22 UTC)
**Urgency:** U1 — URGENT
**Priority:** Investigate immediately after active P0 integrity blockers; user reports that trading was unusually slow all day and remains far below expectations.
**Reported:** Saturday 2026-11-21, America/Los_Angeles (local date; UTC events can span 2026-11-21 and 2026-11-22)

### Scope and goal
**Regular High-Probability Favorites ONLY.** Determine *why actual paper fills/trading volume were so low today*, and whether it is caused by limited eligible opportunities, discovery coverage or staleness, bots not becoming active, maker order placement/cancellations/short resting time, exposure/capital/risk/fee filters, settlement/collateral holds, execution/quote routing, task/worker backpressure, market-specific timing windows, or missing diagnostic counts. Explicitly exclude **Statistics-Backed Favorites** and every other strategy from any debugging changes, optimizations, tests of throughput, or reactivation.

### Investigation and required evidence
- Establish a timestamped Nov 21 **Pacific-time** baseline versus at least the preceding comparable day and most recent successful active windows. Do not mistake 75 enabled bots for 75 trading opportunities. Break down **15-minute crypto/finance, hourly crypto/finance/commodities, weather hourly/daily, and sports**, including markets with zero trades.
- Trace the complete **market discovered → admitted/subscribed → valid fresh bid/ask/fee snapshot → eligible opportunity → decision/gating reason → maker/taker choice → submitted/open bid → first/partial fill → cancellation/expiry/rejection → position → authoritative settlement** funnel. Count **independent market events and order attempts**, not contracts, duplicate fills or bots, and distinguish *observed* from *inferred* reasons.
- Measure quote resting duration, bid churn and cancellation causes, any limit on simultaneous outstanding bids, per-market exposure and available funds, suspicious time-to-expiry filters, disabled/nontrading bot states, worker locks, queue lag, memory/CPU, API rate/fee readiness, data gaps and missed eligible markets. Include detailed empty hourly-finance coverage previously flagged by MT-018/MT-023.
- Compare read-only telemetry with known [MT-024](https://github.com/princesspikachuu/kalshi-scanner-data/pull/328) and **MT-026** maker-order churn evidence; prior sample showed many unfilled cancels, but mismatched order cohorts must **not** be reported as a precise fill rate. Coordinate with existing MT-018 discovery balancing, MT-026 quote-churn work, and MT-019 settlement/backup owners; do not duplicate their overlapping code changes.
- Rank measured **root causes** by lost eligible events/fills and propose fixes that genuinely increase qualifying trades (especially hourly/other undersampled categories) without reducing healthy 15m activity, relaxing fee/risk/exposure or market-finality protections, or compromising the research's observation integrity.
- Implement only clearly validated Favorites-related fixes in an isolated branch/PR with focused and full API/PostgreSQL tests, preserving all historical observations, orders, balances, held-to-settlement interpretation and paper-only behavior. Compare before/after **actual fills and independently settled events**, not quote attempts or contract counts alone.

### Acceptance criteria
A concrete baseline table by market type and hour; measured gating and loss-of-opportunity distribution; demonstrated explanation for the unusually low Nov 21 trading; tests for any fix; and post-deployment evidence of increased *qualifying* regular Favorites fills without missed settlements or other strategies running. Record truly unavailable markets or absent data explicitly rather than assuming the algorithm is too restrictive.

### Coordination
**Do not work on Statistics-Backed Favorites, Market Maker or any other strategy. Never enable LIVE trading.** Keep R2 history immutable, current worker lock singleton, settlement and risk safeguards intact. MT-030 is CLAIMED and in progress. MT-018 owns the separate 15-minute discovery fix; MT-028 has completed its separately owned work.

### November 22 02:13 UTC diagnostic outcome
- **Cash-source correction:** On Nov 21 **08:06:10 PST**, regular Favorites paper cash was **$391.6271** (available $384.7571), then at **08:06:40 PST** cash was **$5,390.2271** (available $5,384.0571) while the engine processed command rows. Strongly consistent with a **$5,000 paper refill/adjustment**, not proof of a large ordinary settlement-cash release. Command type not independently inspectable from the available Render logs; no ledger/settings mutation performed. The overnight $0.20 funding shortage remains real but should not be diagnosed as naturally resolved by a settlement.

- Merged [PR #336](https://github.com/princesspikachuu/kalshi-scanner-data/pull/336) now actively emits bounded and fixed `unfilled_cancel_causes` on live worker: **7** submitted weather maker bids representing **4** independent submitted events, **2** first-filled orders representing **2** first-filled events, **2** confirmed unfilled cancels, **3** still-open bids in a *five-minute rolling/restart-local* sample at 02:13:34 UTC. Both cancellations were `quote_unavailable`, with median resting time ~143 sec, and observer errors zero. These counts are not a daily fill rate, and do not justify changing order timing or protective filters.
- Verified regular Favorites-only runtime: 75 regular Favorites, zero Statistics-Backed, real orders disabled; recent samples show low backlog, safe RSS and restored available cash. 15m discovery remains the lead blocker, not maker resource saturation.
- Separate MT-018 [PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335) exact head `ac414bf6ea6b73865a436d29dbb6110aa454e881` has **BOTH full [44974770656](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974770656) and focused [44974770666](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974770666) CI passing**, but still draft/unmerged at checkpoint. Keep scanner code and merge under MT-018 ownership; wait for exact Render rollout and 15m first fills before declaring slow trading fixed.
- Detail: [MT-030 shared audit](docs/audits/MT-030-regular-favorites-nov21-throughput.md), section "Post-deployment maker cancellation evidence".

### November 22 02:14 UTC — 15-minute discovery fix merged
- MT-018 owner merged [PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335) **at 2026-11-22 02:14:03 UTC** as `618370c663b3ead89389e8453a83fee16ba21bf3`, after exact-head full and focused CI passed. Postmerge GitHub push [44975123669](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975123669) and PR [44975129411](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975129411) both still in progress at checkpoint, so Render is still serving preceding `d8de25f7`. **Do not claim fix live or restored throughput** before release and real 15m market/fill observations.
- Separate MT-030 cancel instrumentation remains validated live: the 02:13:34 UTC rolling window had 7 submitted regular weather bids, 2 first-filled independent events, 2 unfilled cancels **both `quote_unavailable`** after about 143s median rest, 3 still open, observer errors zero. No evidence supports relaxing safety limits. Cached historical verified outcomes continue to be preserved.

### November 22 02:20 UTC — 15-minute discovery rollout
- MT-018 [PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335) merge commit `618370c663b3ead89389e8453a83fee16ba21bf3` now passed **both post-merge full CI**: push [44975123669](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975123669) and PR [44975129411](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975129411). Render deployment `dep-dc152bflk1mc7383ilig` became **live 2026-11-22 02:20:09 UTC** at that exact commit. Replacement worker initially emitted `demo_lock_wait`; at this checkpoint exclusive takeover and active 15m market/bid evidence are **not yet verified**. Do not force a lock takeover.
- Last pre-15m-fix rolling weather snapshot (02:17:27 UTC) had **12** maker bids submitted, **7** first-filled orders across **4 independent events**, **3** unfilled cancellations (2 `quote_unavailable`, 1 `same_bucket_reprice`) and 2 still open; avoid treating that as a cohort fill rate. This sample was stored in the shared MT-030 audit before worker replacement.

### November 22 02:22 UTC — live 15m discovery and first paper fill VERIFIED
- [PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335) both postmerge full CI passed; exact merge `618370c663b3ead89389e8453a83fee16ba21bf3` deployed to Render as `dep-dc152bflk1mc7383ilig` at **02:20:09 UTC**. New singleton paper worker acquired its lock and logged `demo_worker_ready` **02:22:14 UTC**; fee warmup **22/22 verified**. At 02:22:53 UTC **75 regular Favorites, 0 Statistics-Backed, all other bots paused, live orders off**, measured admission available with zero backlog and memory ~20.5% of limit. No forced takeover or historical reset.
- **Six 15m crypto series resumed independent new-market maker bids** in first 8 seconds: `KXBTC15M`, `KXETH15M`, `KXNEAR15M`, `KXHYPE15M`, `KXDOGE15M`, `KXSOL15M`. All logged bids were maker, 1 contract, 95c, **paper only**. First new-worker 02:22:53 UTC `favorites_quote_lifecycle`: **9** submitted 15m orders, **1** first-filled order from **1 independent event**, **8** open and **0** confirmed unfilled cancels. 20 active/fresh tracked markets. This **verifies primary missing 15m discovery AND the paper-first-fill path recovered**, but **not** hourly/daily frequency gains or venue-final outcomes.
- New 15m first fills will produce research outcomes only after official final settlements. At 02:22:53 UTC the 15m last-hour *verified outcome* count remained 0, as expected for still-open new events. MT-030 remains **IN PROGRESS** pending post-release independent fills and later authoritative settlements/profitability; do not force exits or count orders as observations.
- Evidence: [MT-030 report](docs/audits/MT-030-regular-favorites-nov21-throughput.md) and [Issue #333 live verification comment](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333#issuecomment-7072876258).

### November 22 02:23 UTC — six independent 15m first-fill events
- **Postrelease safety at 02:24:24–27 UTC:** `paper_strategy_health` still **75 regular Favorites bots, 0 Statistics-Backed, 0 other active strategies**, real orders disabled. Render error-level logs since new worker takeover were empty. Settlement polling remains **venue_not_final** for older unresolved held markets; this does not justify a forced payout, and new 15m events have not yet yielded official outcomes.

- New live paper worker's `favorites_quote_lifecycle` **02:23:53 UTC** counted **15m_price: 19 submitted maker orders across 9 independent events, 6 first-filled orders across 6 independent events, 10 orders still open, 0 confirmed unfilled cancels**. Additionally, weather: 1 submitted order/event, 0 first fills, 1 open. Overall: **20 submissions / 10 distinct events / 6 first-filled distinct events / 11 open**. This is a rolling/restart-local count with censored still-open orders: **not** a day-wide fill rate, not 6/19 validated odds, and not settled outcomes.
- This validates MT-018's restored 15m discovery and regular Favorites paper first-fill path for multiple independent events with legacy, Stats-Backed and all other strategies paused, live orders off. [Updated MT-030 evidence report](docs/audits/MT-030-regular-favorites-nov21-throughput.md). **MT-030 remains IN PROGRESS** awaiting authoritative exchange-confirmed post-expiry settlement attribution of these new 15m fills and longer-window throughput comparison. Preserve all history, don't manually pay, exit or relax margins to manufacture results.

### Investigation checkpoint — November 21 Pacific
- **Confirmed source defect and owner:** legacy `ForwardRun.legacy_discovery_required(series)` gated the sole 15-minute contract discovery on paused Convexity bot `enabled`, without checking enabled regular Favorites. [Issue #333](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333) and **MT-018 draft [PR #335](https://github.com/princesspikachuu/kalshi-scanner-data/pull/335)** own a deterministic, standalone scanner fix; MT-030 must not edit `runner.py`, its tests, or other MT-018-owned discovery code. This is a major probable cause of late-day missing 15m fills, not evidence of a broken paper execution engine.
- **Read-only observed evidence:** 75 running regular Favorites bots, zero Statistics-Backed bots; later live books mostly hourly weather, while rolling independently verified 15m outcomes dropped to zero in the last hour. Source shows `favorite_paper_entry` logs **submissions, not fills**. A selected five-minute lifecycle snapshot near 21:44 UTC had **29 submitted bids, one first-filled order, 39 unfilled cancellations** (different event/order cohorts; not a valid fill percentage). MT-026 also found large maker-cancel volume, requiring cause attribution.
- **Money/capacity windows:** At **09:57 UTC Nov 21 (01:57 Pacific)**, 26 eligible fresh Favorites markets but only **$0.2036 unreserved cash / $19.2036 paper cash**, 515.01 open contracts (401.38 still open across 17 markets; 113.63 expired but awaiting official settlement across 3 markets), and 2 resting orders. Available cash recovered to above $5,000 later. This confirms overnight collateral starvation; do not manufacture exits or force settlement. A 13:55 UTC hourly discovery check found one eligible crypto market but admission was deferred by measured capacity; later polls often found zero qualifying listed candidates. Near 21:58 UTC, 22 eligible fresh markets, $5,415.87 available cash and 6 resting orders. Worker samples showed low queue lag, no backlog/cpu saturation, so no basis to increase worker resources as a throughput fix. Hourly finance on Saturday can be unavailable due normal market hours.
- **Separate safe instrumentation:** [Merged PR #336](https://github.com/princesspikachuu/kalshi-scanner-data/pull/336) adds fixed, bounded, regular-Favorites-only reason codes for **confirmed unfilled maker cancellations** to the existing 5-minute quote lifecycle telemetry. Keeps `Engine.cancel`, order prices/sizes/lifetimes/fees, source data, portfolios and live orders untouched. Exact-head and post-merge API/PostgreSQL CI passed. Render released the exact merge SHA; new-worker reason evidence is still required before marking complete.
- **Limitations:** Render Postgres externally unreachable because staging IP allowlist intentionally empty; no network/allowlist changes authorized. Earlier daily logs lack this new observer, and transient rolling cohorts must not be misrepresented as exact day-wide fills or independently settled outcomes. A useful Nov 20 vs Nov 21 apples-to-apples fill baseline may require verified per-event persisted snapshots after access via existing authorized paths. Do not reset historical state.
- **PR #336 merged:** [PR #336](https://github.com/princesspikachuu/kalshi-scanner-data/pull/336) exact-head `bf790c77d448e22a6630f72c555183b4e703180c` passed both focused CI [44973731770](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44973731770) and full API/PostgreSQL [44973731797](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44973731797); squash merged as **`ce0765c902c4b37a6a8d3c9404210a317551b2c4`**. Exact-merge post-merge **CI passed** (push [44974058622](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974058622), PR [44974063291](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974063291)). Render automatically deployed exact SHA as **live** [dep-dc14s2vb9u1s73ftuibg](https://dashboard.render.com/worker/srv-dbhcqr0473hc739kj4pg), finished **2026-11-22 02:06:47 UTC**. **New worker handoff verified:** after `demo_lock_wait`, new worker emitted `shadow_worker_start_recorded` and `demo_worker_ready` at **02:08:48 UTC**. At **02:08:57 UTC**, new `favorites_quote_lifecycle` included `unfilled_cancel_causes: {}` and `observer_errors_total: 0` (first fresh window had zero submissions/fills/cancels); `paper_strategy_health` confirmed **75 regular Favorites, 0 Statistics-Backed, all other strategies paused, real orders disabled**. Handoff preserved singleton lock. Further actual canceled orders and first fills required before reason-based optimization. No trading/fee/risk/expiry/history changes.
- **Shared detailed audit:** [MT-030 November 21 regular Favorites low-trading report](docs/audits/MT-030-regular-favorites-nov21-throughput.md) with timestamped sampled market availability/cash/held-contracts, important source defect and measurement limitations.
- **Next:** Collect new maker order and cancellation activity by market type after the verified worker handoff, including first fills and real settled independent event outcomes. Distinguish unknown, missing and zero, and don't change quote lifetimes without causal evidence. No forced lock break or history mutation. Coordinate with MT-018's PR #335: restored 15m subscriptions, actual first fills and subsequently authoritative independent settlements are required. MT-030 stays IN PROGRESS until post-fix activity is verified.

### User's 4-event/last-hour question — audit reconciliation at 18:18 PST Nov 21
- **Actual worker audit, 01:18:16–02:18:16 UTC (17:18–18:18 PST):** 98 regular Favorites maker `ORDER_SUBMITTED`; 35 actual BUY `FILL` and `FAVORITE_ENTRY_COHORT` records; 14 distinct contract/threshold tickers filled but only **8 independent exchange events** (four hourly-weather city series × closing-hour 21 and 22), all weather. No recorded buy fills from crypto, finance, commodities, sports or daily weather in this hour. Cash ample; running 75, ~11–15 valid markets, capacity admitting/backlog 0, prior monitoring memory <75% guard.
- `favorites_collection_quality.unique_verified_1h=4` describes **newly observed settled outcomes**, not entry fills. The new `FavoriteFilledEvents` 1H tracking started when MT-031 deployed ~02:12:15 UTC (only 6 minutes before user's 02:18 snapshot), so its count was correctly **partial** and may read `≥4` even though the full 60-minute raw audit shows eight independent filled events. Do not mistake 4 for the complete hour's trade total or 35 contracts/fills for 35 independent observations.
- **Observed root cause of market-type concentration:** regular Favorites 15m scanner had wrongly followed paused legacy Convexity (issue #333, now PR #335 merged); the fix became live on worker only 02:20:09 UTC, AFTER the measured hour. Still no 15m monitored/submitted in 02:20–02:22 UTC first post-deploy sample; coordinate MT-018 owner on inventory/discovery gate rather than assuming recovery. Hourly-price discovery returns no eligible listed markets, Daily Weather city-local entry windows sleeping until next eligible period (one ~03:00 UTC), verified live sports late window absent. Available cash ~$5.4k, paper only.
- **Measurement caution:** venue/event identity inferred from `ticker` by removing strike suffix when counting the audit; all eight are corroborated by the city+hour event codes. Read-only Render logs, no DB mutation; direct Render SQL unavailable because Postgres IP allowlist blocks hosted MCP (do not change networking just for this audit). No raw user secrets accessed.

### Post-#335 trading recovery and remaining quote churn — 02:29 UTC Nov 22
- Reconciled 02:20:10–02:28:30 UTC as **49 maker order submissions, 21 BUY fill records, 9 distinct filled exchange events** (7 crypto 15m and 2 hourly weather). All 7 filled 15m crypto event IDs are independent across BNB/DOGE/SOL/XRP/ETH/ZEC/NEAR; no 15m final venue settlement asserted yet. Confirms the long-standing 15m discovery block was a major cause of Nov 21 zero-crypto throughput; **the code fix is actually trading**.
- Five-minute rolling `favorites_quote_lifecycle` near 02:28:59Z: 15m `quote_unavailable` unfilled cancel cause 24, `partial_guard` 2, `redundant_after_fill` 1, with 0 open 15m maker orders at that instant (time-bound near market rollover). These cancellation figures can include orders submitted before the current rolling window and **must not be divided by that window's submission count** as a fill rate. Validate if late-window cancels were eligible for fills before changing any quote safeguards.
- The hourly-price scanner separately checked 16 series in the sampled recent log window and found zero listed eligible markets, while Daily Weather's city-local window was sleeping until its next scheduled entry. Distinguish genuine venue inactivity from missed discovery; no read-only logs support a capital/risk or RSS limiter. Follow [Issue #333 update](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333#issuecomment-7072938694); no settings/ledger/history changes made.

### Completed root-cause verification, 02:31 UTC Nov 22
- The main Nov 21 zero-15m-Favorites root cause (legacy Convexity pause suppressing independent collector discovery) is not just inferred: PR #335's live worker obtained 15m maker fills and **5 separate venue-settled new 15m event outcomes** (ETH, NEAR, SOL, XRP, ZEC) as of 02:30:31 UTC. See [Issue #333 final confirmation](https://github.com/princesspikachuu/kalshi-scanner-data/issues/333#issuecomment-7072953287), now closed. Current total `unique_verified_1h=9` includes the 5 newly confirmed 15m outcomes; distinct fills vs settlements remain separate measures.
- Keep MT-030 **IN PROGRESS** for 15m quote cancellation root causes and remaining inactive hourly-price/sports/daily-weather windows, and for statistically honest post-fix baseline comparisons. Do not change risk/fee/freshness gates to chase activity without loss-of-eligible-event evidence.

### Second 15m rollover verified — 02:30–02:31 UTC Nov 22
- Continued live worker `618370c6` did not need a restart. After the 02:30Z contract expiry, `favorite_paper_entry` emitted fresh maker bids for **next 21:45 ET expiry** events across BTC, ETH, SOL, DOGE, BNB, ZEC, NEAR and XRP 15m series. In 02:30:05–02:31:18Z audit logs, 21 new maker submissions and **12 new BUY fill records** across **8 independently filled events** (5 crypto series BTC/ETH/SOL/NEAR/DOGE, 3 hourly weather). One event can have multiple maker fills; do not mistake 12 for 12 settled events.
- `paper_position_settlement_poll_health` 02:30:54Z recorded 7 confirmed-queued settlement lookups and 16 venue-not-final responses, showing recoverer continues polling rather than assuming no result; no original historical/portfolio mutation by triage. Worker still 75 regular Favorites active, no real orders, 21 fresh/active books.
- **Main discovery defect #333 closed**, but **MT-030 remains open** for eligible listing/quote cancellation/missed opportunity measurement and post-fix comparison. Price/fee protections left intact.


## MT-031 — Restore Daily Weather research table and period-specific distinct filled-event counts
**Status:** DONE — merged, full CI passed, staging frontend/API/worker deployed, runtime checked
**Worker:** ChatGPT / Daily Weather research and filled-events period UI
**Claimed:** 2026-11-22 01:55 UTC
**Urgency:** U2 — HIGH
**User request:** Daily Weather shows no research data table; show number of observed **filled events** in smaller text beneath dollar P/L, responsive to All, 1H, 6H, 24H, 7D, 30D selectors.

### Acceptance / safety
- Diagnose the actual missing Daily Weather table; verify existing data against derived research outputs and preserve detailed, Wider 3×3, and Single choices, never fabricate timing or settlement outcomes.
- Display distinct event identities with an executed **buy fill**, NOT contracts, orders, maker submissions, partial fills, or settlement-only reports. Avoid equating a settled-event count to new fills in a selected period.
- Per-window counts should be temporally scoped to the same selected P/L window, and clearly mark partial or missing history rather than emitting a misleading zero. Apply to visible relevant P/L headings (overview, folder, market-type, bot) where supported by source data. Preserve other strategies' visibility and period behavior.
- No changes to trading decisions, LIVE orders, bot enablement, cash/settlements, backups, originals, R2, history retention, or MT-018/019/029/030 work. No expensive full JSONB scans or unbounded snapshot payload. Add repeat-fill/event dedup, time window, missing-history, UI and Daily Weather regression tests.
- Development based on `build/google-auth-foundation`, draft PR until CI, then verify exact staging release, worker health and research visibility.

### Completion notes
NaN- **Root cause:** Daily Weather had confirmed event-level research (19 settled category events) but `favorite_wide.summarize_wide` could not establish a reliable 3-way entry-time span, so it emitted no Wider cells; the frontend showed only a waiting paragraph despite populated Detailed/Single data.
- **Draft [PR #337](https://github.com/princesspikachuu/kalshi-scanner-data/pull/337)** on branch `fix/mt031-weather-wide-and-filled-event-periods-20261121`: category and market-level Wider views now fall back to actual verified detailed cohorts (then Single if only those are available), without guessing time thirds.
- Introduced a bounded, durable-checkpoint-compatible **actual BUY FILL event** observer in regular Favorites only. Distinct event identity counts per all/1H/6H/24H/7D/30D are sent as safe counts on folder, category and bot snapshots; repeats, contract counts, sell fills, and outcomes without fill timestamps cannot inflate recent totals. Older/incomplete coverage is explicitly partial.
- The small event-count subtitle renders under P/L in top overview, folder, market-category and individual bot views; bot-time and folder-time controls update the number.
- Targeted UI and Python regression tests added. Initial CI run caught an escaped-HTML assertion and was corrected. Exact-head full CI still in progress; **no merge or staging deployment yet**. Preserve independent MT-030 changes when merging.



---

---

## MT-032 — Add event-based held-profit uncertainty to regular Favorites price/time cohorts
**Status:** DONE — merged, deployed API/frontend, event-based live confidence verified
**Worker:** ChatGPT / Detailed and Wider held-ROI interval audit
**Claimed:** 2026-11-21
**Urgency:** U2 — research reliability after event-based clarification

### Goal
Calculate and display **90% event-level held-return uncertainty** for populated Detailed and Wider regular High-Probability Favorites price/time cohorts, using the exact same pooled one-event-one-vote, fee-inclusive hypothetical held-to-settlement return method and >=50 event minimum as Single. These are **not** separate contracts, partial bids, repeated price-tier appearances or calendar-day clusters. Maintain distinct win-rate Wilson error vs held-profit-return Student-t error.

### Boundaries and coordination
- No 20-day cluster threshold, day-diversity gate, or automatic trading decision. Independently confirmed exchange event identities are the research observations. Source data and original early-exit cash ledger remain unchanged.
- Active MT-031 [PR #337](https://github.com/princesspikachuu/kalshi-scanner-data/pull/337) owns the `apps/web/shadow-view.mjs` view and Daily Weather fallback; coordinate any markup changes, avoid overwriting its edits. MT-030/MT-018 own quote and discovery throughput. Do not touch other strategy portfolios, LIVE orders, settlements or backups.
- Derive 90% bounds from already-pooled per-event return maps in the regular Favorites Detailed and Wider summarizers only; no new SQL queries or heavy history reads, and never generate independent observations from aggregated counts lacking IDs.
- Distinguish 'under 50 independent settled hold returns', '50+ but no observed gains *and* losses', and a valid numerical interval. Show uncertainty in **percentage points** next to held ROI (not win-rate margin); do not misrepresent unadjusted exploratory interval as proof of profitability, especially across many tested cells.
- Add event-dedup, repeat-fill, missing-settlement, historical known-exit, estimated-return, threshold, zero-variance and frontend regressions. Base implementation on `build/google-auth-foundation`, draft PR and CI before staging release.

### Completion notes
- Merged [PR #338](https://github.com/princesspikachuu/kalshi-scanner-data/pull/338) on `feat/mt032-event-based-held-roi-bucket-confidence-20261121` adds a regular Favorites-only event-pooled held ROI 90% Student-t interval to Detailed and Wider backend cohorts using Single's 50 independent-event return threshold; no day gate. It preserves each event's derived fee-inclusive held outcome and original historical exit ledger. Price/time cells reused across the dashboard are **not** treated as independent aggregate samples. It does not affect Statistics-Backed Favorites or other trading strategies.
- Compact UI shows `P/L 90% ±Xpp` separately from Wilson win-rate error when valid; expanded details give interval, distinct event n, estimated attribution, and multiple-testing caveat. It suppresses stale numeric bounds below 50 events and refuses to manufacture intervals from client-aggregated row summaries.
- **Validation and integration:** Earlier PR-head run [44974857878](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44974857878) **passed 2,166 API/PostgreSQL tests** plus all 5 new Node UI regressions after correcting a test-expected-value parenthesis (production ROI math unchanged). PR #337 Daily Weather and PR #335 discovery fixes advanced the branch; PR #338 was safely rebased onto latest `build/google-auth-foundation` commit `618370c6` as PR head **`5edb3db9eb0847f60939cd9b3cae0a49d0a2ff1a`**, preserving their frontend fallback/filled-event logic and backend discovery changes. **PR #338 merged** on latest development branch as commit `b9fc1bf3dc50aa881bcaf20cd3ebafa195a16424` after integrated exact-head [CI 44975304175](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975304175) passed **2,184 API/PostgreSQL tests** and the new frontend regressions. Post-merge API/infrastructure [44975770133](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975770133) and [44975765581](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975765581) **both passed**, and dedicated Cloudflare staging frontend [44975765522](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975765522) **passed and verified the four deployed frontend assets against exactly `b9fc1bf3`**. The separate generic gateway workflow [44975765565](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975765565) deployed the same assets but failed an **unauthenticated root-page GET 403** smoke check on both attempts; this failure also occurred on earlier commits `d8de25f7`, `e1cb0472`, `a21e109b`, etc., **not introduced by MT-032**. Do not claim generic gateway boundary passed. API Render `pocket-api-staging` is **Live on `b9fc1bf3` at 2026-11-22 02:27:26 UTC**; `favorites_timed_rollup` at 02:27:40 UTC emitted real event-level ROI intervals/status for populated Detailed price/time cells. Four subsequent `dashboard_transport` responses completed; zero error-level API logs in sampled period. Processing worker remains Live on prior `618370c6` intentionally; runtime reported 75 regular Favorites bots, zero others, real orders disabled and no sampled error-level worker logs. No historical, paper order or portfolio mutations.

- **Live MT-032 bucket evidence (API `favorites_timed_rollup`, 2026-11-22 02:27:40 UTC):** commodities-15m 70¢/10–15m **n=349, average +5.87%, nominal 90% held ROI CI [+0.55%, +11.18%], 349 estimated**; commodities-15m 75¢/10–15m **n=182, average +9.20%, CI [+3.35%, +15.05%], 176 estimated**; crypto-15m 70¢/5–10m **n=413, average -5.55%, CI [-10.90%, -0.20%], 255 estimated**. Finance-15m 75¢/10–15m n=90 +5.07%, CI [-3.87%,+14.02%] crosses zero. Crypto-hourly 90¢/15–30m n=44, +8.81% average, **numerical P/L interval suppressed (needs 6 additional distinct settled returns to reach 50)**. Results are **exploratory**: many candidate price/time cells were screened and historical entry quantities are frequently reconstructed. A selected nominal interval entirely above/below zero is NOT sufficient out-of-sample/multiple-comparisons evidence of a reproducible edge. Neither day-diversity nor a 20-calendar-day sample requirement is used.
- **Next, if assigned:** Prioritize event-based verification and pre-registered out-of-sample bucket confirmation, exact-vs-estimated attribution sensitivity and maintaining independent per-market settlement evidence. Do not add a calendar-day gate or automatically alter paper bids on these exploratory results.


---

## MT-033 — Forward-only regular Favorites price/time profitability validation
**Status:** DONE — merged, exact-head/post-merge CI passed, API and paper worker deployed and runtime-verified  
**Worker:** ChatGPT / Money Tree Chat 04, forward-only regular Favorites validation  
**Claimed:** 2026-11-22 UTC  
**Urgency:** U2 — HIGH  
**Priority:** Preserve meaningful 90% confidence assessment after MT-032 without recycling the same selected historical outcomes

### Scope and acceptance
- Regular **High Probability Favorites only**; no Statistics-Backed Favorites, other portfolios, real trading, or changes to entries, exits, fees, risk, settlement, cash, or historical observations.
- Freeze a fixed short-list of Nov 21 **historically selected/exploratory** Detailed 15m price/time cohorts and evaluate separately on **future-date, independently settled exchange-event returns**. The holdout date gate is for a forward-time split only, **not** a minimum number of calendar days / day clustering requirement. Each verified event counts once within a cell even with repeated bids/contracts.
- Use conservative valid venue event date labels strictly after 2026-11-22 (earliest 2026-11-23), never reconstruct fill timestamps or treat encoded dates as authoritative settlement timestamps. Mark the test as date-proxy forward evidence, not a guarantee the market was never previously monitored or a multiple-testing-adjusted proof.
- Reuse the regular Favorites read-only held-to-settlement research view and fee-inclusive per-event 90% Student-t interval with the existing 50-independent-event minimum and both observed positive and negative returns. Unknown outcomes, missing event attribution, unparseable labels, and historical dated events do not count.
- Fixed exploratory cohort shortlist from MT-032 Nov 21 checkpoint: commodities-15m 70–74¢ / 10–15m; commodities-15m 75–79¢ / 10–15m; crypto-15m 70–74¢ / 5–10m; finance-15m 75–79¢ / 10–15m. No midstream cherry-picking based on forward outcomes.
- Provide bounded, identifier-free forward progress for these four cells alongside existing one-minute regular Favorites research diagnostics; no new DB queries, R2 accesses, persistent event IDs, expanded background jobs, or new worker tasks. Add deterministic tests for old/new dates, repeat fills, estimated historic attribution, unknown/unsettled events, incomplete event returns, 49/50 confidence gating, shared-event overlap and unchanged source records.
- Run exact PR-head GitHub API/PostgreSQL checks, safely merge and verify API telemetry when tests pass. Other task owners retain MT-019 settlement, MT-030 throughput and MT-011 resources.

### Completion notes
- **Draft PR [#340](https://github.com/princesspikachuu/kalshi-scanner-data/pull/340)** on branch `feat/mt033-forward-only-favorites-validation-20261121`, head `c039769cd758fb51d0cde8ab72b4379929000167`. Read-only new `favorite_forward_validation.py`, once-per-minute API report in `services/api/shadow.py`, seven deterministic regression tests in `services/api/tests/test_regular_favorites_forward_validation.py`.
- Strict future venue event **label** after 2026-11-22, frozen four Nov 21 research coordinates, deduped event-level held ROI; never treat the label as verified original fill/settlement timestamp. No calendar-day cluster requirement, no trading, other portfolio, SQL/R2, settlement, history or risk changes.
- The initial PR-head run [44977398195](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44977398195) failed **one fixture assertion** because an entirely absent return cost is intentionally reconstructible in existing derived held research. The test now uses an explicitly invalid source cost, which must remain incomplete. **Corrected exact-head CI [44977409576](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44977409576) passed all 2,191 API/PostgreSQL tests**, plus auth and focused checks. PR #340 merged as `c1c44dc6440252b41f2831776bbe44d8d1e2f8ec` into `build/google-auth-foundation` at 2026-11-22 ~02:48 UTC. Postmerge push [44977776273](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44977776273) and PR [44977780206](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44977780206) CI **both passed**. Render processing worker auto-deployed exact merge `c1c44dc6` as `dep-dc15iee417fc73b79kb0` live 2026-11-22 02:54:37 UTC; its lock handoff finished safely with `shadow_worker_start_recorded`/`demo_worker_ready` at 02:56:42 UTC. API explicitly deployed exact SHA as `dep-dc15ikifngtc73em1o0g`, live 02:55:11 UTC. API emitted valid `favorites_forward_validation` at 02:55:17 UTC: all four forward cohorts have zero independently settled returns before Nov 23 event labels (the correct expected empty state); historical exclusions 462/227/501/99 appearances respectively, no unparseable appearances. No numeric interval fabricated. New worker's 02:56:59 UTC health: 75 regular Favorites bots, zero all other running strategies, real orders off, capacity admission true, backlog zero, RSS 179,425,280/2,147,483,648 bytes; no error-level worker/API logs in sampled postrelease window. Historical trading, settlements, backup settings and cash not changed.


---

## MT-034 — Fail safely on malformed future-entry timestamp hints (regular Favorites)
**Status:** DONE — PR #341 merged, exact-head and postmerge CI passed, deployed via verified descendant Render worker SHA (2026-11-22 UTC)
**Worker:** Money Tree — Chat 1.1: Discovery Optimization (successor to Chat 1.0 / legacy Chat 01)
**Claimed:** 2026-11-22 UTC
**Urgency:** U2 — HIGH
**Priority:** Guard regular Favorites discovery against malformed venue schedule hints without overlapping MT-018 market scanner ownership

### Reproduced source issue / scope
PR #314 introduced `known_entry_wake` as a read-only venue schedule hint in `services/paper_demo/shadow/discovery_wake.py`. Its `ts` parser calls `value.replace(...)` for anything other than int/float. JSON `null` or array/object schedule values raise **AttributeError** (not among the wake helper's caught KeyError/ValueError/TypeError/OverflowError), so a nonessential future hint can propagate a scanner exception and skip all remaining market discovery work for that scan pass. Boolean values also masquerade as numeric epoch timestamps.

**Bounded fix:** In the shared helper, reject booleans and unsupported input types with a caught TypeError before ISO timestamp parsing. Add focused unittest cases for null/list/object/bool in hourly, 15m, weather daily and sports schedule fields, while preserving valid venue times and the existing fail-open-to-discovery unknown-schedule policy. Do not edit `hourly.py`, `weather.py`, `runner.py`, market discovery/admission, entry/cancel, fees, trading, cash, settlement, or persistence. No changes to Statistics-Backed Favorites or other strategies; paper-only. Recheck latest base before a safe independent PR and run full hosted API/PostgreSQL CI before merge/deploy.

### Chat 1.1 successor checkpoint (2026-11-22 UTC)
- Chat 1.1 took over release verification from Chat 1.0; #341 merged and CI passed, but exact Render deployment cannot be independently verified because the Render connector requires a user-confirmed workspace selection. No claim that code is deployed. No app code or trading state changed.

### Final release verification — Chat 1.1 (2026-11-22 UTC)
- [PR #341](https://github.com/princesspikachuu/kalshi-scanner-data/pull/341) merged as `447ff4dd6129e4dd39e2a13511b699b349ee3805`; exact-head and postmerge hosted API/PostgreSQL CI **PASSED**. GitHub compares confirm `447ff4dd` is an ancestor of #343 merge `9158a089`, which is an ancestor of #342 merge `c9802172`, both with zero behind-base commits.
- Chat 3.1's [independently verified Render worker report](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339#issuecomment-7073424429) confirms `c980217225fa0f14bfd04de6a4b98e08d062ae5b` deployed at 03:11:23 UTC, exclusive worker ready 03:13:29 UTC. This is verified deployment **by descendant ancestry plus the cited runtime report**, not by direct Render access in Chat 1.1. No need to trigger extra deployment. No actual malformed production timestamp observed; safety behavior is covered by deterministic tests.
- Task closed for code + release acceptance; MT-018 remains open for Monday funded weekday finance evidence. No trading/ledger/other strategy changes.

### Completion notes
- **Release checkpoint:** [PR #341](https://github.com/princesspikachuu/kalshi-scanner-data/pull/341) **merged** on 2026-11-22 UTC as `447ff4dd6129e4dd39e2a13511b699b349ee3805` after exact combined head `90a25a499e3be1d8fedee3be0ec98d047c38496a` passed full hosted API/PostgreSQL [44977857044](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44977857044). Postmerge [workflow 44978194515](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978194515) **PASSED** full API/PostgreSQL checks. Render exact deployment remains unverified in this chat (requires workspace selection). Do not claim live release until verified.
- **Previously draft [PR #341](https://github.com/princesspikachuu/kalshi-scanner-data/pull/341)**, branch `fix/mt034-malformed-known-entry-wake-timestamps-20261121`, current exact head `90a25a499e3be1d8fedee3be0ec98d047c38496a`. Safely integrated concurrent regular-Favorites PR #340 base `c1c44dc6440252b41f2831776bbe44d8d1e2f8ec` using a two-parent commit; compare confirms only the same two expected modified files, with zero behind-base commits.
- `discovery_wake.ts` now rejects unsupported JSON input types and booleans with `TypeError`, allowing existing `known_entry_wake` failure-to-schedule path to return `None`. Added 45 invalid-field deterministic subcases across 15m, hourly, weather daily and sports. No scanner, execution, fee, risk, wallet, settlement or history mutations.
- Original full API/PostgreSQL workflow [run 44977652713](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44977652713) and new exact-combined-head workflow [44977857044](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44977857044) are **in progress** at this checkpoint. New head must pass before merge. Draft/unmerged, not deployed. Must confirm exact-head full CI, review base changes, and then do guarded merge/release verification.
- MT-018 remains the sole owner of pagination/full listing and weekday finance no-trade work ([#339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339)); MT-030 retains order/fill throughput.


---

## MT-035 — Read-only weekday finance-hourly Favorites entry-funnel visibility
**Status:** IN PROGRESS — PR #342 and #346 merged, deployed, and runtime-verified; funded weekday finance BUY fills/outcomes still unproven
**Worker:** Money Tree — Chat 3.1: Finance-Hourly Investigation (successor to 3.0)
**Claimed:** 2026-11-22 UTC
**Urgency:** U1 — URGENT
**Priority:** Diagnose the persistent zero-finance-hourly-Favorites-trades problem before any cash starvation; coordinate with MT-018's exclusive scanner work and MT-030's maker-lifecycle work.

### Scope
- Regular High-Probability Favorites only. Issue [#339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339) tracks eleven configured finance-hourly series with no verified settled research rows.
- MT-018 / Chat 01 exclusively owns `hourly.py`, market listing and pagination. **This task must not modify scanner code or trading gates**. MT-030 retains its separate maker cancel logic. Instead add a bounded, periodic, read-only post-admission diagnostic in the existing hosted regular Favorites health pass, using already retained engine/book/order and discovery-coverage state. Never add REST requests or DB/R2 activity.
- For each enabled finance-hourly series, separately report whether it has a fresh scan, active admitted market, fresh two-sided book, price-qualified maker candidate, verified zero-maker-fee marker, enough paper cash for one contract, and active maker buy orders. These are *snapshot-stage indicators*, not independently tradeable/filled event counts, promises of fills or a full historical funnel.
- The diagnostic must not call any trading action, invoke recovery/fee refresh, change wallet/risk/order/settlement state, or log market/order identities, private book depths, or secrets. Log at most once per minute with a bounded small summary and non-fatal errors. Preserve all histories and real_orders_enabled=false.
- Add deterministic synthetic tests for funded qualifying, cash-starved, stale/one-sided/price-disqualified, zero-fee-unverified, empty/disabled series and separation from other portfolios. Run exact-head focused + full API/PostgreSQL CI and deploy/verify only after passes, coordinated with Chat 01. Record actual weekday before/after results and do not claim root cause without a real venue observation.

### Completion notes
- **Draft [PR #342](https://github.com/princesspikachuu/kalshi-scanner-data/pull/342)**, branch `feat/mt035-finance-hourly-favorites-funnel-20261121`, latest combined head `9c80900f2c7da2503d4b925b7e0651afcc6dd84c`. Two-parent integration of merged Chat 01 wake safety base `447ff4dd6129e4dd39e2a13511b699b349ee3805`; PR diff remains exactly three MT-035 files.
- Only three changed files: `favorite_finance_health.py`, once-per-minute bounded logging in `host.py`, and 11 synthetic tests `test_favorite_finance_health.py`. No scanner, order, fee, settlement, cash, historical or other-strategy code changed.
- Latest exact-head one-contract validation [44978275053](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978275053) **PASSED**. Latest exact-head full API/PostgreSQL [44978275073](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978275073) **IN PROGRESS**, not yet passing. Independent fee-verification count added before book-freshness. **No merge, deployment, or verified weekday finance fills.**
- Historical correction: CFTC 2025 listings confirm `KXUSDJPYH` and `KXEURUSDH` were genuine at that time; their absence from a 2026 category listing is **not** proof they never existed or are currently eligible. Follow up with provider verified series metadata without deleting source history.


### Chat 3.1 — merged/released live verification (2026-11-22 03:13 UTC)
- **MT-035 [PR #342](https://github.com/princesspikachuu/kalshi-scanner-data/pull/342) MERGED** as `c980217225fa0f14bfd04de6a4b98e08d062ae5b` after exact-head one-contract [CI #44978275053](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978275053) and full API/PostgreSQL [CI #44978275073](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44978275073) passed. The Render staging processing service automatically deployed that exact commit as `dep-dc15q6m1egvs73809rf0`, live at **2026-11-22 03:11:23 UTC**. Do not manually trigger a second deployment.
- New singleton worker `srv-dbhcqr0473hc739kj4pg-9ls9f` safely acquired the lock and emitted `demo_worker_ready` **03:13:29 UTC**; no forced unlock. First `favorites_finance_hourly_funnel` occurred **03:13:46 UTC** with **11 configured, 11 enabled**, available cash **$5,417.6319**, zero admitted finance markets and no logged error. All 11 per-series `scan_recent=false` at this *initial* startup snapshot, before first scanner pass; **not** proof of weekday listing absence. `paper_hourly_scan` at **03:13:49 UTC** did check one finance profile with zero eligible Saturday-evening listings; do not infer weekday root cause.
- **Monday November 23 during funded weekday finance sessions:** take multiple new once/minute per-series snapshots after completed scans, then correlate scanner coverage with consumer admission, fresh two-sided books, fee-verified 70–95c maker price, one-contract funding, actual order, BUY fill and final authoritative venue settlement. Distinguish missing/stale scan, absent listing, zero quote, fee, cash and quote churn; never infer unique event counts from point-in-time market snapshot metrics. Do not change any trading/fee/risk/settlement/history controls on Saturday to manufacture activity.
- [Issue #339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339) remains **OPEN**. MT-018 / Chat 1.1 owns scanners and pagination; Chat 3.1 owns this post-admission finance diagnostic. The public [Kalshi hourly-finance category](https://kalshi.com/category/financials/frequency/hourly) presently presents 8 hourly products, while the [15-minute finance category](https://kalshi.com/category/financials/frequency/fifteen_min) includes FX. This is a **metadata verification lead**, not authoritative proof that any exact configured FX hourly ticker is invalid; do not remove profiles or historical records without authenticated Kalshi series metadata.

### Ownership transfer to Chat 3.1 (2026-11-22 UTC)
- User explicitly established this new conversation ID as **3.1**, successor to Chat 3.0. Registered as active in `main:docs/CHAT_INDEX.md` commit `a3db29569e1f05eb72a1b5b8075fe58b5385c39e`; the next unused third-stream conversation ID is `3.2`. This transfers the **existing MT-035 claim only**, not other queued tasks.
- Chat 3.1 owns the merged/deployed read-only regular Favorites finance-hourly diagnostic PR #342 and Issue #339 post-admission evidence review. MT-018/Chat 1.1 retains exclusive hourly/FX/market discovery scanner/schedule code. The separately generically claimed MT-030 broad throughput task requires explicit owner reconciliation before any assumption of ownership or overlapping changes.
- Verified Saturday 03:14:47 UTC snapshot: 9/11 finance series scanned recently with zero markets inside the last hour, and 2 cash-index profiles waiting for weekday session prewarm. Available paper cash >$5,400. This is not the weekday root cause; preserve history and await verified weekday fills/settlements.

### Chat 3.1 — next read-only clarification draft [PR #346](https://github.com/princesspikachuu/kalshi-scanner-data/pull/346) (2026-11-22 UTC)
- Branch `feat/mt035-finance-schedule-diagnostics-20261121`, latest head `afc881e5305d9ecedbe9da52746a35d4a8eb77ca`, **MERGED** into `build/google-auth-foundation` as `bb23bd72657525b7fb3b7d29aa1bd7d8e962c104`; **Render rollout not verified yet**. This PR only changes the existing `favorite_finance_health.py` read-only post-admission log helper and its standalone test file (no scanner, bot, cash, fee, real orders, settlement, DB or historical changes).
- Separates `scan_state` into recent / scheduled_cash_index (NYSE calendar hint) / scheduled_retry (pre-existing hint) / stale / never_scanned; exposes last scan age/reason, cached series frequency, bounded next-scan hint. Invalid/nonfinite persisted scan timestamps now remain `unknown_scan_time` rather than producing a failed health emission; deterministic regression added. New metadata only uses existing in-memory fields and pure calendar logic; does **not** invoke provider REST, authorize orders or assume market availability.
- Motivation: first three Saturday runtime reports after #342 showed **9 recent finance scans with 0 eligible listed last-hour markets** while both cash indexes had `scan_recent=false` (possibly expected NYSE weekend sleep), which the existing `no_recent_scan` label could not distinguish. All weekday pre-cash first-fill questions remain open in [#339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339).
- Added deterministic tests for Saturday index scheduling, stale vs explicit retry, immutable existing cached series metadata, bounded invalid hints and no event inference. Exact-head full API/PostgreSQL CI [run 44980269668](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980269668) **PASSED** at exact PR head; postmerge push [44980717479](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980717479) and PR [44980720955](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980720955) are still running. Full `services/api/tests` suite includes the five new deterministic finance tests; no separate one-contract workflow was triggered due its file-path filters. PR safely merged with only the two expected changed files and no behind-base commits; release requires passing postmerge CI, automatic checks-pass Render deploy, safe lock takeover and observed `scan_state` runtime. Chat 1.1 retains scanner ownership.

---

### Chat 3.1 — PR #346 production paper-runtime verification (2026-11-22 03:36 UTC)
- [PR #346](https://github.com/princesspikachuu/kalshi-scanner-data/pull/346) merged as `bb23bd72657525b7fb3b7d29aa1bd7d8e962c104`. Exact-head full [CI #44980269668](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980269668), postmerge [push CI #44980717479](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980717479), and postmerge [PR CI #44980720955](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980720955) all **PASSED**. Verified postmerge PR CI logged **2,212** passing `services/api/tests`, including each of five new scan-state tests. Changed files only `favorite_finance_health.py` and `test_favorite_finance_health.py`.
- Render `pocket-processing-staging` `autoDeployTrigger=checksPass` released exactly `bb23bd7` as `dep-dc164qu0tbcc73acqt60`, status **live 2026-11-22 03:33:40 UTC**. No manual deploy/forced lock. Replacement singleton `srv-dbhcqr0473hc739kj4pg-9wxvw` emitted `demo_worker_ready` at **03:35:46 UTC**, after normal lock wait; original `9ls9f` ceased exclusive execution.
- First new-schema `favorites_finance_hourly_funnel` observed **03:36:04 UTC**: 11/11 enabled finance series, **two NYSE cash indexes explicitly `scheduled_cash_index`** with known next prewarm hint (~125,575 seconds), nine other profiles **`never_scanned` immediately after worker startup** (not a broken scanner). Available paper cash `$5,428.827`; zero finance admitted at Saturday-evening sample. `paper_strategy_health`: 75 regular Favorites enabled, **zero** other strategies, `real_orders_enabled=false`; `paper_monitoring_capacity` admitting, backlog 0, RSS pressure ~8.4%. No error-level/finance-funnel-error/scan-retry logs in initial worker slice. **Second worker snapshot 03:37:05 UTC verified:** all nine non-index finance series had `scan_state=recent`, cached verified `frequency=hourly`, `scan_listed_last=0`, `scan_eligible_last=0`, and reason `No active markets closing within one hour`; both stock indexes remained `scheduled_cash_index` rather than falsely `never_scanned`. Paper available cash `$5,418.717`; no admitted finance markets. This Saturday evening sample verifies diagnosis metadata, not weekday tradability.
- **This fixes observability, not trading.** MT-035 and [Issue #339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339) remain open until weekday finance opportunities can be verified after discovery, admission, fresh book/price/fee/cash checks, actual first BUY fill and independently confirmed final venue outcome. Chat 1.1 retains scanner ownership; do not relax market hours, fees, risk, settlement or cash conditions to fabricate fills.

## MT-036 — Show forward-only regular Favorites profitability validation on the dashboard
**Status:** IN PROGRESS — PR #349 merged; postmerge CI, staging frontend and hosted API runtime acceptance pending
**Worker:** Money Tree Chat 4.1 — forward profitability evidence display
**Claimed:** 2026-11-22 UTC
**Urgency:** U2 — HIGH
**Priority:** Expose MT-033's pre-registered holdout in the operator-facing regular Favorites research view before future settled events accumulate

### Scope
- **Regular High-Probability Favorites ONLY.** MT-033 already computes four frozen event-label-post-2026-11-22 cohorts in a once-per-minute API diagnostic. The dashboard cannot currently see that bounded report; no independent longitudinal validation is visible without inspecting logs.
- Expose the same four pre-registered cohorts as a compact, read-only Favorites research panel: dated-label proxy cutoff, independent settled event counts vs 50, estimated attribution and missing-return counts, mean fee-aware hypothetical held ROI, and nominal 90% confidence bounds *only* when backend interval status and sample gate permit. Distinguish positive/negative interval entirely off zero from exploratory mean.
- Reuse the existing derived Favorites held view once per workspace response; keep the existing bounded logging cadence and avoid new SQL/R2 reads, provider requests, persistence, background loops, market/account identifiers, or raw event IDs in the frontend payload.
- Do not alter fixed cohort definitions/cutoff, trading, buys, risk, fees, cash, exits, settlement, existing records, Statistics-Backed Favorites, other strategies, or LIVE orders. The Chat 1.1 scanner, Chat 3.1 finance/throughput, Chat 2 deployment, and MT-019 backup owners retain their separate work.
- Verify UI markup with synthetic zero/49/50 sample, all-winner, positive/negative/cross-zero intervals, malformed bounds and absent-API cases; run exact-head API/Postgres + frontend CI. Deploy/verify only after review and passing gates. Record PR/commits and outcome below.

### Completion notes
- **Draft PR [#349](https://github.com/princesspikachuu/kalshi-scanner-data/pull/349)**, branch `feat/mt036-forward-favorites-dashboard-20261121`. Initial source commit `6cebc803`; safely integrated concurrent Chat 3 finance diagnostic source via two-parent `e2b3f710` (base changed two **non-overlapping** finance-health files), then fixed dashboard VM test harness `4b82e4bf` and included the new targeted UI suite in hosted API/frontend test command `d7205177`. No source changes to trading, other bots, cash, fees, settlement or history.
- Adds `collector_forward_validation` from the existing regular Favorites derived held view to the four-cell workspace report, reusing it in one-minute log without additional DB/R2/provider accesses. Adds a compact user-facing forward profitability panel with sample count, estimated/incomplete evidence and conservative nominal 90% interval interpretation.
- First exact-head [CI 44980787577](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980787577) **FAILED** because `test_strategy_folders.mjs` VM setup lacked the newly imported UI helper; addressed in `4b82e4bf`. Follow-up [CI 44980838742](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980838742) passed its Node/browser suite; remaining API/PostgreSQL checks in progress at checkpoint. Latest commit `d7205177` adds `test_favorites_forward_validation_ui.mjs` to hosted Node regression command, requiring its own exact-head run before readiness. **NOT MERGED, NOT DEPLOYED.**
- **Additional CI finding and guarded repair (2026-11-22 UTC):** [run 44980838742](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44980838742) completed full 2,213 API/PostgreSQL tests with exactly **one failure**: the old `test_shadow_workspace_transport` under-2 KB compact-response assertion now sees a deliberate four-cohort, ~1.8 KB read-only report (response 3,809 bytes). Follow-up `c06667ad` keeps the original <2 KB assertion **for all pre-existing compact data**, independently caps the fixed new report below 2.3 KB and whole test payload below 4.3 KB; it does not remove the production 8 MiB transport rejection. The report remains exactly four event-equal cohorts and sends no raw event IDs. Commit `b477bf8e` adds narrow/mobile-friendly table styling without changing existing matrices. The staging frontend predeploy workflow now also includes the six new Node view tests (`e65e7034`). No data changes.
- **Latest exact-head:** `b477bf8eb86eafb3dabb32529e064b8540ef7c0b`, workflow [44981192526](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981192526) running at checkpoint (Node/browser checks already passed; API/PostgreSQL pending). PR #349 is **draft, mergeable, unmerged, not deployed**. Earlier runs before the size-contract repair are expected red and must never justify release.
- **Next:** inspect the *latest exact-head* hosted API/PostgreSQL result (not earlier red runs); only after green verify new base/diff and guarded merge, then coordinate postmerge frontend/API/worker deployment verification with Chat 2.0. Keep source records/ledgers and other strategies untouched.

- **Release gate update:** Exact combined-head [CI 44981523781](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981523781) **PASSED** full browser tests, hosted API/PostgreSQL tests and staging Blueprint validation at `a688c738c5a140e9bfd8243bb8c99aaca100575a`. It incorporated the latest non-overlapping Chat 1.1 scanner changes from base `2a699a21` via safe two-parent merge, with 0 behind-base commits; PR #349 was marked ready and **MERGED** to `build/google-auth-foundation` at commit `953fbcd7bb16002d7818c1228f6ce0501eaa8351`. No LIVE or other-strategy changes.
- **Postmerge checks launched for exact merge:** API [44981852121](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981852121) / [44981849031](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981849031), staging frontend [44981849032](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981849032), generic staging gateway [44981849012](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981849012), all **in progress** at checkpoint. Frontend asset identity and hosted API/worker runtime need verification before marking DONE; generic gateway's unauthenticated 403 has historically failed independently of signed-in access.
- **Chat 2.0 handoff:** Render workspace is not selected in this connector session, so API/processing worker exact-deploy/runtime logs require independently authorized workspace access or verification by Chat 2.0. Do not infer API or worker live from GitHub merge alone. The new workspace field is read-only, uses the same regular Favorites held research, and its four event-label cohorts remain unchanged.
- **Frontend verified at exact merge:** [Money Tree staging workflow 44981849032](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981849032) **PASSED**, including deployment to `pocket-analytics-staging` and byte-for-byte validation of published `shadow.html`, `shadow.mjs`, `shadow-view.mjs`, and `money.css` against merge `953fbcd7`. The independent [generic gateway workflow 44981849012](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981849012) deployed successfully but then **FAILED** the known unauthenticated sign-in asset HTTP403 vs expected 200 smoke check. Do not mistake this for a new authenticated API failure or claim that check passed.
- **Remaining acceptance:** postmerge hosted API CI [44981849031](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981849031) / [44981852121](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44981852121) still running at checkpoint; Render staging API and processing-worker exact revision and regular Favorites runtime status **unverified** without a user-confirmed Render workspace. Keep task IN PROGRESS until this is verified or explicitly handed off.

