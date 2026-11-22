# Money Tree — unfinished and abandoned-task audit

**Prepared by:** Money Tree — Chat 02 (deployment verification / coordination).  
**Snapshot:** November 21, 2026 Pacific / November 22, 2026 approximately 02:54 UTC.  
**Authoritative scope:** `main:WORK_QUEUE.md` — **regular High-Probability Favorites ONLY**. Other strategies remain paused.  
**User clarification:** **Only numbered Chats 01, 02, 03 and 04 are active**. Generic previous ChatGPT/Codex workers without explicit reassignment must not be treated as currently staffed.

This is a **read-only ownership and completeness audit**, not a claim, implementation, merge, deploy, recovery or permission to alter source history.

## Inventory and interpretation

- Shared queue: **35** numbered MT tasks; **27 DONE**, **7 IN PROGRESS**, **1 BLOCKED**, **0 READY**. An `IN PROGRESS` label is not proof an agent remains active.
- GitHub at audit time: **8 open issues** (6 directly related to the Favorites/recovery system and 2 unrelated paused strategies), approximately **12 open pull requests** after PR #341 merged.
- **Open or merged PR does not imply runtime deployed**, and `DONE` in a header does not by itself establish a passing acceptance test.
- Old issue and PR timestamps are historical; do not declare a code defect currently live merely from an old open ticket.

## Ownerless or ambiguous unfinished tasks — act on these first

