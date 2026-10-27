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

The table now shows a single approximate threshold directly in each cell when
loss prevention is enabled. There is no decision-time picker, tap prompt or risk
detail panel. Turning it off restores the unchanged P/L/ROI/win-rate view.

The display pools event counts across series within the selected market category
at an automatic checkpoint at or before half the original entry time. Weighted
isotonic regression fits loss probability as decreasing with current bid; this
is an explicit modeling assumption, not a claim that the raw bins are monotonic.
The displayed integer is the interpolated 50% crossing between adjacent observed
price bins, marked approximate. No crossing, a missing adjacent bin, zero-bid
interpolation or a crossing above the original average entry price yields a dash.
It does not average selected series thresholds or extrapolate across missing bins.

Both historical and latest use all saved history for threshold estimation while
the original return datasets and counts remain separate and unchanged. These
numbers estimate loss likelihood, not validated sell-versus-hold policies. No
live orders are placed. Later-event replay and paper validation remain separate.

Legacy scenario/replay helpers remain in `scripts/loss_prevention.py` for
reproducibility and existing collector integration. They are no longer used by
the published report. Algorithm and dashboard regression tests cover quote timing,
side alignment, no future leakage, event deduplication, zero bids, uncertainty,
price gaps, series separation and preservation of the original table returns.
