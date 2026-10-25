#!/usr/bin/env python3
"""Build a human-readable maker-only report from collected daily CSV files."""
import csv
from collections import defaultdict
from pathlib import Path

for folder in (Path("backtests/btc15m"),Path("backtests/eth15m"),Path("backtests/weather_hourly")):
    files=sorted(folder.glob("????-??-??.csv"))
    if not files:continue
    rows=[]
    for file in files:
        with file.open(newline="") as stream:rows.extend(csv.DictReader(stream))
    if not rows:continue
    groups=defaultdict(list)
    for r in rows:
        if not r.get("maker_bid") or not r.get("won"):continue
        mins=int(r["minutes_before_close"])
        band=r["price_band"]
        kind=r.get("weather_type","crypto") or "crypto"
        city=r.get("city","") or ""
        groups[(kind,city,mins,band)].append(r)
    out=["# Maker-only historical research: "+folder.name,"",
         "**Important:** Entries are simulated at the recorded best bid. The data do not prove a resting limit order would have filled. Do not treat this as executable historical profit.","",
         "## What the numbers mean","",
         "- **Wins / tested:** Outcomes that paid $1, assuming every listed bid was filled.",
         "- **Average bid:** Typical hypothetical purchase price.",
         "- **Profit / $100:** Stake-weighted settlement profit on each $100 hypothetically invested at those bids, **before fees**. This is not a forecast.",
         "- Results from fewer than 30 distinct markets or fewer than 7 days are marked **limited evidence**.",
         "- Rows for different entry times may be the same underlying contracts; do not add them together as independent trades.",
         "",
         "## Results by weather type, city, entry time and price band","",
         "| Type | City | Time left | Price | Wins / tested | Avg. bid | Profit / $100 | Evidence |",
         "|---|---|---:|---:|---:|---:|---:|---|"]
    for (kind,city,mins,band),rs in sorted(groups.items(),key=lambda kv:(kv[0][0],kv[0][1],-kv[0][2],kv[0][3])):
        n=len(rs);wins=sum(int(r["won"]) for r in rs)
        stake=sum(float(r["maker_bid"]) for r in rs)
        pnl=(wins-stake)/stake*100 if stake else 0
        avg=100*stake/n
        days=len({r["date"] for r in rs})
        markets=len({r["ticker"] for r in rs})
        evidence="Limited" if days<7 or markets<30 else "Research sample"
        minutes=f"{mins//60}h" if mins%60==0 and mins>=60 else f"{mins}m"
        out.append(f"| {kind} | {city or '—'} | {minutes} | {band}¢ | {wins} / {n} | {avg:.1f}¢ | ${pnl:+.2f} | {evidence} |")
    out.extend(["","## Data coverage",f"- Recorded days: {len({r['date'] for r in rows})}",f"- Market observations: {len(rows)}",f"- Unique market tickers: {len({r['ticker'] for r in rows})}","- No claim is made about fees, fills, market impact, confidence intervals, or a reliable trading edge.",""])
    (folder/"REPORT.md").write_text("\n".join(out),encoding="utf-8")
    print("Created",folder/"REPORT.md")
