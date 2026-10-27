# Pocket Analytics — remaining app build plan

**Draft for review. Planning only: no application deployment, account provisioning, paid subscription, database migration, or live trading is authorized by this document.**

This expands [the product plan](../APP_PLAN.md). Existing source code remains unchanged by this planning branch.

## 1. Outcome and boundaries

Build an app that researches and runs enabled short-horizon trading strategies automatically, keeps operating when the phone/browser is closed, and explains its decisions. The workflow is research → strategy testing → forward paper trading → live automation → performance review.

Retain markets whose underlying outcomes last one day or less: hourly/daily weather, short-duration crypto, sports game/match winners, and eligible daily financial outcomes. Classify eligibility from contract rules and event timing. A settlement delay alone does not turn a daily outcome into a longer-horizon bet. Long-horizon outcomes remain excluded.

The first release serves one owner and one trading account. Once a strategy is enabled in a trading mode, routine qualifying orders run without individual confirmation. Automatic activation of newly discovered strategies or automatic changes to live parameters remains undecided; proposed default is to surface those changes for review.

Loss prevention means reducing downside when selling is supported by evidence. Profit-taking targets are outside this feature. Do not replace weak evidence with a guessed higher stop or present tiny salvage as prevention of most of a loss. A maximum acceptable realized loss is a separate owner-defined risk preference, not something a profitability optimizer can infer automatically.

## 2. Current foundation and remaining gaps

| Area | Already present | Remaining work |
| --- | --- | --- |
| Research dashboard | Categories, time-by-price grid, latest/cumulative views, remembered selections, collection controls | Date filtering, previous-run browser, stable data snapshots, authenticated owner controls |
| Collection | Batched recent candles, paced/bounded requests, archive lookback, per-run staging, new minute-close bid paths | Database ingestion, resumable jobs, incremental sync, coverage inventory, reusable archive storage |
| Entry testing | Quoted maker-entry simulations and optional trade-through evidence | Shared strategy model, actual fee rules, independent validation and realistic execution assumptions |
| Loss prevention | Downside-threshold study and partial overlay in the main table | Better path/depth evidence, decision-time conditioning, meaningful risk context and executable maker exits |
| Backend | Cloudflare routes for saved data and GitHub collection dispatch | Private API, database, job management, streaming updates and account reconciliation |
| Automation | No live order placement in the current app | Independent engine, forward paper mode, controlled live mode and operational monitoring |

The current research output is not evidence that an enabled strategy will fill or be profitable live. Preserve its source, assumptions, fees and model version when importing it.

## 3. Target structure

| Component | Responsibility | Proposed implementation |
| --- | --- | --- |
| Phone/browser app | Navigation, research, strategy setup, orders, performance, controls | React + TypeScript + Vite, served by Cloudflare |
| Private API | Authentication, queries, settings, strategy versions and job requests | Python + FastAPI on Render |
| Trading engine | Live subscriptions, current market state, strategy evaluation, order/position management | Separate continuously running Python service on Render |
| Research worker | Historical ingestion, validation, backtests and report generation | Separate Python service/jobs on Render |
| Durable database | Strategies, observations, jobs, run membership, order intents, fills and audit events | Managed PostgreSQL |
| Raw archives | Compressed provider responses, price paths and reproducible export artifacts | Cloudflare R2, indexed from PostgreSQL |
| Build pipeline | Source control, tests, reviewed changes and release artifacts | GitHub; deployment behavior agreed before implementation releases |

Keep API, engine and database in the same hosting region initially. Select the region after measuring connectivity to the exchange; do not promise subsecond execution based on hosting location alone. Shared typed API contracts connect the interface to the Python services.

Live evaluation uses an in-memory market view. Batch noncritical quote persistence in the background. **Persist an order intent durably before transmitting an order**; order/position correctness takes priority over shaving milliseconds from that step. Research work must not occupy the engine process or its critical database connections.

Start with PostgreSQL-backed research jobs and process-local live state. Add a separate message broker/cache only if load measurements justify it. The first architecture should not require Kubernetes, multiple database systems, or a paid AI service for each trading decision.

## 4. Data and SQL model

