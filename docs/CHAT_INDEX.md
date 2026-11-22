# Money Tree — Chat Stream/Round Register

**BOOTSTRAP BEFORE SELF-IDENTIFICATION:** If the user's first message is a bare chat ID such as `1.2`, that exact string is the intended chat title. Before the assistant's first substantive reply or any self-naming, fetch this document and `main:WORK_QUEUE.md` from GitHub. Do not add a topic or prefix to the title. **READ THIS FIRST when creating, continuing, or handing off a Money Tree conversation.** The repository's **authoritative scope and task-claim file** is [`main:WORK_QUEUE.md`](../WORK_QUEUE.md) and this [`main:docs/CHAT_INDEX.md`](./CHAT_INDEX.md) is the **stream/round identifier register**. Always fetch both files from the `main` branch of `princesspikachuu/kalshi-scanner-data` at the beginning of a new conversation, before accepting task ownership or editing code. The queue's **"Chat naming and handoff rule — STREAM.ROUND"** section is authoritative if these two files ever disagree. Work branches may be based on `build/google-auth-foundation`; naming and ownership still live on `main`.

## Rule: `<stream>.<round>`, NOT a decimal number

- **Stream** = one of the four user-designated parallel work lanes (`1`, `2`, `3`, `4`). **Round** = successive ChatGPT *conversation threads* within that lane, starting at `0`. Continue within one thread without advancing the round. Creating the next handoff conversation increments that lane's suffix.
- **Current round:** `1.1`, `2.1`, `3.1`, `4.1`. **Next conversation in each lane:** `1.2`, `2.2`, `3.2`, `4.2`. Independent progress: one lane can move to `1.2` while the others remain at `2.0`, `3.0`, `4.0`.
- **After nine rounds** suffixes continue `1.9 → 1.10 → 1.11 → 1.12` (same rule for 2–4). **Treat identifiers as exact text labels, never floating-point values.** `1.10` must never be collapsed to `1.1`.
- **Required ChatGPT title:** Exactly the **number only**, such as `1.0`, `1.1`, `2.1`, or `1.10`. No `Money Tree — Chat` prefix and **no topic suffix**. Topics may change and are retained only as internal tracking metadata. The assistant cannot directly rename ChatGPT sidebar chats.
- **Legacy aliases:** Past references to `Chat 01`, `Chat 02`, `Chat 03`, `Chat 04` denote round-zero Chats `1.0`, `2.0`, `3.0`, `4.0`; do **not** rewrite historic citations, merge history, or task records just to relabel them. Chat IDs never equal `MT-###` IDs or PR/issue numbers.

## Current active conversation register

| ID | Historical workstream context (NOT a chat title) | Existing focus / claims | State |
| --- | --- | --- | --- |
| **1.0** | Discovery Optimization | Prior round: PR #314, #335, #341 and #343 discovery work; MT-018/MT-034 handoff | **Succeeded by 1.1** |
| **1.1** | Discovery Optimization | Successor to 1.0; MT-018 discovery verification and weekday finance listing gates, MT-034 release verification; coordinate with Chat 3 MT-035 and Chat 2 deployment | **Active — registered 2026-11-22 UTC** |
| **2.0** | Deployment Verification | Predecessor to 2.1; runtime health, memory audit, and MT-017 Cloudflare read-only observability bridge PRs #344/#345/#348/#350 | **Succeeded by 2.1** |
| **2.1** | Deployment Verification | Successor to 2.0; continue MT-017 Cloudflare CPU read-only diagnostic and verify GitHub Actions/Render safety without taking other streams' code | **Active — registered 2026-11-22 UTC** |
| **3.0** | Trading Throughput | Previous round: finance-hourly MT-035, diagnostics PR #342, MT-030 shared inquiry; handoff to 3.1 | **Succeeded by 3.1** |
| **3.1** | Trading Throughput | Successor to 3.0; owner of MT-035 regular Favorites finance-hourly read-only funnel, weekday validation Issue #339; scanner owned by 1.1; MT-030 broad ownership requires separate claim | **Active — registered 2026-11-22 UTC** |
| **4.0** | Profitability Validation | MT-033 merged, deployed and verified; predecessor to 4.1 | **Succeeded by 4.1** |
| **4.1** | Profitability Validation | Successor to 4.0; MT-033 DONE; MT-036 regular Favorites forward profitability dashboard PR #349 IN PROGRESS, owned by 4.1; awaiting exact-head CI / safe release | **Active — registered 2026-11-22 UTC** |

**Next successor conversation IDs (reserved as *planned*, not yet active or claimed): `1.2`, `2.2`, `3.2`, `4.2`.** There is no blanket next-new-chat number `05` under this four-stream plan. Do not create a fifth stream without user instruction.

## Mandatory startup: the user's numeric ID is the entire chat title

**2026-11-22 user clarification (supersedes every older descriptive-title instruction in this repository):** The user opens a new chat by sending **only its assigned ID**, e.g. `1.2`. That bare number is the **exact intended title** of this ChatGPT conversation. The subject/topic can change and must **not** appear in the title. Do not ask the user to change their first message or send a longer name.

**Assistant startup sequence, required before self-identification or substantive reply:**

1. Treat the first user message matching `<stream>.<round>` (for streams 1–4, round a nonnegative integer string) as the exact chat ID and intended sidebar title. Do **not** treat it as a decimal number, version to round, arithmetic expression, or request to guess a topic. Preserve `1.10` distinct from `1.1`.
2. **Before naming yourself, selecting work, or answering the first message**, fetch the current `main:WORK_QUEUE.md` and `main:docs/CHAT_INDEX.md` from `princesspikachuu/kalshi-scanner-data` through the connected GitHub tools. The repo files are *not* automatically read by a new ChatGPT conversation; the project's own instructions must provide this startup bootstrap.
3. Verify whether that ID is registered, its predecessor and continuation lane, prior handoff, task ownership, and current project-wide scope. Register the new thread or reconcile collisions before taking tasks; keep topic/focus **only in GitHub metadata**.
4. The first line of the assistant's first substantive response must be the **ID alone**, e.g. `1.2`, with no Markdown prefix/header, topic, explanatory words, or `Money Tree — Chat` prefix. Then summarize continued work without claiming the sidebar was renamed.
5. The ChatGPT interface generates sidebar titles independently. The assistant cannot set, see, or guarantee them through GitHub or a reply. If the actual sidebar title is not exactly the numeric ID, the user may manually rename it. Do not increment the round for a title correction.

**Where the bootstrap must live:** Put the short startup rule in the **Money Tree ChatGPT Project's instructions**, since an instruction found only inside GitHub cannot tell a new chat to fetch GitHub before first reading it. The GitHub files are the detailed, authoritative follow-on rules.

## New successor thread registration and task ownership

1. Fetch `main:WORK_QUEUE.md` and this `main:docs/CHAT_INDEX.md` to learn the exact current stream/round. Identify the predecessor stream and its most recent registered round. Read that predecessor's task handoff and live PR state before making claims.
2. When opening a **new** thread in an existing stream, select the next unused **literal** `stream.round` string; append a registration row under the exact numeric ID, with descriptive topic **as internal metadata only**, predecessor ID and actual status. Use the latest file SHA to atomically update this index; on a collision, refresh and pick the next available suffix rather than duplicating a label.
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
