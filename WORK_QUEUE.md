# Money Tree / Kalshi Shared Work Queue

This file is the coordination source of truth for ChatGPT/Codex implementation chats working on this repository.

## How implementation chats must use this file

When the user says **"continue"** and the current chat has finished its assigned work:

1. Read this file before choosing more work.
2. Do **not** start a task already marked `IN PROGRESS` by another chat.
3. Claim exactly one unclaimed task by editing its status to `IN PROGRESS`, adding a short worker label and UTC timestamp.
4. Commit that claim before changing application code so parallel chats can see it.
5. Complete the task end-to-end, including relevant tests/verification.
6. Update this file again with:
   - `DONE` if complete, or `BLOCKED` if genuinely blocked.
   - concise implementation notes.
   - files/components changed.
   - verification performed and result.
   - any follow-up task discovered.
7. If the task is done and the user says "continue" again, return here and claim another `READY` task.
8. Before claiming, re-read the latest `WORK_QUEUE.md` from `main` so a stale copy cannot overwrite another chat's claim.
9. When a task changes application code, record the implementation branch/PR/commit in Completion notes so another chat can audit or continue it.

### Status values
- `READY` — available for any chat to claim.
- `IN PROGRESS` — actively owned; other chats must skip it.
- `BLOCKED` — cannot proceed until the blocker is resolved.
- `DONE` — finished and verified.
- `PAUSED` — intentionally not being worked on.

### Global constraints
- Preserve all existing collected trading data.
- Extend current strategies instead of replacing/resetting them unless explicitly instructed.
- Paper-trading behavior must remain isolated from live trading.
- Do not reduce useful monitoring/trading activity merely to save worker resources.
- Favor instrumentation that lets us measure whether a change actually increased trade opportunities, fills, data volume, and P/L.
- If a task changes shared strategy infrastructure, verify it does not silently break the other active strategies.
- Current user intent: **Market Maker and Favorites are active; volatility strategies are paused.** Paused markets/strategies should remain paused unless explicitly re-enabled.

---

# PRIORITY 1 — Increase Favorites data collection volume

## MT-001 — Allow repeated Favorites data-collection bids on the same market
**Status:** BLOCKED  
**Worker:** ChatGPT / MT-001 implementation merged; deployment pending  
**Claimed:** 2026-11-09 04:32 UTC  
**Priority:** Highest

### Goal
The **data-collection Favorites strategy** must be able to place multiple paper-trading bids/trades in the same market whenever a new qualifying condition appears. The current one-market/one-entry behavior is preventing us from collecting enough observations.

### Required behavior
1. Remove any blanket rule that permanently marks a market "already traded" after the first Favorites data-collection entry.
2. Replace it with an **opportunity-level** rule:
   - A market may generate multiple entries over its lifetime.
   - Each entry must correspond to a distinct qualifying opportunity/event, not repeated duplicate submission every worker cycle.
3. Preserve protections against accidental spam/duplicate bids:
   - Do not submit the same logical signal repeatedly while nothing meaningful has changed.
   - Introduce or reuse an opportunity fingerprint / signal key based on the relevant decision inputs (for example price bucket, probability/side, time-to-expiration bucket, market state, and/or other strategy conditions).
   - Allow another entry when the qualifying condition materially changes or reappears after leaving the qualifying state.
4. Do **not** overwrite prior Favorites observations. Every entry should become its own data point/trade record linked to the same market.
5. Ensure simultaneous/open entries in the same market are represented correctly in:
   - open bids,
   - filled positions,
   - awaiting-settlement positions,
   - realized P/L,
   - strategy summary counts.
6. Risk/capital rules should still apply. The purpose is to collect much more data, not to create infinite exposure.
7. Keep this specifically for the **data-collection Favorites** behavior unless shared infrastructure safely supports it for other strategies.

### Data we need from every Favorites observation
Verify each qualifying entry records enough information to later analyze performance by:
- market/event type,
- market ticker/id,
- side,
- entry price / implied probability,
- entry timestamp,
- time remaining to close/settlement at entry,
- price/probability bucket,
- market-type/category bucket,
- order type / maker-vs-taker if relevant,
- fill status and fill delay,
- final outcome,
- realized P/L,
- any existing Favorites-specific signal/features.

Do not discard existing fields. Add missing fields in a backward-compatible way.

### Instrumentation
Add/verify counters so the dashboard/logs can distinguish:
- qualifying opportunities detected,
- entries attempted,
- entries skipped as exact duplicates,
- entries skipped for risk/capital limits,
- entries filled,
- repeated entries on markets already traded once,
- unique markets observed,
- total observations/trades.