Store provider identifiers and original timestamps alongside normalized fields. Use explicit dollar-denominated price/amount fields with exact decimal types, timezone-aware UTC timestamps, and explicit quantity units. Convert to cents only at the presentation boundary. Verify unit conversions with saved provider examples before importing data.

| Data group | Core records | Important rules |
| --- | --- | --- |
| Contract catalog | Series, events, markets, contract-rule versions | Separate outcome duration, trading close, scheduled event end, actual event end, and settlement time |
| Raw inputs | Archive objects, provider responses, checksums, ingestion versions | Immutable object references; do not overwrite the evidence behind a published result |
| Market history | Quotes/candles, trades, snapshots/deltas, settlements | Distinguish observation time from ingestion time; store resolution, gaps and revisions |
| Collections | Jobs, runs, settings, per-run membership and coverage | A deduplicated observation can belong to several runs; latest/previous runs must remain reconstructable |
| Strategy records | Strategies, immutable versions, entry/exit/risk configurations | Every simulation and order references the exact version that produced it |
| Research outputs | Backtests, model versions, cohort memberships, candidates, validation results | Preserve both full holding baseline and evaluated subset; never silently substitute populations |
| Execution | Order intents, submissions, exchange orders, fills, positions and reconciliations | Stable client order IDs, unique exchange identifiers, transactional state transitions |
| Operations | Engine leases, health, decisions, errors and audit events | Record why an order was placed/skipped and which data/rules were used |

Use unique keys for provider events/trades/candles so retries do not duplicate records. Historical quote revisions produce a traceable revision rather than silently changing an old backtest. Cache aggregated reports with their dataset/model versions.

Publish a dataset manifest/version atomically. All dashboard queries for a view use that version, so counts, coverage and P/L cannot come from different collection commits. Preserve the identity of each category's latest run and the complete membership of previous runs; runner-local staging is not the permanent record.

## 5. Data collection and research workflow

1. Catalog eligible markets, including rule/settlement-source references and reliable category metadata.
2. Look up stored coverage for the requested category and UTC dates.
3. Fetch missing/revised data with shared provider rate budgets, bounded concurrency and backoff.
4. Persist inputs and checkpoints before advancing the job cursor. Restart a failed job without repeating completed work.
5. Validate units, timestamps, duplicates and path gaps. Publish no incomplete run as a completed result.
6. Create explicit run membership, build versioned summaries, and publish the new dataset version.

Expose queued/running/paused/failed/completed/cancelled states, current category/date, progress, retries, added observations, and errors. Cancelling a research job preserves completed stored inputs without calling the partial output a complete collection.

Retain the current bounded collection controls while migrating. Older dates are permitted only where the provider has coverage; the app must not imply ten years of every contract family. Historical download rate and archive depth differ from live-stream speed.

The research screen should include:

- Latest collection, all historical data, and an individual previous collection.
- UTC date range, category/family/underlying filters, price bands and entry windows.
- Original holding P/L, optional loss-prevention overlay, sample counts, exact data coverage, costs, and model version.
- A cell detail with the full-sample result, paired covered-subset comparison, supported/candidate exit prices and implied percentage loss.
- Exportable results with the same filters, scope and assumptions as the screen.

## 6. Strategy definition and testing

A saved strategy version contains eligible categories/contract families, outcome-duration restrictions, entry-price range, entry clock/window, maker bid adjustment, quantity/budget, order lifetime, replace/cancel behavior, exit policy, fee model, and risk limits. Define the clock explicitly: time to trading close is not automatically time to sporting-event completion or settlement.

Use the same strategy evaluator in historical replay, forward paper trading and live execution. Execution adapters differ; the rule definitions do not. Freeze the strategy/data versions for each evaluation.

Evaluate expected net outcome per attempted order as well as per estimated fill. Distinguish no order, unfilled order, partial fill, entry fill, early exit and settlement. Model fees from the actual applicable schedule/version when available; fixed stresses remain labeled scenarios. Do not infer fill probability from quoted prices or treat at-price trades as confirmed maker fills.

For loss prevention, compare actual available exit quotes with holding for the same positions. Select the highest expected-net-improvement training candidate before applying confidence checks, validate later, and do not fall back to tiny salvage merely because its variance is low. Report unsupported thresholds explicitly. Capture remaining time at the exit decision and later recoveries, not just entry time and eventual losers. Require stronger data before claiming sub-minute performance.

