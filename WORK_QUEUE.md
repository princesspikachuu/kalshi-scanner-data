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
**Status:** IN PROGRESS  
**Worker:** ChatGPT / MT-001 implementation  
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

### Implementation progress
- Branch: `feature/mt001-repeat-favorites-observations` (based on live app source branch `build/google-auth-foundation`, not repository `main`).
- PR: https://github.com/princesspikachuu/kalshi-scanner-data/pull/137
- Added bounded same-market Favorites paper re-entry keyed by entry price/time bucket, with duplicate and risk suppressions, existing fill-cohort accounting, and targeted tests.
- **Pending:** full CI results, independent review of re-entry accounting, and paper-run verification before merge/deployment. Do not mark DONE or assume deployed.
- The default `main` branch contains the research scanner and this queue; the paper engine source is on `build/google-auth-foundation`.

### Completion notes
_Fill in once verified._

---

# PRIORITY 2 — Build Statistics-Backed Favorites concurrently

## MT-002 — Add a Statistics-Backed Favorites strategy alongside Data-Collection Favorites
**Status:** IN PROGRESS  
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

Where practical, expose:
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
_Fill in when done._

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

# Coordination notes

- MT-001 and MT-002 may be worked on by different chats at the same time.
- MT-003 depends on MT-001 being deployed/verified.
- MT-004 can run concurrently with Favorites work if it does not modify the same shared monitoring/risk infrastructure.
- MT-005 should use evidence from MT-003/MT-004 when available. If another task is already changing shared scheduler/monitoring infrastructure, do not create a parallel conflicting implementation; coordinate through this file.
- MT-006 is UI-focused and is a good independent task for a separate chat.
- If MT-002 needs data-schema fields that MT-001 is already changing, coordinate through this file rather than independently creating conflicting schemas.
