# Kalshi Pocket Analytics

Historical research only: BTC and ETH 15-minute contracts, plus **hourly** Weather Index temperature contracts (NYC, Chicago, Miami, coastal Los Angeles). This repo does not place trades.

## Run a first backtest
1. Open [Actions](https://github.com/princesspikachuu/kalshi-scanner-data/actions).
2. Select **Kalshi historical research (weather + crypto)**.
3. Choose **Run workflow**, asset **btc**, days_ago **2**, max_markets **60**.
4. After completion inspect `backtests/btc15m/status.json` and `summary.csv`.
5. Repeat for **eth** and **weather** and earlier dates to build a larger sample.

The collector runs on demand, with no scheduled Kalshi requests. The legacy live-market workflow has been retired.

## Reading the statistics
- Maker entries use the minute's quoted **bid** and **assume fills**; they are *not* proven executable maker returns.
- Taker entries use the minute's quoted **ask** and a fee-model estimate.
- One market can contribute several observation times; correlated observations must not be counted as independent bets.
- Every `status.json` reports market sample size and whether market sampling was truncated. A truncated sample is not comprehensive.
- These are simulations, not trading recommendations. Verify market series, data completeness and fees before drawing conclusions.

## Dashboard
The Cloudflare phone dashboard is deployed separately. It reads `backtests/btc15m/summary.csv`, `backtests/eth15m/summary.csv`, and `backtests/weather_hourly/summary.csv` after GitHub research runs publish them.