| Task | Queue status / previous worker | Actual remaining work | Proposed next action; NOT an assignment |
| --- | --- | --- | --- |
| **MT-019 — storage, verified backups, recovery** | `IN PROGRESS`, generic `ChatGPT / storage-outage investigation`, claimed Nov 10 | **P0**. [Issue #238](https://github.com/princesspikachuu/kalshi-scanner-data/issues/238) remains open; actual R2 original/readback coverage, recent complete backup acceptance, physical disk and `pg_wal` headroom, operator-controlled retention and credential gates, and safe settlement/restart reconciliation have open verification items. Historical source engineering complete does not equal operator acceptance. Related [#196](https://github.com/princesspikachuu/kalshi-scanner-data/issues/196), [#147](https://github.com/princesspikachuu/kalshi-scanner-data/issues/147) also remain open. | Split *completed safety code* from *blocked operator-only gates*; designate an owner among Chats 01–04 for coordination. No SQL purge, unsafe archiving, R2 expiration, downtime, resets or firewall/credential changes. Do not assume prior observed 88.15% disk usage (Nov 13) is current. |
| **MT-011 — resource / memory / checkpoint waste** | `IN PROGRESS`, generic `ChatGPT / MT-011 systems audit`, claimed Nov 9 | **U1**. [Issue #151](https://github.com/princesspikachuu/kalshi-scanner-data/issues/151) still open; checkpoint read/serialization/write pressure and old drafts need review. [Chat 02 verified memory report](chat-02-staging-memory-audit-2026-11-21.md): five genuine processing-worker 2 GiB OOM kills on Nov 20 Pacific; new instance ~0.9 GiB and admitting at latest checks, so neither leak resolution nor present memory gating is proved. | Explicitly reassign a narrow *regular Favorites only* engineering/long-run profiling task to a numbered chat. Review stale drafts before writing replacement code. Keep original history, held positions, measured admission safeguards and all other bots paused. |
| **MT-030 — slow Favorites fills and maker cancellation causes** | `IN PROGRESS`, generic `ChatGPT / MT-030 Favorites trading slowdown audit` | **U1**. [Issue #278](https://github.com/princesspikachuu/kalshi-scanner-data/issues/278) open; 15-minute discovery was fixed and filled/settled events verified, but broader quote churn, eligible-to-filled event opportunities and comparison baseline remain. | Confirm whether **Chat 03** owns MT-030 in addition to its expressly claimed **MT-035**. Do not duplicate Chat 01's **MT-018** scanner changes; do not weaken fee/risk or count orders/contracts as independent events. |
| **MT-017 — Cloudflare CPU / free-tier incident** | `BLOCKED`, generic old worker, claimed Nov 9 | Requires unavailable/unauthorized Cloudflare CPU metrics; direct ongoing effect on regular Favorites has not been established. | **PAUSE under current scope** unless an actively verified regular-Favorites dashboard outage or CPU error makes the work essential. Avoid spending an urgent slot merely because the old task is U1. |

### Presently owned by active numbered chats — do NOT reclaim

| Task | Numbered owner | GitHub status checked | Next acceptance step |
| --- | --- | --- | --- |
| **MT-018**, discovery / [issue #339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339) | **Chat 01** | In progress, 15-minute defect #333 corrected; separate weekday finance and pagination checks continue. | Complete scanner-specific source and real weekday admission evidence, preserving all existing guards. |
| **MT-034**, malformed venue wake hint | **Chat 01** | [PR #341](https://github.com/princesspikachuu/kalshi-scanner-data/pull/341) **MERGED 02:54:16 UTC**; previous queue entry still said draft/CI in progress. | Confirm exact postmerge CI and worker release; then update `WORK_QUEUE.md` to DONE. Don't prematurely relabel at merge. |
| **MT-035**, finance-hourly post-admission visibility | **Chat 03** | [PR #342](https://github.com/princesspikachuu/kalshi-scanner-data/pull/342) **open draft**, focused checks passed, full API/PostgreSQL pending. | Complete tests, merge/deploy safely and verify finance-hourly once a qualifying weekday session exists; mere scan counts are not fills. |
| **MT-033**, forward-only held-profit research | **Chat 04** | [PR #340](https://github.com/princesspikachuu/kalshi-scanner-data/pull/340) **MERGED 02:48:32 UTC**, full PR-head tests passed. API Render `c1c44dc6` was **update_in_progress** at 02:54 UTC, not yet independently live-verified at that checkpoint. | Confirm release, 1-minute telemetry, 75 regular Favorites running, and update DONE only after runtime acceptance. |
| **Deployments/monitoring** | **Chat 02** | Read-only checks and scheduled 75%/crash monitoring. | Verify rollout states; record failure evidence without editing other chat owners' source. |

## Unowned open pull requests — review rather than merge blindly

**Potentially relevant to regular Favorites or its infrastructure, but stale:**

1. [PR #247](https://github.com/princesspikachuu/kalshi-scanner-data/pull/247), draft since Nov 17 — bound websocket subscription scans. Possibly useful to MT-011; needs rebase, exact branch comparison, tests and demonstration the current implementation has not superseded it.
2. [PR #157](https://github.com/princesspikachuu/kalshi-scanner-data/pull/157), open since Nov 9 — bound redundant durable-event diagnostic logs. Check against later diagnostics/performance work before adoption.
3. [PR #124](https://github.com/princesspikachuu/kalshi-scanner-data/pull/124), open since Nov 9 — amortize checkpoint commits. Check against later merged checkpoint and scheduling changes (including #171) and preserve transaction/durability atomicity.
4. [PR #125](https://github.com/princesspikachuu/kalshi-scanner-data/pull/125), open since Nov 9 — fee refresh cadence. Compare with merged fee metadata fixes (#154 and newer); never relax zero-maker-fee/freshness gates without verification.

**Long-lived structural PR, not automatically abandoned:** [PR #9](https://github.com/princesspikachuu/kalshi-scanner-data/pull/9) is the umbrella development-branch-to-`main` draft and is updated when the active development branch advances. Treat merging it as a separate coordinated release, not as cleanup.

**Old unrelated PRs currently out of scope:** [#123](https://github.com/princesspikachuu/kalshi-scanner-data/pull/123), [#128](https://github.com/princesspikachuu/kalshi-scanner-data/pull/128) (Market Maker), and [#55](https://github.com/princesspikachuu/kalshi-scanner-data/pull/55), [#53](https://github.com/princesspikachuu/kalshi-scanner-data/pull/53), [#13](https://github.com/princesspikachuu/kalshi-scanner-data/pull/13), [#7](https://github.com/princesspikachuu/kalshi-scanner-data/pull/7) (other app/strategy/platform features). Do not pursue simply to empty the PR list. Similarly, open issues [#239](https://github.com/princesspikachuu/kalshi-scanner-data/issues/239) (Market Maker) and [#65](https://github.com/princesspikachuu/kalshi-scanner-data/issues/65) (Complete Set) are outside the user's current Favorites-only scope.

## `DONE` bookkeeping needing review, not presumed failures

- **MT-005** is marked DONE but its section still has `_Fill in when done._` with no linked PR or detailed acceptance record. Check whether PR #314 and other later monitoring/capacity work fully superseded its original scope. Do not re-run old capacity changes without a discrepancy.
- **MT-010** is marked DONE with only a placeholder completion note and no linked PR, but concerns **Statistics-Backed Favorites**, which is explicitly **out of current scope**. Documentation cleanup may be useful later; reactivation/optimization is not.
- MT-009 and MT-007 retain placeholder text in earlier section sections but also include actual later implementation/merge notes; this is **not evidence** that their implementation is missing.

## Recommended reconciliation, without altering task ownership today

1. **P0 MT-019**: appoint a numbered owner or classify remaining work as **BLOCKED—requires authorized operator evidence**; keep user-visible recovery risks explicit, not an indefinitely staffed `IN PROGRESS` fiction.
2. **U1 MT-030**: Chat 03 confirms whether its existing finance work also covers the broad throughput task; otherwise mark MT-030 available for separate re-claim by an existing numbered chat.
3. **U1 MT-011**: hand off scoped Favorites memory/checkpoint investigation to Chat 02 or another numbered owner once active tasks allow; evaluate #151, #247, #157, #124, #125 without conflicting with live work.
4. **MT-017**: change to `PAUSED — out of scope` unless evidence directly links Cloudflare CPU errors to current Favorites use.
5. **Current Chat 01/04 merges**: let their owners verify exact Render deployment/runtime and update MT-033/034 DONE; **Chat 03** finishes MT-035 PR #342.
6. Record old PR disposition explicitly as **rebase and test**, **superseded/close**, or **paused outside scope**, but do not auto-close or merge any without owner review.

**Safety:** This audit makes no changes to runtime code, policies, paper wallets, source records, SQL/R2 data, any deployment, or strategy status. The queue task-status fields and old PR states are preserved for the four active chats to reconcile deliberately. 
