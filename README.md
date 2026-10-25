# Kalshi Pocket Analytics

Research scope: **Bitcoin and Ethereum 15-minute contracts**, and **hourly multi-station Kalshi Weather Index** markets in NYC, Chicago, Miami, and coastal Los Angeles. No trading orders or scheduled market scans.

## Running historical research

Open [Kalshi historical research](https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/research-backtest.yml), choose **Run workflow**:

- `asset=btc`, `days_ago=2`, `days_to_collect=1`, `max_markets=100` for the first validation run.
- Then run `asset=eth` with the same settings.
- Finally run `asset=weather`, `max_markets=100`. Weather has many strike markets per hourly event, so 100 is only a sample.
- Once each passes, choose up to `days_to_collect=7`, and repeat with earlier `days_ago` to backfill. Each run is **manual-only**.

**Caution:** The Oct 23 BTC dataset was collected with an older, time-biased sampling algorithm. Re-run Oct 23 with the updated collector before comparing results or quoting an ROI.

## Meaning of the results
- Maker bid means **hypothetical resting buy filled at quoted bid**; actual execution is NOT verified.
- Taker ask means **hypothetical immediate purchase at the quoted ask**; quote availability/size are not guaranteed.
- `mean_roi_no_fees_if_filled` includes maker observations even when no taker ask exists and is NOT directly comparable with `mean_roi_taker_if_filled`.
- Use `matched_maker_mean_roi` versus `matched_taker_mean_roi` and the paired stake-weighted ROI fields for a comparison using the **same** observations.
- `series` splits weather cities and includes an `ALL` aggregate.
- `quote_coverage_rate` reports the fraction of hypothetical maker observations with usable matching taker asks.
- Backtest uses simplified fee coefficients and simulated fills. The fee schedule may depend on the actual Kalshi series. No model here tests order-book queues or predictability of fills.
- Every day is a separate file. Summary recalculates from all available daily files. Each `status.json` describes the **latest** collected date, not an entire historical batch.
- Review `sampling_truncated`, sample counts, and the series represented before interpreting the totals.

Code: [scripts/collect_backtest.py](scripts/collect_backtest.py)

Data: `backtests/btc15m/`, `backtests/eth15m/`, `backtests/weather_hourly/`.

The old live-scanner schedule was retired. The Cloudflare app is managed separately and has not been redeployed automatically.