**Maker-only execution is the baseline.** A passive maker exit needs its own fill/wait/expiry model; observing a bid does not prove that a maker sale would execute. No silent conversion to a taker sale is part of this plan. Whether urgent loss exits may cross the spread requires a separate explicit product decision and cost model.

Measure performance by independent event/day groups, including correlated weather strikes and repeated observations. Use later periods and forward paper data for validation; repeated optimization against the same validation period must not become a fresh out-of-sample claim. Show bad periods and uncertainty alongside favorable averages.

## 7. Continuous engine and order lifecycle

Market feed → validate/update current state → identify affected strategies → evaluate rules → check exposure/available funds → persist intent → submit → reconcile orders/fills → manage position → exit or settle → record outcome.

Requirements before any live activation:

- One active order-submitting engine per account, with a durable leadership mechanism. Loss of authoritative state/leadership stops new submissions.
- Validate a fresh snapshot after stream reconnection or sequence gaps before evaluating entries. Maintain periodic exchange reconciliation alongside streams.
- Stable client order IDs and reconciliation of timed-out submissions before retries. Restart and deployment overlap must not place duplicate orders.
- Reserve funds/exposure for pending as well as filled orders. Handle partial fills, cancel/replace races, expiry, settlement, and rejected orders.
- Keep entry permissions separate from existing-position management; losing a research worker must not stop the engine.
- Keep credentials on the backend, out of browser bundles, URLs and decision logs. Use separate paper/demo and live configurations.
- Record relevant quote timestamps, signal/reason, strategy version, risk checks, submission timing, exchange response and final reconciliation.

The current dashboard has no order-placement capability. This is design work for a future engine, not activation of one.

## 8. Controls and failure behavior

| Control or condition | Planned behavior |
| --- | --- |
| Pause new entries | Stop new buys and cancel pending entry orders as configured; continue managing existing positions |
| Stop engine orders | Stop further submissions and attempt cancellation of open orders; clearly show that filled positions remain exposed |
| Uncertain exchange response | Reconcile first; do not blindly resend |
| Stale/gapped market data | Stop new entries, refresh/reconcile state, show affected markets |
| Database unavailable | Stop creating new order intents; show the recovery/reconciliation state |
| Research failed | Preserve the current published dataset and strategy version; trading must not wait for it |
| Restart/deployment | Reconcile positions/open orders before resuming enabled strategies |
| Repeated errors or configured limits reached | Pause according to saved policy, explain why, notify the owner |

Owner-configured limits include position/order size, committed funds, pending-order exposure, per-event/category/strategy/account exposure, and applicable loss limits. Do not invent numeric limits or order-liquidation behavior from the research optimizer. A stop threshold cannot guarantee a maximum loss when orders do not fill or prices gap.

## 9. App screens and everyday use

| Screen | First useful release |
| --- | --- |
| Home | Engine/feed/account state, mode, committed/available funds, open exposure, current jobs and important events |
| Strategies | Plain-language rule editor, immutable versions, supporting evidence, paper/live state, enable/pause controls |
| Research | Existing matrix plus exact dates, previous runs, coverage inventory, candidate comparisons and resumable job controls |
| Trading | Pending/open/completed orders, partial fills, positions, intended exits, and clear decision reasons |
| Performance | Separate historical, paper and actual results; fees, drawdowns, non-fills, recovery/exit costs, category/strategy breakdowns |
| Activity/settings | Searchable decisions/errors, alerts, connections, risk limits, authentication and persistent view preferences |

Preserve mobile usability, named navigation, selected views and filters, and clearly visible mode/connection state. Show operational information that helps a decision; keep debugging internals in the activity/details views. Use authenticated owner sessions before adding private account data or execution controls; the present public research endpoints must never become public trading controls.

## 10. Speed and observability

Proposed targets, to be measured rather than promised:

| Measurement | Initial target and qualification |
| --- | --- |
| Strategy processing | p95 under 100 ms from an accepted feed event to a decision, on the measured subscribed universe |
| Eligible order dispatch | p95 under one second from receiving the relevant update to request transmission, when risk checks permit and provider budgets allow |
| App status propagation | Most order/position changes visible within two seconds of backend receipt |
| Research interference | No material degradation of engine latency during a representative full research workload |
| Restart correctness | No duplicate orders or unreconciled exposure in replayed restart/reconnect tests |

