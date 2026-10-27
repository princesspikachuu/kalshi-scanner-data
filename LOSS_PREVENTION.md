# Loss prevention in the return table

The loss-prevention switch keeps the normal P/L, ROI and win-rate table. With it
on, each cell adds its sell threshold and applies only the measured paired change
from a simulated exit replay. With it off, the original dataset and values are
unchanged. Sample sizes never shrink to a smaller exit-study cohort.

If the original group's loss rate exceeds 50%, the cell says **Trade not
recommended** instead of displaying the sell threshold. Exactly 50% does not
trigger this label. This warning does not remove trades from the return dataset.

## Research policy

Fit the category's conditional 50% loss boundary from earlier event representatives
using weighted decreasing isotonic regression over current-price bins. Interpolate
only between adjacent observed price bins; never bridge a missing band or invent
an above-entry threshold. Display a descriptive estimate even if a frozen replay
is not available yet, but do not change returns without a replay.

Freeze that threshold on earlier events (approximately 70% chronological training).
Evaluate one checkpoint at or before half the original entry window on later
events, only when the decision occurs after every training event's close. No
minimum seven-day gate is imposed. This is a checkpoint policy, not a claim to
have simulated the first crossing over an unobserved full minute path.

A qualifying below-entry positive bid at that checkpoint is the simulated sale
price. Never assume a fill at the threshold when the observed bid gaps below it.
Zero bids cannot execute. Incremental exit cost uses a 2-cent stress assumption,
not verified exchange fees. A missed recovering winner counts against the policy.
All adverse as well as favorable measured differences are retained.

For one $1-payout contract, paired sale-minus-hold change in cents is:

`observed sale bid - 2-cent exit cost - 100 * eventual win`

The entry price and common entry fees cancel. Apply the sum of these paired
changes over the original full cell count for average P/L; recompute ROI over the
original total entry cost. Uncovered, training-only and unavailable positions
retain their original holding result. This is a partial research overlay, not a
validated live strategy or verified order-fill history.

## Latest and historical views

Historical replay uses the whole saved history. Latest replay is restricted to
exact run membership and uses only historical events up to the last relevant
latest event. Thus loading an older period never borrows future historical
outcomes. Latest and historical retain their own original returns and counts.

New collections persist membership in `backtests/LATEST_MEMBERSHIP.json`, bound
to the latest run ID. An older run is recovered only when its complete saved date
range matches metadata and all published entry-cell counts, wins and prices.
Otherwise its ROI stays unchanged until a fresh collection saves exact membership.

## Build and validation

Run `python scripts/loss_prevention.py` and `python scripts/sync_dashboard.py`.
The normal collection and deployment workflows already build this report. The
compact published schema is version 2 with `roi_policy_version: 1`; older schemas
fall back to the freshly built same-origin report. No new provider calls are
needed. The raw decision-risk analyzer remains available for research tests.

Tests cover chronological fitting, future-label exclusion, older latest runs,
actual sale bids, zero bids, costs, missed recoveries, adverse deltas, event
deduplication, full-sample return preservation and the >50% loss warning.
