# Money Tree — Numbered Chat Index

The **authoritative chat-number and task-ownership register** is [WORK_QUEUE.md](../WORK_QUEUE.md) on `main`. This index mirrors it for convenient navigation. Chat numbers are separate from `MT-###` task IDs, GitHub PR numbers, and issue numbers. Every development conversation should suggest its number and title to the user; ChatGPT cannot automatically rename the sidebar conversation.

## Current chat register

| Chat | Suggested ChatGPT sidebar title | Focus / ownership | Status |
| --- | --- | --- | --- |
| **01** | **Money Tree — Chat 01: Discovery Optimization** | PR #314 discovery/pagination follow-up; existing implementation owner | Assigned to separate conversation |
| **02** | **Money Tree — Chat 02: Deployment Verification** | **This conversation**: verify Render/GitHub releases, deployed revisions, health, and paper-only safeguards. Read-only coordination; do not take MT-018 or MT-030 application-code ownership | Active, Nov 21, 2026 Pacific |
| **03** | **Money Tree — Chat 03: Trading Throughput** | Low-frequency / finance and regular Favorites throughput follow-up; use shared task claims | Assigned to separate conversation |
| **04** | **Money Tree — Chat 04: Forward-only Favorites Validation** | MT-033 forward-only frozen-cohort profitability validation; PR #340 in development | Assigned to separate conversation |

**Next currently unassigned number: 05.** Always re-read the latest `main:WORK_QUEUE.md` before claiming a new chat ID. Keep existing numbers stable, and correct accidental duplicate labels rather than starting duplicate implementation.

## Chat 02 — Verified deployment and health handoff

**Checked:** 2026-11-22 approximately 02:45 UTC (Saturday, Nov 21 Pacific). These are latest observed deployment and sampled health facts, not a guarantee of future uptime.

- **Processing worker:** Render `pocket-processing-staging` live on `618370c663b3ead89389e8453a83fee16ba21bf3` (merged PR #335, regular Favorites 15-minute discovery), deploy `dep-dc152bflk1mc7383ilig`, successful at 02:20:09 UTC.
- **API:** Render `pocket-api-staging` live on `b9fc1bf3dc50aa881bcaf20cd3ebafa195a16424` (merged PR #338, event-based 90% held-profit intervals), deploy `dep-dc155kbl550s73detjvg`, successful at 02:27:26 UTC.
- **Separate research worker:** Render `pocket-research-staging` live on its existing independent release `32b01b1fa00b337c1310278e272f39e534e38b4b`; do not infer that it must match the API or processing worker revision.
- **Live strategy safety:** `paper_strategy_health` at 02:45:29 UTC showed **75 running regular Favorites bots**, **zero running in every other portfolio including Statistics-Backed Favorites**, and `real_orders_enabled=false`. Worker instance `655b7` was still emitting periodic logs.
- **Error/event check:** no error-level worker logs since 02:20 UTC, no error-level API logs since 02:27 UTC, and no server failure/restart events in those checked post-release windows. This does not establish all user-facing frontend routes or every delayed settlement.
- **New work:** PR #340 (MT-033) was open, not merged or deployed, at the last GitHub check. It is owned by Chat 04; do not preempt it.
- **Ownership boundaries:** MT-018 owns Favorites hourly/discovery balancing, MT-030 owns low-fill and maker-cancel investigations, and MT-033 owns forward-only validation. Chat 02 performs deployment verification, runtime health checks and routing findings to their owners only. Do not change trading decisions, capital, settlement, history, live-order status, or inactive strategies as part of verification.

The earlier erroneous designation of this deployment conversation as **Chat 01** has been corrected to **Chat 02** to match the queue and the user's preexisting numbered conversations.
