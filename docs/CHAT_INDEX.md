# Money Tree — Numbered Chat Index

Use this file to assign short, distinctive names to Money Tree development conversations. The **chat number** is independent of the existing `MT-###` work-queue tasks, GitHub issue numbers, and PR numbers. Continue task ownership and scope rules in [WORK_QUEUE.md](../WORK_QUEUE.md); this index does not authorize overlapping work.

## Current chat register

| Chat number | Suggested ChatGPT sidebar title | Focus / related work | Status |
| --- | --- | --- | --- |
| **01** | **MT Chat 01 — Deployment & Trading Verification** | Continuation of `Deployment status update`; regular High-Probability Favorites only; read-only verification of Daily Weather/P&L fill-count release (MT-031, PR #337), 15-minute crypto discovery fix (MT-018, PR #335), and active MT-030 throughput investigation | Active as of 2026-11-21 18:33 Pacific |

**Next available chat number: 02.** For a genuinely new Money Tree conversation, select the next unused number, add a one-line entry here with its distinctive focus, and give the user that exact suggested sidebar title. Keep each new conversation's number stable even if the topic evolves. Do not automatically rename existing conversations or retroactively number earlier chats without the user's request.

## Continuation notes for Chat 01

- Staging paper-worker deployment `dep-dc152bflk1mc7383ilig` was live from commit `618370c663b3ead89389e8453a83fee16ba21bf3` at 2026-11-22 02:20:09 UTC (Saturday November 21 Pacific).
- By 02:33:41 UTC live logs showed **75 regular Favorites bots, 0 other running bots, real orders disabled**, and `favorites_collection_quality.unique_verified_1h=11` (7 crypto 15m, 4 weather), demonstrating verified recovery beyond mere order submissions.
- Live API released `b9fc1bf3dc50aa881bcaf20cd3ebafa195a16424` at 02:27:26 UTC, including PR #338 event-based uncertainty.
- Remaining `quote_unavailable` maker cancels and hourly market eligibility are **owned by existing in-progress MT-030 and MT-018**, respectively. Do not duplicate their code or change protective fee, book, settlement, or paper-only limits.
- For the next step, read `main:WORK_QUEUE.md` and current PRs before claiming unrelated in-scope work. Existing histories remain preserved.
