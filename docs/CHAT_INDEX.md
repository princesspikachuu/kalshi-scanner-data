# Money Tree — Chat Stream/Round Register

**SUCCESSOR HANDOFF PROTOCOL (2026-11-22, newest user directive):** The user sends the **next conversation's number to the existing chat** (e.g. the active `1.1` chat receives `1.2`). The existing chat writes a GitHub handoff and produces a **ready-to-paste first message** for a new chat beginning with the exact title `1.2 - Money Tree`. The user pastes that generated message into the new conversation. It is NOT a request to rename the current chat. The successor must fetch this index and `main:WORK_QUEUE.md` before selecting work. See the section below. **READ THIS FIRST when creating, continuing, or handing off a Money Tree conversation.** The repository's **authoritative scope and task-claim file** is [`main:WORK_QUEUE.md`](../WORK_QUEUE.md) and this [`main:docs/CHAT_INDEX.md`](./CHAT_INDEX.md) is the **stream/round identifier register**. Always fetch both files from the `main` branch of `princesspikachuu/kalshi-scanner-data` at the beginning of a new conversation, before accepting task ownership or editing code. The queue's **"Chat naming and handoff rule — STREAM.ROUND"** section is authoritative if these two files ever disagree. Work branches may be based on `build/google-auth-foundation`; naming and ownership still live on `main`.

## Rule: `<stream>.<round>`, NOT a decimal number

- **Stream** = one of the four user-designated parallel work lanes (`1`, `2`, `3`, `4`). **Round** = successive ChatGPT *conversation threads* within that lane, starting at `0`. Continue within one thread without advancing the round. Creating the next handoff conversation increments that lane's suffix.
- **Current round:** `1.1`, `2.1`, `3.1`, `4.1`. **Next conversation in each lane:** `1.2`, `2.2`, `3.2`, `4.2`. Independent progress: one lane can move to `1.2` while the others remain at `2.0`, `3.0`, `4.0`.
- **After nine rounds** suffixes continue `1.9 → 1.10 → 1.11 → 1.12` (same rule for 2–4). **Treat identifiers as exact text labels, never floating-point values.** `1.10` must never be collapsed to `1.1`.
- **Required ChatGPT title:** Exactly **`<stream>.<round> - Money Tree`**, e.g. `1.1 - Money Tree`, `1.2 - Money Tree`, `1.10 - Money Tree`. Include the literal ` - Money Tree` suffix, **no additional topic**, prefix, or description. Topic/ownership metadata belongs only in GitHub. The assistant cannot directly set or view the ChatGPT sidebar title.
- **Legacy aliases:** Past references to `Chat 01`, `Chat 02`, `Chat 03`, `Chat 04` denote round-zero Chats `1.0`, `2.0`, `3.0`, `4.0`; do **not** rewrite historic citations, merge history, or task records just to relabel them. Chat IDs never equal `MT-###` IDs or PR/issue numbers.

## Current active conversation register