This is important because **we are currently dissatisfied with the amount of data being collected** and need to prove the change increases observation volume.

### Acceptance criteria
- A single market can produce 2+ Favorites data-collection entries when distinct qualifying opportunities occur.
- A static unchanged qualifying state does not produce a new duplicate order every cycle.
- Existing Favorites history remains intact.
- Existing summary/P&L accounting remains correct with multiple entries per market.
- Automated tests cover repeated-entry allowed + duplicate-cycle suppressed behavior.
- Verification includes a paper-trading run or deterministic simulation showing repeated observations from the same market.

### Implementation and verification
- **Code merged** to `build/google-auth-foundation` in PR https://github.com/princesspikachuu/kalshi-scanner-data/pull/137
- Merge commit: `75b304c09db0d46c4904233d7e3ba62e9c3b1b49`.
- GitHub Actions validation: **SUCCESS** at https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42563609262 (full API/owner policy/PostgreSQL suite and staging checks).
- Adds opportunity-level repeat paper-data entries on the same market; price/time signal suppresses unchanged repeated entries; permits fresh qualifying events. Existing timing fill-cohort history remains append-only.
- Enforces per-market paper repeat inventory cap (default 5x configured contract quantity, profile override), cash limits, existing exit protections, and verified freshness/deadlines.
- Tests cover distinct entry orders and prices within one market, duplicate suppression, capped inventory, two distinct fill cohorts through confirmed settlement, and calibrated Favorites retaining its original single-entry behavior.
- Records repeated opportunities, attempts, risk skips, duplicate suppressions and audit events.

### Deployment blocker
- **NOT YET DEPLOYED** to Render. `infra/render.processor.yaml` has `autoDeployTrigger: 'off'`; merging the source branch does not redeploy the paper worker.
- Render connector returned one available workspace (named `My Workspace`), but workspace selection must be explicitly confirmed by the user before any service action. After confirmation: inspect the correct active paper worker, deploy merge commit, verify service healthy, then observe repeated paper entries, duplicate suppression and position/P&L reconciliation in a controlled run.
- Do not mark `DONE` or start throughput comparison MT-003 until deployment and production paper smoke check are verified.
- If MT-002 is being implemented in parallel, rebase its branch on the merged `build/google-auth-foundation` source before merging overlapping Favorites code.

### Completion notes
_Code complete and 1,356-test suite passing; blocked solely on live paper-worker deployment and smoke verification._

---

# PRIORITY 2 — Build Statistics-Backed Favorites concurrently

## MT-002 — Add a Statistics-Backed Favorites strategy alongside Data-Collection Favorites
**Status:** DONE  
**Worker:** ChatGPT / MT-002 implementation  
**Claimed:** 2026-11-09 04:37 UTC  
**Priority:** High

### Goal
Create a second Favorites strategy that runs **concurrently** with the existing data-collection Favorites strategy.

The original Favorites strategy must continue gathering broad observations. The new strategy should use the accumulated Favorites data to make increasingly evidence-based entry decisions and improve as the dataset grows.

### Important separation
- **Data-Collection Favorites** = exploratory / broad observation collection.
- **Statistics-Backed Favorites** = selective trading based on empirical performance in our collected data.
- Do not convert the collector into the statistical strategy.
- Do not stop or narrow the collector merely because the statistical version exists.

### Initial statistical model
Start with transparent, auditable statistics rather than an opaque ML model.

At minimum evaluate historical Favorites results by combinations of:
- market type/category,
- entry price / implied-probability bucket,
- time-to-expiration bucket,
- side if materially relevant,
- other already-collected Favorites features that show sufficient sample size.

**Price/value buckets must use 5-cent increments, not 10-cent increments.** Preserve the full applicable Favorites price range and split it into contiguous 5-cent buckets (for example, 70–74¢, 75–79¢, 80–84¢, etc.; use the actual strategy range rather than hard-coding this example).

For each candidate group calculate useful empirical measures such as:
- sample size,
- win rate,
- expected gross payout / return,
- realized net P/L,
- ROI,
- confidence/uncertainty measure,
- maker fill rate/fill delay where relevant.

### Sparse-data handling
Because the dataset is still small:
1. Do not overfit tiny groups.
2. Require a configurable minimum sample size before treating a narrow segment as authoritative.
3. Use hierarchical/fallback grouping when a narrow combination lacks data, e.g.:
   - exact market type + price bucket + time bucket,
   - then broader market type + price bucket,
   - then broader category/price or another sensible parent group,
   - then a conservative global baseline.
