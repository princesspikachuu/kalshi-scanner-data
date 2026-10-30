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
