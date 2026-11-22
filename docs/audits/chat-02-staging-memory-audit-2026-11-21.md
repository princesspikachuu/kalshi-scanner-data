# Money Tree — Chat 02: Staging memory audit

**Audit date:** Saturday, November 21, 2026, Pacific (UTC observations through 2026-11-22 02:51 UTC).
**Scope:** Read-only Render resource metrics, capacity logs and failure events for the *regular High-Probability Favorites* paper-trading staging stack. No code, trading, cash, strategy, backups, histories, deployment, or Render configuration was modified.
**Existing owner:** MT-011 systems efficiency and memory optimization (IN PROGRESS). Chat 02 owns only deployment/read-only verification, not the implementation.

## Snapshot

At **2026-11-22 02:50 UTC** (18:50 Pacific), Render 300-second samples show:

| Service | Latest memory | Memory limit | Usage | CPU |
| --- | ---: | ---: | ---: | ---: |
| `pocket-processing-staging`, instance `655b7` | 980,836,350 B (~0.913 GiB) | 2 GiB | **45.7%** | ~0.248 core |
| `pocket-api-staging`, instance `kj97v` | 205,553,660 B (~0.191 GiB) | 0.5 GiB | **38.3%** | ~0.124 core |
| `pocket-research-staging`, instance `rtndb` | 84,152,320 B (~0.078 GiB) | 0.5 GiB | **15.7%** | ~0.003 core |

CPU readings approximate Render per-core CPU utilization and are not host-wide CPU percentages. Worker instance count was 1 at each of the 5-minute metric points in the sampled 24+ hours; API and research likewise reported 1 instance each.

### Current processing worker after PR #335

The processing service is live on **`618370c663b3ead89389e8453a83fee16ba21bf3`**; deploy `dep-dc152bflk1mc7383ilig` succeeded at 2026-11-22 02:20:09 UTC. New active instance suffix: `655b7`.

| Time UTC, Nov 22 | Memory bytes | Approx GiB |
| --- | ---: | ---: |
| 02:25 | 747,524,100 | 0.696 |
| 02:30 | 962,641,900 | 0.896 |
| 02:35 | 985,358,340 | 0.918 |
| 02:40 | 998,662,140 | 0.930 |
| 02:45 | 1,000,153,100 | 0.931 |
| 02:50 | 980,836,350 | 0.913 |

This is **startup ramp followed by a short apparent plateau**, not proof that memory cannot grow later. At 02:51:08 UTC, application `paper_monitoring_capacity` reported `rss_bytes=1,011,077,120` (47.1% of 2 GiB), `admitting=true`, `telemetry_fresh=true`, `backlog=0`, p95 queue lag ~15.9 ms, measured market caps removed and `real_orders_enabled=false`; it reported 14 subscribed markets, 3 entry candidates and 11 positions/exit markets. This independent application RSS reading is close to Render's container metric, but the two measure different moments/sources.

At 02:51:39 UTC, `paper_strategy_health` confirms **75 running regular Favorites bots**, zero enabled bots in every other portfolio (including Statistics-Backed Favorites) and real exchange orders disabled. This does **not** attribute RAM to a specific portfolio: paused historical state may remain loaded, and no component/heap allocation profile was taken.

## Confirmed historical OOM kills

Render `list_events` returned **five server_failed events** with explicit `reason.oomKilled.memoryLimit = "2Gi"`:

- 2026-11-21 **06:03:43.95179 UTC** — instance `qvhsx`
- 2026-11-21 **06:54:20.104822 UTC** — instance `2v5zw`
- 2026-11-21 **07:00:35.675174 UTC** — instance `2v5zw`
- 2026-11-21 **07:06:23.699963 UTC** — instance `2v5zw`
- 2026-11-21 **07:14:30.740523 UTC** — instance `2v5zw`

These were **Friday, Nov 20 at approximately 22:03–23:14 Pacific**, across two instance IDs; repeated failures on `2v5zw` are individual events rather than evidence of four different machines. Highest observed 5-minute sample from the last ~25 hours: **2,090,360,800 B (~1.947 GiB, 97.3% of 2 GiB)** on `qvhsx`. Five-minute metrics cannot capture the exact instantaneous peak at termination.

**No OOM/restart/failure events** were returned for the processing worker after the 2026-11-22 02:20:09 UTC rollout, nor for the API/research services during the 2026-11-21 02:00 UTC onward checked window. This is limited to Render event coverage and does not prove future stability.

## Interpretation and handoff to MT-011 owner

1. **Historical memory instability is confirmed and serious.** The old worker exhausted its 2-GiB allocation multiple times. Do not dismiss prior OOMs merely because a newly deployed process currently looks healthy.
2. **No evidence of current memory-gated Favorites trading.** Current telemetry reports ~47% RSS utilization, admission allowed, zero queue backlog and low p95 lag. Do not disable the admission/75% resource safety guard or increase server resources without validating a present need.
3. **The present ~0.9-GiB baseline remains unexplained by resource metrics.** These metrics expose process/container totals, not per-bot, Python heap, historical event cache, JSON snapshot, or retained paused-strategy memory. The existing MT-011 owner may assess component-aware profiling and long-run allocation curves without altering canonical research history.
4. **Check the same worker instance over several uninterrupted hours.** A stable 20–30-minute post-restart plateau is encouraging but insufficient for a long-run memory leak conclusion. Escalate if steady-state RSS consistently rises toward the existing measured-memory admission guard (~75%, 1.5 GiB) or if any further OOM event is recorded; distinguish organic load from deployment restarts.
5. **No changes to other portfolios or live trading.** Keep Statistics-Backed Favorites and all unrelated portfolios paused, historical state intact, one active paper worker, and `real_orders_enabled=false`. Separate MT-018/MT-030 own discovery/trading throughput.

**Evidence endpoints:** Render metrics `get_metrics` for services `srv-dbhcqr0473hc739kj4pg`, `srv-dbgcsb6c6qcc73f1j6n0`, `srv-dbgcsb6c6qcc73f1j6lg` at 300-second resolution; Render processing-worker `list_events` with `server_failed`; application `paper_monitoring_capacity` and `paper_strategy_health` logs; the shared task queue `main:WORK_QUEUE.md`. No private credentials, IDs of traded markets, or historical evidence were exported.
