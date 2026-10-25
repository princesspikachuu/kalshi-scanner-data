#!/usr/bin/env python3
"""Publish same-origin, cache-refreshable dataset files for the Pocket Analytics app."""
import csv
import datetime as dt
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKTESTS = ROOT / "backtests"
DOCS = ROOT / "docs"
SOURCES = {
    "weather": BACKTESTS / "weather_hourly",
    "btc": BACKTESTS / "btc15m",
    "eth": BACKTESTS / "eth15m",
    "crypto": BACKTESTS / "crypto15m",
    "sports": BACKTESTS / "sports_game",
    "weather_daily": BACKTESTS / "weather_daily",
    "financial_daily": BACKTESTS / "financial_daily",
}
EXPECTED = {
    "asset", "minutes_before_close", "price_band_cents",
    "sampled_markets", "average_profit_loss_cents_per_contract"
}
def main():
    DOCS.mkdir(exist_ok=True)
    src = BACKTESTS / "AVERAGES_BY_TIME_AND_PRICE.csv"
    if not src.exists():
        raise SystemExit("Missing generated average P/L CSV: run build_report.py first")
    with src.open(newline="",encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
        if not EXPECTED.issubset(set(rows[0]) if rows else set()):
            raise SystemExit("Generated P/L CSV is empty or missing expected columns")
    shutil.copyfile(src, DOCS / "data.csv")
    execution_src = BACKTESTS / "EXECUTION_BY_BID_OFFSET.csv"
    if execution_src.exists():
        shutil.copyfile(execution_src, DOCS / "execution.csv")
    assets = {}
    for asset, folder in SOURCES.items():
        files = sorted(folder.glob("????-??-??.csv")) if folder.exists() else []
        days = set()
        tickers = set()
        obs = 0
        types = set()
        for file in files:
            with file.open(newline="",encoding="utf-8") as stream:
                for row in csv.DictReader(stream):
                    if not row.get("ticker"): continue
                    days.add(row["date"])
                    tickers.add((row["date"],row["ticker"]))
                    obs += 1
                    if asset == "weather" and row.get("weather_type"):
                        types.add(row["weather_type"])
        latest_status = {}
        status_path = folder / "status.json"
        if status_path.exists():
            latest_status = json.loads(status_path.read_text(encoding="utf-8"))
        record = {
            "asset":asset,
            "days_sampled":len(days),
            "markets_sampled_total":len(tickers),
            "total_observations":obs,
            "first_date":min(days) if days else None,
            "last_date":max(days) if days else None,
            "hourly_types":sorted(types),
            "latest_run_status":latest_status,
        }
        assets[asset] = record
        (DOCS / f"status-{asset}.json").write_text(
            json.dumps(record,indent=2)+"\n",encoding="utf-8")
    manifest = {
        "published_at":dt.datetime.now(dt.timezone.utc).isoformat(),
        "dataset_rows":len(rows),
        "assets":assets,
    }
    (DOCS / "dataset-meta.json").write_text(
        json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print("Published docs/data.csv and docs/dataset-meta.json:",len(rows),
          "aggregated price/time rows")
    for asset, record in assets.items():
        print(asset,record["days_sampled"],"days",record["markets_sampled_total"],
              "markets",record["total_observations"],"observations")
if __name__ == "__main__":
    main()
