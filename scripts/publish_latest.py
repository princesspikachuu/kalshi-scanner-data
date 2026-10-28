#!/usr/bin/env python3
"""Publish per-category latest-run snapshots from staged unmerged observations."""
import csv,json,os,datetime as dt
from pathlib import Path
from collections import defaultdict
from build_report import ASSETS,BANDS,distinct_markets_at_time,metrics

root=Path("backtests");stage=Path(os.environ.get("POCKET_COLLECTION_STAGE",".run-collection"))
asset=os.environ.get("ASSET")
if not asset or asset not in {x[0] for x in ASSETS}:raise SystemExit("Missing valid ASSET")
source=stage/asset
if not source.exists():raise SystemExit("No staged collection found")
rows=[]
for f in sorted(source.glob("????-??-??.csv")):
    with f.open(newline="",encoding="utf-8") as handle:rows.extend(csv.DictReader(handle))
old=root/"LATEST_BY_CATEGORY.csv"
combined=[]
header=["asset","market_type","minutes_before_close","price_band_cents",
        "sampled_markets","wins","win_rate_percent","average_purchase_price_cents",
        "average_profit_loss_cents_per_contract","hypothetical_roi_percent","sampled_days"]
if old.exists():
    with old.open(newline="",encoding="utf-8") as handle:
        combined=[r for r in csv.DictReader(handle) if r.get("asset")!=asset]
for key,title,folder,ref,minutes in ASSETS:
    if key!=asset:continue
    for minute in minutes:
        for band in BANDS:
            selected=[r for r in distinct_markets_at_time(rows,minute) if r["price_band"]==band]
            m=metrics(selected)
            if m:
                combined.append(dict(zip(header,[asset,title,minute,band,m["n"],m["wins"],
                    round(100*m["wins"]/m["n"],4),round(m["avg_price_cents"],4),
                    round(m["avg_pl_cents"],4),round(m["roi_per_100"],4),m["days"]])))
with old.open("w",newline="",encoding="utf-8") as handle:
    writer=csv.DictWriter(handle,fieldnames=header);writer.writeheader();writer.writerows(combined)
meta=root/"LATEST_METADATA.json"
data=json.loads(meta.read_text()) if meta.exists() else {}
dates=sorted({r["date"] for r in rows})
tickers={(r["date"],r["ticker"]) for r in rows if r.get("ticker")}
data[asset]={"asset":asset,"first_date":dates[0] if dates else None,
             "last_date":dates[-1] if dates else None,
             "days_sampled":len(dates),"markets_sampled_total":len(tickers),
             "total_observations":len(rows),
             "run_id":os.environ.get("GITHUB_RUN_ID","local"),
             "run_attempt":os.environ.get("GITHUB_RUN_ATTEMPT","1"),
             "collected_at":dt.datetime.now(dt.timezone.utc).isoformat(),
             "requested_markets_per_day":int(os.environ.get("MAX_MARKETS","0")),
             "requested_days":int(os.environ.get("DAYS_TO_COLLECT","0")),
             "requested_days_ago":int(os.environ.get("DAYS_AGO","0")),
             "daily_market_limit":int(os.environ.get("MAX_MARKETS","0"))}
meta.write_text(json.dumps(data,indent=2)+"\n")
print("Latest snapshot:",asset,len(tickers),"markets",len(dates),"days")