4. Surface the sample size and level of fallback used for every statistical decision.
5. Make thresholds/configuration explicit and easy to change as more data arrives.

### Entry policy
The strategy should only trade when the available historical evidence indicates positive expected value after relevant fees/slippage assumptions and passes configured confidence/sample thresholds.

Record for every decision:
- whether it traded or skipped,
- statistics used,
- sample size,
- grouping/fallback level,
- estimated expected value / expected ROI,
- threshold that was required,
- reason for skip if not traded.

### Continuous improvement
- The statistical strategy should recompute or refresh its evidence from newly settled Favorites observations on a practical cadence.
- New data should improve future decisions automatically without wiping historical results.
- Avoid expensive full-history recalculation every tight worker cycle; cache/materialize aggregates if needed.

### Dashboard/UI
Add a clearly separate Statistics-Backed Favorites card/folder/strategy identity so its:
- realized P/L,
- open bids,
- open/filled/awaiting-settlement positions,
- trade count,
- sample/data basis,
can be distinguished from the Data-Collection Favorites strategy.

#### Required statistics matrix
Display the Favorites statistical evidence as a **two-dimensional table/matrix** rather than a flat list of segments.

- Use **entry value/price as one axis** and **time-to-expiration at entry as the other axis**.
- Use **5-cent value buckets** on the value axis, replacing any existing 10-cent buckets.
- Recommended orientation for readability: **value/price buckets as rows** and **time buckets as columns**. The implementation may transpose this only if the UI is materially clearer.
- Keep different market types/categories separated (for example, separate matrix/table per market type or a market-type selector). Do not pool unlike market types into one table merely to simplify the display.
- Preserve the currently useful time-bucket resolution unless evidence supports changing it; this request changes the **value resolution to 5 cents**, not the time resolution.
- Every cell represents the historical observations for that exact **value bucket × time bucket** combination within the selected market type/category.
- Each populated cell should expose, at minimum:
  - sample size,
  - win rate,
  - ROI or expected value,
  - and whether the Statistics-Backed Favorites strategy currently considers that cell/group eligible to trade.
- Where useful, allow the user to inspect additional cell details such as realized P/L, confidence/uncertainty, fill rate, and fallback level.
- Empty or under-sampled cells must be visibly distinguishable from cells with sufficient evidence. Do not present sparse cells as authoritative.
- When a decision uses a broader fallback because the exact matrix cell lacks enough data, make that fallback apparent rather than making the exact cell look statistically proven.
- The table must update as newly settled Favorites observations are incorporated.

Still expose, where practical:
- current best-performing market/time/price segments,
- sample sizes,
- observed win rate/ROI,
- segments currently allowed vs rejected by the statistical strategy.

### Acceptance criteria
- Both Favorites variants can run at the same time.
- Data-Collection Favorites continues gathering broad data.
- Statistics-Backed Favorites consumes the same historical dataset without modifying/resetting it.
- Decisions are traceable to empirical statistics and sample sizes.
- Sparse-data fallback is tested.
- Newly settled data can change the statistical strategy's future decision parameters.
- P/L and open-position accounting for the two Favorites strategies remain separate.