| ID | Historical workstream context (NOT a chat title) | Existing focus / claims | State |
| --- | --- | --- | --- |
| **1.0** | Discovery Optimization | Prior round: PR #314, #335, #341 and #343 discovery work; MT-018/MT-034 handoff | **Succeeded by 1.1** |
| **1.1** | Discovery Optimization | Successor to 1.0; MT-018 discovery verification and weekday finance listing gates, MT-034 release verification; coordinate with Chat 3 MT-035 and Chat 2 deployment | **Active — registered 2026-11-22 UTC** |
| **1.2** | Discovery and finance-hourly runtime verification (topic metadata only) | Successor to 1.1; handoff on main WORK_QUEUE.md under MT-018; exclusive scanner ownership NOT yet transferred; PR #347/#351 merged, verify exact Render deployment and weekday outcomes | **PREPARED — NOT ACTIVE; 1.1 retains MT-018 until successor checks in (2026-11-22 UTC)** |
| **2.0** | Deployment Verification | Predecessor to 2.1; runtime health, memory audit, and MT-017 Cloudflare read-only observability bridge PRs #344/#345/#348/#350 | **Succeeded by 2.1** |
| **2.1** | Deployment Verification | Successor to 2.0; continue MT-017 Cloudflare CPU read-only diagnostic and verify GitHub Actions/Render safety without taking other streams' code | **Active — registered 2026-11-22 UTC** |
| **3.0** | Trading Throughput | Previous round: finance-hourly MT-035, diagnostics PR #342, MT-030 shared inquiry; handoff to 3.1 | **Succeeded by 3.1** |
| **3.1** | Trading Throughput | MT-035 handed off to 3.2 after prepared successor check-in | **Succeeded by 3.2 — 2026-11-22 UTC** |
| **3.2** | Trading Throughput (topic metadata only) | ACTIVE successor to 3.1; MT-035 regular Favorites finance-hourly read-only weekday evidence, Issue #339; scanner remains stream 1 | **ACTIVE — registered 2026-11-22 UTC** |
| **4.0** | Profitability Validation | MT-033 merged, deployed and verified; predecessor to 4.1 | **Succeeded by 4.1** |
| **4.1** | Profitability Validation | MT-036 #349/#353 merged; GitHub CI and staging assets PASS; verified 75 regular Favorites running and 230 recent paper BUY fill rows all with $0 recorded fees; API still LIVE on pre-#349 c1c44dc6 (manual deployment authorization required); no SQL read possible without unsafe allowlist change; 4.1 retains MT-036 | **Active — registered 2026-11-22 UTC** |

**Prepared successors:** `1.2` remains **PREPARED / NOT ACTIVE**. `3.2` activated after `continue` and succeeds `3.1`; its next successor ID is `3.3`. **Other planned successors:** `2.2`, `4.2`. **After 1.2 activates, its next ID will be `1.3`.** There is no blanket next-new-chat number `05` under this four-stream plan. Do not create a fifth stream without user instruction.


## Prepared handoff record — 3.1 → 3.2 (2026-11-22 UTC)

