# MT-017 — Cloudflare Workers CPU limit audit (2026-11-09)

Status: **partial code-path audit with synthetic CPU benchmark and a confirmed integrity constraint; actual Cloudflare invocation analytics unavailable**.

## Incident and scope

Cloudflare sent an alert at 2026-11-09 14:41:29 UTC, subject `[Action required] Workers CPU limit exceeded`. The email subject/snippet confirms CPU-limit exhaustion but does **not** name a Worker, affected route, invocation ID, CPU percentile or failed-request count. Full email body was inaccessible through the connected mail integration. There is no Cloudflare Analytics/Observability connector or Cloudflare API read access available in this audit session.

**Do not conflate** per-invocation CPU with total free-tier requests, elapsed network time, Render worker CPU, or Cloudflare's public 403 checks. Cloudflare specifically records `exceededCpu` for CPU termination and `exceededResources` for resource-limit invocation status. Production p50/p95/p99, error rates and route attribution are **not measured yet**.

## Services and routes

| Cloudflare Worker | Source | Deployment branch | Activity and risk |
|---|---|---|---|
| `pocket-analytics-staging` | `apps/gateway/index.mjs`; `infra/wrangler.staging.json` | `build/google-auth-foundation` | Authenticated API gateway for Money Tree dashboard. Static HTML/CSS/JS now bypasses Worker execution with `run_worker_first: ['/api/*','/live-paper']`; API proxies to Render, with byte limits, contract checks and security headers. |
| `kalshi-pocket-analytics` | `worker/src/index.js`; `wrangler.jsonc` | `main` | Legacy historical/research UI: Worker executes on `/api/*`, fetching historical reports and dispatching GitHub Actions. Large report uses `await result.text()` before returning a response; consider safe stream-through if analytics implicates this route. Static assets use Cloudflare Assets. |

The actual alert recipient Worker is **unknown**. The Worker name must be established from Cloudflare analytics rather than inferred from the service history.

## Confirmed code and deployment findings

1. **Staging static-asset CPU work existed prior to PR #155.** Previously `run_worker_first: true` invoked Worker JavaScript for every static request. PR #155 (`6346ee1d783439ff510cd51170e9006c7f24dac0`) narrowed Worker-first routes to `/api/*` plus `/live-paper`. Static responses receive equivalent CSP/no-store/security headers through `apps/web/_headers`. Cloudflare documents this asset-first behavior. This reduces Worker invocation count for static requests but does **not** establish an improvement in per-request API CPU.
2. **Redundant gateway JSON serialization was eliminated in PR #155.** Most authenticated API routes still parse response JSON to enforce their contract, but non-transformed responses now forward their original text instead of parsing and then serializing again. The largest authenticated dashboard workspace has a special **8 MiB byte-bounded stream** path when the API returns `x-pocket-workspace-contract: demo-v1`; it avoids parsing/restringifying at Cloudflare altogether.
3. **A tempting stream-copy optimization is unsafe.** `boundedResponse` copies each upstream chunk using `value.slice()` before enqueueing it. MT-017 tested bypassing that copy, but the existing regression test demonstrated that a mutable upstream buffer could be zeroed before the downstream consumer read it, corrupting dashboard bytes. **The copy was intentionally retained.** The benchmark documents its synthetic CPU cost, but integrity takes precedence. Any future lower-copy design requires provably immutable ownership/transfer semantics.
4. **Dashboard refreshes generate legitimate gateway calls:** `apps/web/shadow.mjs` has a 10-second refresh timer and loads workspace then events, potentially **12 sequential API invocations per minute per open tab** when both requests complete quickly. This is a code-derived maximum for the normal polling path, not an observed request rate. Reducing polling could reduce request volume, but won't fix a CPU-heavy *individual* invocation; do not silently lower monitoring freshness.
5. **Legacy research reports are relatively modest in repository size**: the largest audited report `backtests/LOSS_PREVENTION.json` is 90,707 bytes, with `EXECUTION_BY_BID_OFFSET.csv` 31,432 bytes and `AVERAGES_BY_TIME_AND_PRICE.csv` 10,834 bytes. File sizes are from `main` Git metadata, not observed Worker response payloads. `await result.text()` on each report is a possible minor CPU hotspot, not a proven incident cause.
6. **Post-deploy smoke check is not a CPU measurement.** Cloudflare's staging deployment step completed after PR #155, while an unauthenticated public check returned HTTP 403, as in previous deploys. That may reflect access policy and cannot be labeled a CPU failure without independent evidence.

## Verification and quantitative evidence

- Test coverage: `tests/test_demo_gateway.mjs` checks static asset configuration, authorization/proxy contract, stream-overflow cancellation and byte ownership under mutable upstream buffers. The attempted no-copy change **failed this existing test**, so it was reverted rather than weakening the test.
- Reproducible local measurement: `node tools/benchmark_gateway_cpu.mjs` prints Node process CPU consumption for 100 synthetic 2-MiB byte copies versus by-reference access, plus a 10-request 2-MiB stream through `proxyAuth`. Values are intentionally reported as **synthetic local CPU**, not Cloudflare usage. Results appear in the PR CI log.
- No Cloudflare request-level traces, CPU quantiles or `exceededCpu` series were accessible. **Before/after Cloudflare error reduction is not verified and must not be claimed.**
- No new paid service, fee, trading cap, retention change or reduced trading/monitoring cadence. MT-017 has not shipped a new runtime CPU reduction beyond previously merged PR #155; it has produced an audit and benchmark with an explicitly documented blocked optimization.

## Remaining required measurement (blocking completion)

In Cloudflare, for **each** Worker:
1. Workers & Pages → select Worker → Metrics → CPU Time per execution; record p50/p95/p99 before and after PR #155 and the MT-017 patch.
2. Metrics → Errors → Invocation Statuses; record `exceededResources` counts and rate by time; in request logs isolate `exceededCpu` (distinct from quota/429).
3. Use Workers Logs, tracing or the built-in CPU profiler to determine the failing route and volume. Avoid raw cookies, authentication tokens, user identifiers or full trade records in exported logs.
4. Compare over equal active hours and dashboard-session counts, including the same market conditions. Record invocation counts separately from per-invocation CPU.
5. Check both Worker names, including `kalshi-pocket-analytics` on `main`. If the issue is tied to `/api/demo/shadow/workspace`, verify that the upstream contract header is present (otherwise the 8-MiB fallback would parse at Cloudflare).
6. Confirm authenticated dashboard access on a logged-in device; the existing public 403 check cannot substitute for this.

Only close MT-017 when metrics confirm the responsible Worker and post-change CPU behavior. If the edge keeps exceeding its limit, open a separate follow-up for the proven route. A paid-plan recommendation requires a measured unavoidable CPU requirement, not merely an email alert.

## Sources
- Cloudflare Workers metrics and invocation statuses: https://developers.cloudflare.com/workers/observability/metrics-and-analytics/
- Asset-first routing: https://developers.cloudflare.com/workers/static-assets/binding/
- Static asset headers: https://developers.cloudflare.com/workers/static-assets/headers/
- CPU limit error diagnostics: https://developers.cloudflare.com/workers/platform/limits/
