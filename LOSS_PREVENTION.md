# Conditional loss prevention

The published loss study now uses schema version 2, model `conditional-outcome-v1`.
It estimates settlement-loss probability from current bid and time remaining,
within the original entry category and contract series. It does not publish the
legacy constant-stop optimizer as a probability boundary or a sale instruction.

`python scripts/loss_prevention.py` builds `backtests/LOSS_PREVENTION.json`.
`python scripts/sync_dashboard.py` copies it to the dashboard fallback asset.
The normal research workflow already runs both steps. Deployment also builds the report from source before uploading the app. A legacy remote schema falls back to that newly built same-origin asset. No additional provider
requests are needed for this analysis.

Decision evidence is either a fresh saved minute bid or a later saved checkpoint
quote for the same contract and side. Complete subsequent paths are unnecessary.
Older checkpoint archives only retain 50–100-cent bids; missing lower quotes are
not inferred from complementary bids. Do not interpret missing evidence as safe
holding. Zero bids count as outcome evidence but cannot establish executable sales.

Counts use one outcome-blind event representative per original entry category,
chosen before examining later quote availability. Repeated dates and correlated
contracts within that event cannot inflate a bin's count. Different categories
and checkpoints still reuse events. Wilson 95% intervals reflect binomial sample
uncertainty; they do not cover regime shifts, cross-event correlation or missing-data
bias. A descriptive estimate is displayed even with one observation, accompanied
by its wide interval. There is no minimum seven-day display gate.

Adjacent observed price bins can bracket a downward 50% loss-probability crossing.
Missing bins are not bridged. Reversals or multiple crossings are labeled ambiguous;
there is no forced monotonic curve or extrapolated precise stop. Boundary estimates
are conditional on remaining time and series, not one timeless exit price.

The table's loss-prevention control adds risk annotations and per-bin details.
Original holding P/L, ROI, win rate and sample sizes remain unchanged in both
historical and latest views. Both use the full historical risk study, clearly
labeled; latest returns still come only from the latest collection. The optional
sale advantage is a descriptive net-bid-versus-expected-payout comparison under
a hypothetical 2-cent exit cost, not verified fees or a validated policy. No live
orders are placed. A frozen exit policy, later-event replay and forward paper
validation are separate future work.

Legacy scenario/replay helpers remain in `scripts/loss_prevention.py` for
reproducibility and existing collector integration. They are no longer used by
the published report. Algorithm and dashboard regression tests cover quote timing,
side alignment, no future leakage, event deduplication, zero bids, uncertainty,
price gaps, series separation and preservation of the original table returns.