- **Current:** `3.1 - Money Tree` remains ACTIVE and MT-035 owner. **Prepared successor:** `3.2 - Money Tree` is PREPARED, not active; no transfer until new conversation receives `continue`.
- **Canonical complete handoff:** `main:WORK_QUEUE.md` under MT-035, heading `Chat 3.1 → 3.2 successor handoff (2026-11-22 UTC)`. Issue [#339](https://github.com/princesspikachuu/kalshi-scanner-data/issues/339) tracks the open weekday finance no-fill blocker. This record is informational and does not change task claims or deployment ownership.
- **Last completed verified predecessor work:** PR #342 `c980217225fa0f14bfd04de6a4b98e08d062ae5b` and PR #346 `bb23bd72657525b7fb3b7d29aa1bd7d8e962c104` merged, CI passing, deployed and read-only runtime telemetry validated on Render; latest directly observed new-worker sample 2026-11-22 03:37:05 UTC. Zero finance hourly eligible listings on Saturday does NOT answer previous weekday zero BUY fills.
- **Unfinished:** With funded Nov 23 weekday markets, identify exact failure stage discovery → admission → two-sided fresh fee-verified candidate → maker order → independent BUY fill → authoritative final settlement, without changing safety controls or rewriting history. Scanner owned by 1.1/activated 1.2, Cloudflare/deployment by 2.1, profitability by 4.1. Broad MT-030 is independently claimed. Preserve original ownership until explicit new chat activation.
- **Naming-only startup rule (user's latest directive, supersedes earlier bootstrap instructions):** Predecessor outputs exactly one copyable sentence `your name is 3.2 - Money Tree`. On new thread receipt the assistant replies only `3.2 - Money Tree`, performs no GitHub/memory/tools/task registration and remains naming-only until user says `continue`. After `continue` read current main queue and index, register 3.2 ACTIVE, mark 3.1 succeeded and transfer only MT-035. No claim that a ChatGPT sidebar title changed.

## Prepared handoff record — 1.1 → 1.2 (2026-11-22 UTC)

- **Current:** `1.1 - Money Tree`, remains active/owner until successor explicitly checks in. **Prepared successor:** `1.2 - Money Tree`, title exact; NOT active and NO ownership transfer yet. The current conversation must not be renamed.
- **Canonical complete predecessor handoff:** `main:WORK_QUEUE.md`, heading `Chat 1.1 → 1.2 successor handoff (2026-11-22 UTC)`, inside `MT-018`.
- **Repo:** `princesspikachuu/kalshi-scanner-data`. Coordination: `main`; development: `build/google-auth-foundation`, verified HEAD `cf2cf74e05ec220d23da4effb6282c77e580be7f` at preparation. Merged PR #347 (`2a699a2135a59e28d6d76a2b158140ea4909cab2`) and PR #351 (`cf2cf74e05ec220d23da4effb6282c77e580be7f`). PR #351 source branch `fix/mt018-hourly-fee-gate-reasons-20261121`, original head `1d8c1baad3a6350e7bd0d123a34b64ee57256829`; PR #347 source branch `feat/mt018-hourly-listing-stage-visibility-20261121`.
- **Verified CI:** PR #351 full API/PostgreSQL #44982045049 passed **2,223 Python tests** (including 3 new fee-stage tests); its postmerge push #44982441825 and PR #44982446595 BOTH passed. PR #347 original and combined exact-head and postmerge checks also passed. **Render runtime for exact PR #347/#351 merges remains unverified by predecessor**; Chat 3.1's earlier worker confirmation reached #346 (`bb23bd7...`), not proof of later merge deployment.
- **Unfinished MT-018:** finance-hourly regular High Probability Favorites, Issue #339, **zero verified independent weekday BUY fills and settled outcomes before earlier cash shortage**. Capture funded Monday Nov 23 FX/Treasury/cash-index venue listings, scan/quote/fee/admission stages, true first fills, official venue-final outcomes, or exact failure gate; distinguish page appearances from independent events. Confirm actual worker deployment before interpreting new stage fields. Preserve all history, protections and LIVE-disabled state.
- **Other owners:** 2.1 MT-017 Cloudflare/deployment, 3.1 MT-035 read-only finance funnel (and MT-030 claim to be verified), 4.1 MT-036 profitability/dashboard. They retain ownership; successor must not edit those files or workstreams.
- **Next step on new chat:** paste generated exact-title startup message, read GitHub main queue/index, verify this handoff and newer commits/PRs, change 1.2 to ACTIVE and transfer ONLY MT-018 from 1.1 in queue, update 1.1 to succeeded, coordinate deployment/runtime verification and weekday evidence. Do not start 1.2's implementation within 1.1.

## Successor handoff: the current chat prepares the next chat's first message

**Newest user directive (2026-11-22; supersedes the old bare-number-first-message startup rule):** Instead of starting a fresh chat by sending only `1.2`, the user sends **`1.2` in the CURRENT chat `1.1`**. This is a request for an explicit successor handoff and a complete first-message prompt to paste into a NEW chat. **Do not rename the existing conversation or treat the supplied successor ID as its new ID.**

**In the existing conversation, on receiving the successor ID:**

1. Interpret the supplied `stream.round` as a **string**, never a decimal; preserve `1.9 → 1.10`. Confirm it is the next ID in the same stream, using fresh `main:docs/CHAT_INDEX.md` and `main:WORK_QUEUE.md` plus the existing chat's ID. If already active/reserved in another lane, stop rather than overwriting it.
2. Fetch current GitHub PR/branch/CI/deployment and claims. Finish safe checkpoints; write an explicit predecessor handoff in the shared queue/index with current task, status, owners, latest branch, PR, SHA, tests, deployment evidence, unresolved blockers and exact next actions. **Reserve/prep** the successor in the index, clearly marked **prepared / not yet active**. Do not transfer live task ownership until the successor itself checks in or the queue expressly authorizes transfer.
3. Generate a complete **standalone copy-and-paste startup message** for the successor, preferably in a writing block. The **very first line** of that generated message must be exactly `<successor ID> - Money Tree`; this is also the exact intended ChatGPT sidebar title and the mandatory first line of the successor assistant's first substantive reply. Never put a topic in the title, although the work description may follow.
4. The generated message must instruct the new assistant to check the latest `main:WORK_QUEUE.md` and `main:docs/CHAT_INDEX.md` of `princesspikachuu/kalshi-scanner-data` **before taking ownership or editing**, locate the predecessor's handoff, reconcile other chats' claims, activate/register the successor ID, carry over only legitimately assigned tasks, preserve histories and safeguards, and **continue without asking the user to restate the work**. Include concrete current PR/branch/task identifiers and handoff references, verified at generation time, not guesses.
5. Explain briefly that the user should start a new Money Tree Project chat and paste the **entire generated message as its first message**. Do not paste only the number. Do not claim that generating the prompt or updating GitHub has renamed the ChatGPT sidebar; the user can manually correct the title if the app's automatic naming differs.

**Required opening of the generated successor message (replace bracketed IDs):**

```text
<successor ID> - Money Tree

Name this new ChatGPT conversation exactly "<successor ID> - Money Tree". This is my new Money Tree development chat and the successor to "<predecessor ID> - Money Tree". The title must contain the numeric ID and the project folder name only; never append a topic. Begin your first response with the exact title on its own line. Do not claim you changed the sidebar title unless you have actually done so.

Before any implementation, use the connected GitHub tools to read princesspikachuu/kalshi-scanner-data main:WORK_QUEUE.md and main:docs/CHAT_INDEX.md. Find the latest predecessor handoff and current active worker claims; verify status and register this new chat as active without overwriting concurrent ownership. Continue the predecessor's unfinished work with tests and safe commits, preserving historical observations, trade/fee/settlement safety, and the project-wide regular High Probability Favorites-only scope. If GitHub cannot be accessed, explain the blocker instead of guessing.

[Predecessor's specific committed handoff, task/PR/branch/commit references, blockers, next steps and any user instructions.]
```

The predecessor writes that precise ready-to-paste message **each time** a next-round number is supplied, rather than expecting GitHub rules or assistant self-naming to steer the app's automatic title generation. An explicit first-message title should improve title generation but **cannot guarantee** the sidebar; only the user may correct it manually where automatic naming differs.

**New successor's startup:** Treat the pasted prompt as the user's first instruction; obey the exact title, fetch both GitHub files, verify the reserved handoff against current claims, activate/register the successor, transfer only verified ownership, and continue work. Do not create a new successor or register another active thread just because someone typed a number inside the ongoing chat.

## New successor thread registration and task ownership

1. Fetch `main:WORK_QUEUE.md` and this `main:docs/CHAT_INDEX.md` to learn the exact current stream/round. Identify the predecessor stream and its most recent registered round. Read that predecessor's task handoff and live PR state before making claims.
2. When the predecessor prepares a new thread, record the next unused literal ID as **PREPARED / not yet active** and save its handoff. When the successor actually starts and checks in, reconcile that reservation and update the row to **ACTIVE**. Keep descriptive topics **only as internal metadata**, never in the title. Use the latest GitHub SHA, avoid collisions, and do not treat a prepared handoff as a live worker.
3. Have the predecessor (or, if unavailable, the successor after verifying status) update the task claim in `main:WORK_QUEUE.md`, including old/new owner, current branch/PR/CI/deployment, blockers, and next safe action. Merely taking a chat number is **not** task ownership or permission to take another lane's source files.
4. Do not advance a thread's suffix just because the user says "continue" inside it; the suffix advances only when a **new ChatGPT conversation** in that same lane is started. Preserve four streams unless the user explicitly expands them.
5. Maintain **regular High-Probability Favorites only** work, including essential common gateway/Cloudflare/Render infrastructure; keep Statistics-Backed Favorites and other strategies paused and LIVE real orders disabled.

---

## Chat 2.0 — Historical deployment and health handoff (snapshot)

**Checked:** 2026-11-22 approximately 02:45 UTC (Saturday, Nov 21 Pacific). These are latest observed deployment and sampled health facts, not a guarantee of future uptime.

- **Processing worker:** Render `pocket-processing-staging` live on `618370c663b3ead89389e8453a83fee16ba21bf3` (merged PR #335, regular Favorites 15-minute discovery), deploy `dep-dc152bflk1mc7383ilig`, successful at 02:20:09 UTC.
- **API:** Render `pocket-api-staging` live on `b9fc1bf3dc50aa881bcaf20cd3ebafa195a16424` (merged PR #338, event-based 90% held-profit intervals), deploy `dep-dc155kbl550s73detjvg`, successful at 02:27:26 UTC.
- **Separate research worker:** Render `pocket-research-staging` live on its existing independent release `32b01b1fa00b337c1310278e272f39e534e38b4b`; do not infer that it must match the API or processing worker revision.
- **Live strategy safety:** `paper_strategy_health` at 02:45:29 UTC showed **75 running regular Favorites bots**, **zero running in every other portfolio including Statistics-Backed Favorites**, and `real_orders_enabled=false`. Worker instance `655b7` was still emitting periodic logs.
- **Error/event check:** no error-level worker logs since 02:20 UTC, no error-level API logs since 02:27 UTC, and no server failure/restart events in those checked post-release windows. This does not establish all user-facing frontend routes or every delayed settlement.
- **Frontend/Gateway distinction:** The dedicated [Money Tree staging frontend workflow #44975765522](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975765522) passed deployment and confirmed all four published static assets exactly match API/frontend commit `b9fc1bf3`. The independent [generic staging gateway workflow #44975765565](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/44975765565) deployed successfully but failed its separate *unauthenticated `/` HTML* smoke check with HTTP 403 (expected 200); earlier releases also exhibited this failure. Do not mark that gateway boundary check passed, infer signed-in user access failed, or relax Cloudflare/security rules without evidence. The 403 is not a demonstrated regression from PR #338.
- **New work:** PR #340 (MT-033) was open, not merged or deployed, at the last GitHub check. It is owned by Chat 04; do not preempt it.
- **Ownership boundaries:** MT-018 owns Favorites hourly/discovery balancing, MT-030 owns low-fill and maker-cancel investigations, and MT-033 owns forward-only validation. Chat 02 performs deployment verification, runtime health checks and routing findings to their owners only. Do not change trading decisions, capital, settlement, history, live-order status, or inactive strategies as part of verification.

The earlier erroneous designation of this deployment conversation as **Chat 01** has been corrected to **Chat 02** to match the queue and the user's preexisting numbered conversations.

## Chat 2.1 — successor handoff from 2.0 (2026-11-22 UTC)

- Chat 2.1 is the new current conversation in stream 2, succeeding Chat 2.0. The exact intended ChatGPT sidebar title is `2.1` (numeric only); GitHub registration does not rename the sidebar.
- The existing MT-017 read-only Cloudflare CPU observability task transfers from 2.0 to 2.1 by explicit queue update. User already selected the GitHub Actions read-only analytics bridge and configured both required secrets. PRs #344, #345, #348, and #350 merged to `main`; the last documented Cloudflare run #44980816586 failed HTTP 400 at its viewer GraphQL preflight, not a Render deployment. PR #350 replaces viewer probe with documented `budget` field and adds sanitized token verification; inspect its postmerge CI and run one controlled `last_24h` manual audit only when authorized. Never disclose credential values or raw provider errors in public logs.
- Stream 2 also coordinates read-only Render processing/API deploy and safety verification. Other task ownership remains with 1.1 (MT-018), 3.1 (MT-035), 4.1 (MT-036), and distinct MT-019/MT-011 owners pending reconciliation. Regular High-Probability Favorites only; other strategies paused; live orders disabled. Check latest queue and runtime before any further action.