### Completion notes
- **DONE (implementation and deployment):** PR [#138](https://github.com/princesspikachuu/kalshi-scanner-data/pull/138) merged by squash to `build/google-auth-foundation` at commit `8c44d6c5d2aff4dc8731eee316b1b294c0428b87`.
- **Code:** Separate `favorites_statistics` paper portfolio and account, alongside unchanged broad `favorites` collector; pooled, read-only collector evidence; market/series/side/5-cent-price/time grouping; hierarchical fallback with distinct-event counts and Wilson lower confidence bound; configurable sample, positive EV, ROI, fee/slippage and risk gates; traceable trade/skip decisions.
- **User-requested matrix:** Distinct market-type matrices, value tiers 70–74 through 90–94 plus a 95¢ terminal cell, unchanged entry-time tiers, sample/win rate/ROI/net/confidence, evidence candidate vs sparse vs rejected, explicit fallback labels, responsive scroll container. Existing Favorites time/price research now also displays 5-cent bands.
- **Performance:** One 30-second cached evidence aggregation shared by statistical bots; no history deletion/reset; historical P/L and pending positions kept separate.
- **Tests:** GitHub Actions run [42564105494](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42564105494) **success** on PR head `7ed1ce01635afb1d6faa1070a07f809ad6469fd5`: browser matrix tests, targeted statistical tests, full API/PostgreSQL suite (~1,358 tests), and Blueprint validation.
- **Deployment:** Render API `pocket-api-staging` deploy `dep-dbol5315efls73e7giag` **live**; worker `pocket-processing-staging` deploy `dep-dbol542jnfac73f8laog` **live**, both on merged commit. Exclusive worker handoff verified: new worker logged `demo_worker_ready` then `statistics_favorites_initialized` with **75** paper-bot profiles on 2026-11-09 04:59:42 UTC.
- **UI access caveat / follow-up:** Cloudflare staging gateway build and deploy step succeeded in run [42564499457](https://github.com/princesspikachuu/kalshi-scanner-data/actions/runs/42564499457), but the public unauthenticated staging sign-in-assets smoke check returned HTTP **403** (expected 200). Access protection may be intentional; do not weaken security blindly. An authenticated, end-user browser check remains unverified. This does not negate successful backend deploy and worker initialization. Monitor post-deploy actual orders/decisions separately from code acceptance.

---

# PRIORITY 3 — Validate Favorites data throughput after MT-001

## MT-003 — Measure whether Favorites data collection is now fast enough
**Status:** READY  
**Worker:** —  
**Claimed:** —  
**Priority:** High, but execute after MT-001 is deployed

### Goal
Quantify the actual rate of Favorites data collection after repeated same-market opportunities are enabled. We should not assume MT-001 is sufficient.

### Measure
Compare before/after over comparable active-market windows:
- qualifying signals/hour,
- attempted entries/hour,
- fills/hour,
- settled observations/day,
- unique markets/day,
- observations per unique market,
- duplicate suppressions,
- risk/capital suppressions,
- monitoring/data-gap cycles.

Break down by market type and entry price/time bucket where possible.

### Diagnose remaining bottlenecks
If data collection is still too slow, identify whether the limiting factor is:
- insufficient market discovery,
- too few monitoring slots,
- overly restrictive Favorites entry filters,
- maker orders not filling,
- cooldown logic,
- per-market exposure/risk caps,
- worker/API capacity,
- market availability,
- another gating rule.

Do not simply loosen all safeguards. Identify the dominant bottleneck and create a follow-up task in this file with evidence.

### Acceptance criteria
- We have before/after metrics.
- We know whether observation volume materially increased.
- Any remaining dominant bottleneck is documented as a new READY task.

### Completion notes
_Fill in when done._

---

# PRIORITY 4 — Make Market Maker actually trade

## MT-004 — Diagnose and increase Market Maker opportunity-to-fill throughput
**Status:** READY  
**Worker:** —  
**Claimed:** —  
**Priority:** High

### Current problem
The Market Maker is active but has been producing almost no trading activity. The goal is not merely to make it scan more markets; it must generate materially more valid paper quotes, fills, inventory turns, and completed trades while keeping the strategy economically rational.

### First: instrument the full funnel
Before loosening behavior, measure where candidates disappear. Add or verify counters/reason codes for:
- markets discovered,
- markets monitored,
- markets rejected before quoting,
- quote opportunities generated,
- quote opportunities rejected and exact reason,
- bid/ask quotes submitted,
- quotes replaced/repriced,
- quotes cancelled/expired,
- maker fills,
- partial fills if supported,
- positions/inventory opened,
- inventory exits/offsetting fills,
- completed round trips,
- realized P/L,
- average quote lifetime,
- average time-to-fill,
- spread at quote,
- executable depth at quote,
- API/worker capacity suppressions.

Expose enough of this in logs or dashboard diagnostics to identify the dominant bottleneck.

### Increase participation intelligently
After identifying the bottleneck, implement the highest-impact safe changes. Evaluate at least:
1. **Market breadth** — monitor more than a tiny fixed set when capacity exists. Do not assume four markets is a useful ceiling.
2. **Market selection** — prefer slower, liquid markets suitable for passive quoting rather than short 15-minute volatility markets.
3. **Adaptive quoting** — quote based on actual spread/depth and move quotes when necessary instead of leaving stale fixed prices.
4. **Quote refresh/repricing** — allow a maker quote to improve or re-anchor as the book moves, with anti-churn controls.
5. **Two-sided participation** where strategy/risk rules permit, rather than waiting on only one narrow entry condition.
6. **Inventory-aware sizing** — permit repeated small inventory turns without allowing unbounded directional exposure.
7. **Quote lifetime** — avoid cancelling so quickly that fills are impossible, but also avoid leaving economically obsolete quotes.
8. **Opportunity threshold audit** — find any filters that are so strict they eliminate nearly every candidate.
9. **Capital allocation** — verify unused paper capital is not needlessly preventing additional independent quotes.

Do not simply cross the spread to manufacture activity. Any taker behavior must remain explicitly justified by expected value after fees/slippage and should not replace the maker strategy's core purpose.

### Guardrails
- Paper trading only unless explicitly changed by the user.
- Preserve all existing Market Maker history.
- Do not unpause volatility strategies.
- Do not steal so much worker/API capacity that Favorites data collection materially degrades.
- Keep per-market/event exposure caps and total strategy risk caps.
- Avoid duplicate identical orders every cycle.

### Acceptance criteria
- The dominant reason for low activity is identified with measured funnel counts.
- The implementation produces a material increase in quote attempts and/or fills over a comparable active-market window.
- At least one deterministic or paper-run verification demonstrates the bot can manage multiple simultaneous quote opportunities safely.
- P/L, inventory, open orders, and completed-trade accounting remain correct.
- Any remaining bottleneck becomes a new task in this queue rather than being hidden.

### Completion notes
_Fill in when done._

---

# PRIORITY 5 — Expand monitoring capacity for active strategies

## MT-005 — Remove artificial monitoring bottlenecks and allocate capacity dynamically
**Status:** READY  
**Worker:** —  
**Claimed:** —  
**Priority:** Medium-High; especially relevant if MT-003 or MT-004 shows monitoring starvation

### Goal
The app has previously had surprisingly few effective monitoring slots. Active strategies should use available worker/API capacity efficiently rather than being constrained by arbitrary low fixed limits.

### Required work
1. Map the current monitoring-capacity controls:
   - global slot limits,
   - per-strategy limits,
   - per-category limits,
   - API concurrency/rate-limit controls,
   - database/worker concurrency controls,
   - any stale legacy caps.
2. Distinguish a real external/resource limit from a conservative application default.
3. Add diagnostics showing:
   - eligible candidates waiting for a slot,
   - slots currently used by strategy,
   - slots unavailable because of API/CPU/DB pressure,
   - cycles where candidates were skipped solely for lack of monitoring capacity.
4. Allocate capacity dynamically among the **currently active** strategies:
   - Favorites data collection,
   - Statistics-Backed Favorites when enabled,
   - Market Maker.
5. Paused volatility strategies must not consume active monitoring capacity beyond minimal bookkeeping needed to display their existing state.
6. Allow unused capacity from one active strategy to be borrowed by another rather than sitting idle.
7. Preserve API-rate safety and database stability; increase useful concurrency only as far as measured headroom supports.

### Acceptance criteria
- We can state the actual effective monitoring capacity and its limiting resource.
- A hardcoded low ceiling is removed or justified by measured constraints.
- Active strategies can consume otherwise-idle capacity.
- Paused strategies do not crowd out active strategies.
- Dashboard/logging can show when a strategy is opportunity-limited versus capacity-limited.
- Load tests or controlled paper runs show no material regression in worker stability.

### Completion notes
_Fill in when done._

---

# PRIORITY 6 — Keep paused items out of the way without losing them

## MT-006 — Sort paused folders/strategies/markets to the bottom everywhere
**Status:** READY  
**Worker:** —  
**Claimed:** —  
**Priority:** Medium

### Goal
Paused items should remain visible and retain all history/state, but they should not clutter the top of active operating views.

### Required behavior
- Active folders/strategies appear before paused folders/strategies.
- Within a folder/subfolder, active markets appear before paused markets.
- Preserve the existing ordering logic inside the active group and inside the paused group unless there is a strong reason to change it.
- Pausing/unpausing should immediately move the item to the appropriate group without a full data reset.
- Collapsed/expanded UI state should not accidentally unpause anything.
- Summary totals must continue to include/exclude paused state exactly as the existing product semantics intend; this task is primarily ordering/presentation, not accounting.
- Existing open/settling positions from a paused strategy remain visible and continue normal settlement bookkeeping.

### Acceptance criteria
- A paused market moves below all active markets in its relevant list.
- A paused folder/strategy moves below active folders/strategies.
- Unpausing reverses the ordering.
- No historical trades, P/L, positions, or pause state are lost.
- Mobile and desktop views are verified.

### Completion notes
_Fill in when done._

---

# PRIORITY 7 — Make strategy-learning data visible across strategies

## MT-007 — Add per-strategy data collection and learning diagnostics
**Status:** READY  
**Worker:** —  
**Claimed:** —  
**Priority:** Medium-High

### Goal
For every strategy that is collecting observations in order to improve future behavior, expose clear details about **what data it is collecting, how much data it has, how the data is segmented, and how that evidence is intended to improve the strategy**.

This is broader than Favorites. The user should be able to inspect a strategy and understand whether it is actually building a useful evidence base.

### Scope
Audit all current strategies and classify each as one of:
- **Data-learning strategy** — actively collects observations intended to change future entry/exit/quoting decisions.
- **Operational-only strategy** — records trades/P&L for accounting but does not currently use historical evidence to adapt.
- **Future-learning candidate** — has useful historical data but no adaptive logic yet.

Do not pretend an operational-only strategy is “learning” if it is not.

### Required data-details panel
For each data-learning strategy, add an expandable **Data / Learning** section in the strategy/folder UI showing, where applicable:

- total observations collected,
- settled observations usable for learning,
- open/pending observations not yet usable,
- unique markets/events represented,
- date/time range of the dataset,
- market types/categories represented,
- key features being recorded,
- current bucket/segment definitions,
- sample size per important segment,
- outcome metrics being learned from,
- fill-rate / fill-delay data where execution quality matters,
- entry timing / time-to-expiration data where timing matters,
- price/value/probability data where entry value matters,
- spread/depth/volatility/order-book features where relevant,
- reasons observations were skipped or excluded,
- missing-data counts where material,
- last time aggregates/models/statistics were refreshed.

### Explain how the data improves the strategy
The panel must also state in plain language:
- **what decisions the collected data is meant to improve**, such as entry threshold, quote placement, sizing, time window, market selection, exit timing, maker/taker choice, or risk limits;
- whether the strategy is currently **collecting only**, **using statistics now**, or **waiting for a minimum sample size**;
- the minimum evidence/sample threshold required before data can affect decisions;
- which parameters are currently data-driven versus still fixed/manual;
- what fallback behavior is used when a narrow segment lacks enough data.

### Strategy-appropriate views
Do not force every strategy into the same table. Use the visualization that matches the strategy's decision variables.

Examples:
- Favorites: price/value × time matrix, separated by market type.
- Market Maker: spread/depth/liquidity/fill-rate/quote-lifetime diagnostics and performance by market type.
- Sequential Spread: relevant leg spacing/order, time-to-close, entry spread, completion rate, and P/L by setup.
- High Probability: probability/price × time-to-expiration performance, separated by market type.
- Convexity/partial-profit strategies: entry conditions, excursion, partial-exit timing, realized return, and adverse-move data.
- Volatility strategies, when paused: preserve and display collected evidence, but do not resume trading merely to gather more data.

If a strategy has better natural axes/segments, use those instead.

### Data integrity
- Preserve all existing history.
- Reuse the canonical observation/trade dataset where possible rather than creating duplicate incompatible stores.
- Add missing fields backward-compatibly.
- Historical records lacking a newly added field should remain usable for the dimensions they do contain.
- Clearly distinguish raw observations from derived aggregates/statistics.

### Acceptance criteria
- Every strategy is labeled as data-learning, operational-only, or future-learning candidate.
- Every data-learning strategy has an inspectable data/learning section.
- The user can see what features are being collected and how many useful observations exist.
- The UI explains exactly which future decisions the data is intended to improve.
- Sample sizes and sparse-data limitations are visible.
- No strategy is described as adaptive unless its code actually uses historical evidence.
- Paused strategies retain visible historical learning data without being reactivated.
- Tests verify the diagnostics remain correct as new observations settle.

### Completion notes
_Fill in when done._

---

# Coordination notes

- MT-001 and MT-002 may be worked on by different chats at the same time.
- MT-003 depends on MT-001 being deployed/verified.
- MT-004 can run concurrently with Favorites work if it does not modify the same shared monitoring/risk infrastructure.
- MT-005 should use evidence from MT-003/MT-004 when available. If another task is already changing shared scheduler/monitoring infrastructure, do not create a parallel conflicting implementation; coordinate through this file.
- MT-006 is UI-focused and is a good independent task for a separate chat.
- MT-007 can be implemented incrementally by strategy, but its shared UI/data-contract work must not conflict with active MT-001/MT-002 schema changes.
- If MT-002 needs data-schema fields that MT-001 is already changing, coordinate through this file rather than independently creating conflicting schemas.
