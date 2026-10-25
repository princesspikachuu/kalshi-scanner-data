# Kalshi Pocket Analytics — maker-only research

Research scope:
- **Crypto:** Bitcoin and Ethereum 15-minute markets.
- **Weather:** hourly multi-station Weather Index contracts **and** hourly single-station temperature contracts. The strategy and entry-time/price-band tests are the same for both, but results are segmented by type, city and series.
- **No taker statistics**, no daily high/low or monthly weather contracts, and no automated live-market polling.

## Manual historical research

[Run the historical backtest workflow](https://github.com/princesspikachuu/kalshi-scanner-data/actions/workflows/research-backtest.yml).

Choose an asset (`btc`, `eth`, `weather`), completed UTC day offset `days_ago`, `days_to_collect` (1–7), and per-day `max_markets`. The workflow makes historical API requests only when manually triggered and writes:
- `backtests/btc15m/`
- `backtests/eth15m/`
- `backtests/weather_hourly/`

## Maker interpretation

The entry price is the *historical best bid*, modeled as a resting **buy maker** order that fills at that price. This fill is **hypothetical**, not observed: historical minute candles do not reveal order queue positions or order sizes.

Each summary reports sample sizes, unique markets/events/days, win rate, average bid price, mean ROI and stake-weighted ROI for assumed maker fills without fees and with an illustrative maker-fee stress test. Real maker fees depend on contract series and current fee schedules.

Weather results are grouped at four levels: all weather, Index versus station, city, and series. Crypto uses the same maker-only metrics. Legacy CSVs collected before this update are readable, but their simulated returns are not validated executable returns.

**Important:** Old `summary.csv` results still present until that asset's collector is rerun; those results may use the previous columns and biased first-60-market selection. Re-run October 23 BTC before relying on it.

Collector: [scripts/collect_backtest.py](scripts/collect_backtest.py). No trading orders are placed.
