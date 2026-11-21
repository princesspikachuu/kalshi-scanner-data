# Kalshi Demo replacement — active implementation

Base: build/google-auth-foundation @ 1d49a4dea9c661687c5d33b9cc6526e8d62f3873.
User authorizes platform access, implementation and deployment; skip user-dependent blockers.
Keep all historical research datasets/artifacts/results and legacy replay records intact.

## Authoritative decisions recovered from Redesign Kalshi UI
- Bots / Research / Activity navigation; Refined Dark; Bots landing, account value first.
- Balance and always-visible Add demo funds; hidden-by-default equity chart; shared 24H/7D/30D metrics.
- Needs Attention and Running expanded, Paused collapsed; search/filter; Pause/Resume/Manage visible.
- Bulk pause/resume confirmation. One bot contains many price/time squares, shared settings.
- Automatically evaluate YES and NO, one direction per market; first-qualified priority, same-time expected return.
- Independent BID/ASK qualification and entry-price references. Fixed maker-only entry prices.
- Concurrent distinct same-direction entries; cancel invalid/expired bids; retry only after leave/re-entry.
- Separate entry accounting; combined exchange reconciliation; maker exits at best bid +1c, repriced until sold.
- Research/manual/off exits; block entries during exits. Percentage limits; optional daily net-realized cutoff off by default.
- Dedicated existing pocket-processing-staging worker for Demo; automatic verified recovery, valid-bid preservation.
- Reconcile manual trades; pause affected markets only on unclear ownership, protective exits continue where safe.
- Top in-app alerts for all; email critical trading/database/backup failures.
- Adjustable automatic archiving, searchable and restorable; proactive storage/cost alerts, database storage autoscaling.
- Demo orders/fills/cancels/exits/outcomes in historical charts, clearly distinguished and filterable.

## Limitations report that remains relevant
Separate opportunities, orders, fills and outcomes. One shared/versioned strategy. Expose audit evidence.
Bound memory, caches, database connections and result pages; stream archive reads; avoid tick persistence.
REST discovery/reconciliation only, one bounded WebSocket feed. No duplicate collection or historical re-download.
Old simulated paper trading is superseded, not evidence of exchange execution.

## Existing deployment
Workspace tea-dbfv1fl9el5s73bcuefg verified from prior checkpoint and matching services.
API srv-dbgcsb6c6qcc73f1j6n0; research srv-dbgcsb6c6qcc73f1j6lg;
processing srv-dbhcqr0473hc739kj4pg. All branch build/google-auth-foundation, auto-deploy off.
Gateway https://pocket-analytics-staging.ezrealrose831.workers.dev, GitHub Actions deployment on branch push.
Existing 9 migrations/immutable history privileges must stay compatible; use durable research_job namespace for new control data.

## Verified current API
Official docs use demo REST external-api.demo.kalshi.co, WebSocket external-api-ws.demo.kalshi.co.
Current order write API: POST /trade-api/v2/portfolio/events/orders (V2), DELETE same + /{order_id}.
Demo credentials separate from production. No documented faucet endpoint: fund via official demo site/test method.

## Status
Recovered decisions and production source. Isolated worktree build/demo-redesign. Implementation in progress.

## Build checkpoint — October 29, 2026, 10:59 p.m. Pacific
- Implemented Bots/Research/Activity, one multi-square bot builder, demo connection form, shared period controls, controls/archiving, exchange activity and research-side Demo execution summaries.
- Dedicated worker uses fixed Demo REST/WS destinations, V2 post-only orders, deterministic durable intent identifiers, per-entry accounting, manual-market isolation, restart reconciliation, valid-bid preservation, bounded watchlist/trigger cache/pools, and capped API pacing.
- Existing historical datasets/results/source artifacts/migrations untouched. Legacy replay records retained; new replays disabled after Demo cutover, because their worker is repurposed.
- Verified activity archives and Demo-control backups use existing private R2; these are explicitly distinct from full database/provider backups.
- Local: 425 Python tests: 276 passed, 149 PostgreSQL tests deferred to CI. 47 browser/gateway tests passed. Additional recovery regression tests also pass.
- Published source via GitHub connector (shell push has no credential). PR #56, initial commit 5b8286053ed925730fc32255a1a146b95a81da6b. Actual PostgreSQL CI run 41011172477 in progress.
- Render database currently 5GB, storage autoscaling false. Source Blueprint now true, but hosted MCP cannot update that field and browser has a sign-in wall. Per user instruction, do not interrupt for this; leave pending and continue.
- Separate Demo key is not configured; secure connection flow is built. Critical email SMTP connection is not configured. These require user-provided account access, so continue implementation/deployment independently.
- No Demo exchange order has been placed or verified. Do not claim actual execution success until a real Demo key and first order are confirmed.

## Integration findings
Actual PostgreSQL caught two defects before deployment: locale-dependent Unicode key range excluded bot rows, and activity serialization supplied duplicate keyword names. Fixed with the existing ASCII namespace bounds and explicit dictionary merging. All original database tests otherwise passed in the initial CI run.

