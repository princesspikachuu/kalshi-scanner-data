# Loss prevention: decision-state risk before strategy optimization

Draft specification. No application deployment or trading change. This replaces the proposed statistical design, not the deployed implementation.

## Problem confirmed in the current implementation

`scripts/loss_prevention.py` asks which constant stop price would have improved average final P/L over entire subsequent price paths. It groups by original entry time and price category, requires every subsequent minute to have a quote, selects among 5-cent stop increments, and requires at least five training days plus two later test days. Additional market, event, trigger and confidence gates can suppress all candidates.

That is a strategy backtest. It does not estimate the probability of losing given a position's current price and time remaining. Sparse complete paths and outcome-dependent coverage can also make its usable sample unrepresentative. A rejected strategy candidate is not evidence that holding is safe. Tiny salvage stops must not be described as the boundary where losing becomes likely.

## Questions the table must distinguish

1. **Settlement risk:** Given the observed state, what is the probability this side settles at zero? "More likely to lose than win" means this probability exceeds 50%. For these positive-cost binary positions, settlement at zero implies a losing hold.
2. **Expected loss:** What is expected final P/L from holding, relative to the original all-in entry cost? A position can win more often than it loses and still have negative expected P/L.
3. **Sell versus hold:** Does executable net sale value exceed conditional expected remaining settlement value? This is a different boundary from 50% loss probability.

For a one-contract $1 payout, in cents:

`net_sale = executable_bid - actual_exit_costs`

`expected_hold_value = 100 * P(win | state) - expected_remaining_settlement_costs`

`sale_advantage = net_sale - expected_hold_value`

Original entry cost cancels in the current sell-versus-hold comparison. Keep it for category conditioning, realized loss, expected total P/L and downside-only eligibility. For example, a 55-cent bid and estimated 50% win probability produce a 3-cent estimated sale advantage under a hypothetical 2-cent exit cost and no remaining settlement cost. The deployed fixed fee stresses are not verified exchange fees.

The loss-prevention feature only evaluates below-entry sales. It does not introduce profit-taking. No executable positive bid means no claimed sale, even when estimated loss risk is high. A risk cap chosen by the owner is a separate rule.

## Revised observations and model

Build decision snapshots at predefined remaining-time checkpoints strictly after entry and before close. Features available at that instant include market family, original entry category/time, current side bid, remaining time, quote freshness and any later-approved contemporaneous features. Include eventual settled outcome only as the label.

A valid entry, one valid decision quote and a known eventual outcome are sufficient for a risk observation. Do not require the later price path. Preserve zero bids as risk observations while excluding them as executable sales. Keep unknown, stale and absent quotes distinct. Measure missingness and compare included/excluded entry cohorts.

Use one observation per position/checkpoint, with deterministic outcome-blind deduplication. Related contracts, complementary outcomes, checkpoints and collection days must not be treated as independent events. Assign every snapshot of a real event to one validation partition; use event-clustered uncertainty and disclose raw observations and distinct events separately. Repeated collection dates do not create new independent events.

Start with auditable event-weighted outcome counts in current-price and remaining-time bins, retaining the original entry-category context. Show empirical rates and event-level uncertainty. Do not impose an arbitrary calendar-day gate merely to display a descriptive estimate. Small samples remain visibly uncertain; zero observed losses does not imply zero risk.

Then compare a calibrated binomial model with partial pooling against those counts and the simple price-as-probability baseline. Pool within comparable market families; do not silently combine sports leagues, weather and crypto. Select smoothing and pooling strength using training data only. If bins are noisy or the crossing is ambiguous, show a range or no established crossing; do not manufacture a single precise stop. Check any assumed monotonic relationship against held-out observations.

## Table behavior

Keep the original table's full holding baseline and sample sizes. Add loss-risk details for each original entry category:

- Current decision checkpoint and current price range.
- Estimated settlement-loss probability, uncertainty, independent-event count and coverage.
- Estimated boundary where loss probability crosses 50%, conditional on remaining time; show an unresolved interval when appropriate.
- Separately, estimated sale-versus-hold advantage after stated exit costs, and whether it has later validation.
- Status distinguishing descriptive estimate, uncertain crossing and validated policy. Never label unavailable evidence as a recommendation to hold.

An original entry cell can have different risk boundaries at different remaining times. Its detail view should show that curve rather than pretend one timeless stop is a sufficient summary. Do not change the table's historical P/L just because a risk estimate exists. A P/L overlay requires a frozen, separately tested exit policy with an explicit covered subset.

## Validation and implementation sequence

1. Build and audit the snapshot dataset using existing saved quotes and outcomes. Verify units, side/outcome alignment, no post-decision feature leakage, stable event identifiers and duplicate suppression. Publish coverage alongside estimates.
2. Add empirical conditional-risk output and uncertainty to an offline report. No arbitrary seven-day requirement. Show point estimates separately from evidence strength.
3. Fit and calibrate candidate models on earlier event groups, test on later groups, and compare calibration, Brier score and log loss against raw current price. Keep tuning data separate from the final test. Confirm close-time checkpoints represent the intended event horizon, especially for sports.
4. Define a frozen downside-only policy from the risk/value estimates. Use conservative uncertainty for any supported-exit label. A probability crossing alone does not establish positive sale advantage.
5. Replay that policy on independent later events using actual available bids, fees and stated execution assumptions. Full or explicitly coverage-bounded paths are needed here to evaluate the first trigger, not to estimate point-state outcome risk. Report missed recoveries, loss reduction, total P/L, fees and coverage. Never infer unobserved exits across gaps.
6. Integrate descriptive risk into the table first; enable simulated performance changes only for validated policy evidence. Forward paper validation precedes any future automated order placement.

## Existing-data diagnostic

An offline audit of the saved sports dataset published on 2026-10-26 examined original entries three hours before close in the 60–70-cent band, at a later checkpoint one hour before close. Accepting one fresh quote yielded 314 market observations, versus 124 entries passing the existing complete-path requirement. These are different evidence requirements, not directly interchangeable backtest cohorts.

To reduce correlated outcomes, the diagnostic selected one deterministic representative per `(date, event_ticker)` using highest original entry bid, then ticker, without inspecting settlement results. It found 173 event representatives overall. This is a diagnostic grouping; production must also eliminate repeated real events across dates.

| Current side bid | Event representatives | Settled losses | Observed loss rate |
| --- | ---: | ---: | ---: |
| 40–50 cents | 14 | 11 | 78.6% |
| 50–60 cents | 22 | 12 | 54.5% |
| 60–70 cents | 23 | 8 | 34.8% |
| 70–80 cents | 18 | 4 | 22.2% |

These retrospective pooled-sports counts illustrate that the requested transition can be investigated with existing data. They are not calibrated estimates, validated stop thresholds, executable trade recommendations or evidence that a particular loss-prevention policy improves returns. No production threshold was changed by this audit.