Measure feed-event age, queue depth, processing/submit/ack timing, reconnects, rejects, gaps, database latency and reconciliation differences separately. These targets do not guarantee exchange acknowledgment, fill timing, or profitability. Benchmark a bounded market universe before expanding subscriptions.

## 11. Incremental delivery and acceptance gates

| Phase | Deliverable | Completion evidence |
| --- | --- | --- |
| A. Data contracts | Units, SQL schema, collection/run membership, strategy and API schemas | Existing CSV/path inputs import without altering counts or historical holding P/L; invalid units/duplicates rejected |
| B. Durable research | PostgreSQL/R2 ingestion, job checkpoints, coherent dataset versions | Retry/restart is idempotent; latest/cumulative/previous-run results are reproducible; incomplete jobs do not overwrite published data |
| C. Structured app | React screens and private FastAPI, keeping the existing app usable during migration | Mobile core flows work; saved view state persists; no cross-run data mixing; private data requires owner authentication |
| D. Live recorder | Feed client, snapshot/gap recovery, account read reconciliation and archived live evidence | Forced disconnects recover correctly; stale data is visible; research load does not stall the recorder |
| E. Shared strategy + paper engine | Rule evaluation, order simulation, position/risk accounting, loss-exit comparison | No lookahead; deterministic replay; duplicate/restart/cancel/partial-fill cases pass; paper results separate from historical estimates |
| F. Controlled live mode | Authenticated execution adapter and owner controls | Applicable account/market constraints verified, risk limits explicitly configured, reconciliation/failure controls demonstrated, and live activation explicitly selected |
| G. Expansion | Broader categories, tuning tools and optional automatic strategy changes | Each extension has adequate coverage/validation and measured capacity; parameter activation policy is settled first |

Do not set a profitability target or a number of paper days as a substitute for evidence. Fix implementation failures before expanding coverage or increasing hosting size. The first milestone should be reproducible data and strategy contracts, not a simultaneous rewrite of every screen.

## 12. Concrete first backlog

1. Specify price/quantity/time units, immutable dataset IDs, and identifiers for current source files.
2. Draft SQL migrations for catalog, collections, observations, run membership and artifact references.
3. Specify a versioned strategy configuration with entry, maker execution, downside-exit and risk policies.
4. Build an import/reconciliation specification using a small real category/date fixture, including current raw paths and latest-run scope.
5. Define API responses for research summaries/cell details and collection-job status; include coverage and model/data versions.
6. Design mobile Research and Strategy screens around those responses.
7. Write the engine state/transition and failure test matrix before implementing exchange submission.
8. Prepare a deployment/migration proposal and a fresh cost estimate for review; do not provision it as part of this draft.

## 13. Costs and open decisions

The previously discussed working budget was approximately $58/month base and $60–$80/month for an initial small managed setup. This is an earlier planning estimate, not a fresh vendor quote or a capacity guarantee. Verify storage, stream volume, database/worker size, backup/retention and bandwidth before purchasing. Large raw order-book retention or heavy backtests can exceed that budget. No subscriptions are being created now.

Decisions to resolve during planning:

- May the bot only execute enabled strategy versions, or also activate newly discovered/retuned strategies automatically? Proposed initial default: execute enabled versions; review parameter changes separately.
- What funds/exposure/loss limits should apply, and should a risk limit constrain the set of researched exit candidates? No numeric defaults are agreed yet.
- Keep all entries/exits maker-only, or allow explicitly authorized urgent taker exits? Maker-only remains the baseline until changed.
- Which single category should lead the paper-trading release? Proposed selection criterion: clearest contract clock and best usable data, rather than best-looking historical P/L.
- What alerts should reach the phone, and through which channel? Record suggestions only until the owner chooses destinations.
- What raw data resolution and retention are worth the storage cost? Begin by measuring a bounded recording sample.

## Review status

This branch contains planning documents only. Nothing has been merged to the deployment branch, deployed, migrated, purchased, or connected to a trading account by this draft. Implementation and deployment sequencing will follow the owner's next instructions.