## Deployed — October 29, 2026, 11:22 p.m. Pacific
- PR #56 merged to build/google-auth-foundation as c1c722d5bb452c7a8c3ebe0609a8e6df3c647a69.
- Final functional source aa54cb254fcac95f0d6ce0b6008449bc4458354f passed CI 41012543500: 428 Python cases including actual PostgreSQL, 47 browser/gateway cases, Blueprint validation.
- Follow-up operational-only receipt logging 4ab37471701f39f5dddaf04fcd1e2036a5687ef2 passed the 18 targeted engine/integrity tests.
- API live dep-dbi3ckn0bdec73dqd7d0 at 06:20:19Z; collector live dep-dbi3cmijnfac73cn1n0g; Demo worker live dep-dbi3efei0phs73cod6j0 at 06:21:35Z.
- Demo worker emitted demo_worker_ready (3 max DB connections, 100 watch limit), then demo_connection_required / trading_active=false. No Demo key or first exchange order has been verified.
- API/worker secret configuration merged with existing env; vault key generated privately and shared only with these two services. API DEMO_ENGINE_ENABLED=true; processing WORKER_ROLE=demo.
- Cloudflare gateway successfully uploaded and deployed version 4aef58b0-9ec5-4789-a08f-0fc258534804. Public Python/GitHub-runner HTTP checks received Cloudflare error 1010; do not remove protections or claim these checks passed. A normal live browser reached the new Money Tree sign-in page and loaded the Google sign-in button.
- Hosted pre-deploy audits verified all nine migrations, all twelve protected history tables, history_mutation=false and owns_history=false. Git diff confirms migrations/data/backtests untouched.
- Environment-update tool started deploys automatically; subsequently triggered API/processor deploys queued the same revision. Both queues drained successfully; no further deploys are needed.

## Remaining account-dependent setup / verification
1. User connects separate Kalshi Demo API key in Bots > Connect account. Validate first order, exchange IDs, partial fills, exit and recovery against that account before calling actual trading verified.
2. Critical-email SMTP connection is not configured. In-app alerts and email-readiness indicators are implemented; no email delivery has been verified.
3. Hosted Postgres storage autoscaling is still false (5GB). Blueprint requests true, but MCP cannot update that field and browser sign-in is needed. Full provider backup/restore policy is not verified. Do not conflate verified-in-code Demo-control backups with full PostgreSQL backups.
4. Signed-in UI review and live control-backup receipt inspection remain pending an owner session. Backend service readiness and runtime namespace/schema tests passed.
5. Existing immutable historical data is preserved. New legacy replays/simulated-live starts are disabled; historical replay results remain readable.

No permission questions were raised. User directed skipping assistance-dependent work; continue independently when access becomes available.


## Verified Demo execution — October 30, 2026, 10:05 a.m. Pacific
This section supersedes earlier connection/first-order setup notes.
- User connected a valid Demo key and saw funded cash. Ed25519/RSA support is deployed. Four running bots contain 53 conditions.
- Root cause of zero accepted orders: API returned HTTP 404, code `insufficient_shard_balance`. Aggregate account cash was displayed correctly, but crypto markets live on shard 2 and the original engine did not move collateral from shard 0.
- Fixed with on-demand primary-account, event-contract-only transfers of existing Demo funds. Authoritative market `exchange_index` is retained. Each transfer has a durable intent and unique client ID before POST; ambiguous responses are reconciled by transfer history without retrying POST; completion and destination balances are verified. Numbered subaccounts are excluded, resting-order collateral is conservatively retained, and prefunding is bounded by remaining bot budget. The transfer does not add funds or alter spending limits.
- Existing definitively rejected entry attempts are released once for recovery. Accepted, open and uncertain orders are never released. Funding state joins Demo control backups; no migration or historical evidence mutation.
- Fixed cancellation shard routing by market ticker. Worker handoff waits for its exclusive lock rather than restart cycling. Existing Render shutdown delay can keep the previous instance active for about two minutes; avoid redundant redeploys.
- Per-bot entry diagnostics show discovered Demo markets, fresh quotes, matches and constraints. Safe exchange codes/statuses are captured without raw provider responses or secrets.
- Functional source b48381872282652bccdc5ec080fedfe3a4627228. Worker deploy dep-dbiconff3r2c73cm78vg is live. Full validation run 41094467163 passed. Local Python: 441 cases, 292 passed and 149 database-dependent cases skipped; 31 targeted engine/funding cases passed. Frontend: 52 cases passed.
- Live receipt 17:05:15.349506125Z: `demo_shard_funded`, source 0, destination 2, amount_cents 21000. Immediately afterward at 17:05:15.366922748Z, `demo_order_accepted`: maker entry, exchange_index 2, remaining 10.0, filled 0.0. This verifies a resting maker bid, not a fill. Protective exit/partial-fill recovery still require live evidence.
- Frontend diagnostics gateway deployment succeeded in workflow 41093066513; its credential-free public smoke check still encounters the existing Cloudflare boundary. No API or collector redeploy was necessary for this worker fix.
- Critical email, hosted storage autoscaling and full provider backup verification remain as described above. Preserve all existing history.


## Weather and sports audit — October 30, 2026, around 10:25 a.m. Pacific
- Bounded public Demo reads checked all eight configured hourly-weather series (both CH/CHS variants), seven daily-weather series and seven sports series for open markets closing within 24 hours. All hourly and sports responses were empty. All seven daily-weather series returned active markets on shard 0. Do not generalize these results to production or to every possible Demo sports series.
- Current worker diagnostics list weather, sports, btc and crypto running conditions; no weather_daily conditions are running. Do not invent daily trading windows or add conditions without user selection.
- Added routing regression coverage for both hourly-weather variants, daily weather, football (shard 0), basketball/tennis (shard 3), and existing-Demo-funds transfers from crypto shard 2 back to default shard 0 or sports shard 3.
- Fixed discovery fairness: existing-position refreshes used the series counter and could permanently skip series slots when the series count was divisible by five. Refresh and series rotation now have independent counters, with no increase in discovery request frequency.
- Local Python suite: 444 cases, 295 passed, 149 database-dependent cases skipped. Targeted engine/funding suite: 34 passed.
- Follow-up user report: crypto exits consistently occur at 2 cents. Investigate after finishing this deployment; do not assume a price limit or change configured exit thresholds without evidence.
