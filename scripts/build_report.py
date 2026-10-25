#!/usr/bin/env python3
"""Human-friendly, maker-only historical P/L grouped by market type and cost band.

Each headline row uses one reference entry time per contract to avoid counting
different snapshots of the same contract as independent trades.
"""
import csv
from collections import defaultdict
from pathlib import Path

ASSETS = [
    ("weather", "Hourly weather", Path("backtests/weather_hourly"), 30,
     (60, 45, 30, 20, 15, 10, 5, 3, 1)),
    ("btc", "Bitcoin (15-minute)", Path("backtests/btc15m"), 5,
     (15, 10, 5, 3, 1)),
    ("eth", "Ethereum (15-minute)", Path("backtests/eth15m"), 5,
     (15, 10, 5, 3, 1)),
]
BANDS = ("50-60", "60-70", "70-80", "80-90", "90-100")

def read_rows(folder):
    rows = []
    for file in sorted(folder.glob("????-??-??.csv")):
        with file.open(newline="", encoding="utf-8") as stream:
            rows.extend(csv.DictReader(stream))
    return [r for r in rows if r.get("maker_bid") and r.get("won")
            and r.get("minutes_before_close") and r.get("ticker")]

def distinct_markets_at_time(rows, minute):
    """At most one YES/NO buy per contract per time window."""
    picked = {}
    for r in rows:
        if int(r["minutes_before_close"]) != minute:
            continue
        key = (r["date"], r["ticker"])
        if key not in picked or float(r["maker_bid"]) > float(picked[key]["maker_bid"]):
            picked[key] = r
    return list(picked.values())

def metrics(rows):
    if not rows:
        return None
    n = len(rows)
    wins = sum(int(r["won"]) for r in rows)
    paid = sum(float(r["maker_bid"]) for r in rows)
    return dict(n=n,wins=wins,avg_price_cents=100*paid/n,
        avg_pl_cents=100*(wins-paid)/n,
        roi_per_100=100*(wins-paid)/paid if paid else 0.0,
        days=len({r["date"] for r in rows}))

def primary_rows(rows, ref_minute):
    at_time = distinct_markets_at_time(rows, ref_minute)
    return [(band, metrics([r for r in at_time if r["price_band"]==band]))
            for band in BANDS]

def format_money(x, unit=""):
    return ("+" if x>0 else "")+f"{x:.2f}"+unit

def tablerow(label, m):
    if m is None:
        return f"| {label} | — | — | — | — | — | — |"
    return (f"| {label} | {m['n']} | {m['wins']}/{m['n']} "
            f"| {m['avg_price_cents']:.1f}¢ | {format_money(m['avg_pl_cents'],'¢')} "
            f"| {format_money(m['roi_per_100'],'%')} | {m['days']} |")

def table_header():
    return [
        "| Bid price range | Markets | Wins / tested | Avg. purchase | Avg. profit/loss per contract | Return on amount invested | Days |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

def comparison_grid(rows, minutes):
    lines = [
        "| Minutes remaining | 50–59.9¢ | 60–69.9¢ | 70–79.9¢ | 80–89.9¢ | 90–99.9¢ |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for mins in minutes:
        single = distinct_markets_at_time(rows,mins)
        parts=[]
        for band in BANDS:
            m=metrics([r for r in single if r["price_band"]==band])
            parts.append((format_money(m["avg_pl_cents"],"¢")+f" ({m['n']})") if m else "—")
        lines.append("| "+str(mins)+"m | "+" | ".join(parts)+" |")
    return lines

def build():
    overview=[
        "# Kalshi Pocket Analytics — Average maker P/L by market type and purchase price",
        "",
        "## How to read the results",
        "",
        "Each row pools contracts of the **same market type**, regardless of city, strike, or YES/NO outcome.",
        "All weather hourly markets are combined. Bitcoin and Ethereum are separate categories.",
        "The reference entry time is **30 minutes before close for hourly weather** and",
        "**5 minutes before close for 15-minute crypto**. These are reference times",
        "chosen to prevent counting the same contract repeatedly in the headline table.",
        "The detailed timing comparison appears below each asset report.",
        "",
        "**Average P/L per contract** = total settlement payouts minus hypothetical",
        "bid purchase costs, divided by the number of sampled contracts. One",
        "YES/NO position is selected per contract at each reference time.",
        "**Return on amount invested** = total simulated net P/L divided by total hypothetical cost.",
        "**Both figures are before fees and assume every maker bid filled. They are NOT actual trade results.**",
        "A positive number is not evidence of a reliably profitable maker strategy.",
        "",
        "## Summary by category and price range",
        "",
        "| Market type | Reference entry | Price range | Markets | Wins | Avg. cost | Avg. P/L per contract | P/L per $100 invested | Days |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key,title,folder,ref,minutes in ASSETS:
        rows=read_rows(folder)
        sampled = distinct_markets_at_time(rows,ref)
        for band, m in primary_rows(rows,ref):
            if m is None:
                overview.append(f"| {title} | {ref}m | {band}¢ | — | — | — | — | — | — |")
            else:
                overview.append(
                    f"| {title} | {ref}m | {band}¢ | {m['n']} | {m['wins']} "
                    f"| {m['avg_price_cents']:.1f}¢ | {format_money(m['avg_pl_cents'],'¢')} "
                    f"| {format_money(m['roi_per_100'],'%')} | {m['days']} |"
                )
        if not rows:
            continue
        detail=[
            "# "+title+" — Average maker profit/loss by price band",
            "",
            f"**Primary comparison uses bids {ref} minutes before settlement.**",
            "Markets are pooled across contracts; no city or strike selection is required.",
            "All maker bids are hypothetical fills, and P/L figures exclude trading fees.",
            "",
            "## Average P/L by cost range",
            "",
            *table_header(),
            *(tablerow(band+"¢",m) for band,m in primary_rows(rows,ref)),
            "",
            "## Timing comparison: average profit/loss per contract",
            "",
            "Cells show average P/L in **cents per contract**, followed by the number",
            "of sampled markets in parentheses. A dash means no quote in that band.",
            "Each time row is a different hypothetical trading decision; do not",
            "add row counts across times as if they were independent contracts.",
            "",
            *comparison_grid(rows,minutes),
            "",
        ]
        if key=="weather":
            kindcounts=defaultdict(set)
            for r in rows:
                kindcounts[r.get("weather_type") or "unknown"].add(r["ticker"])
            detail+=["## Weather types covered",""]
            for kind in ("index","station"):
                detail.append(f"- {kind.title()} hourly: {len(kindcounts[kind])} unique markets sampled.")
            detail.append("")
        detail += [
            f"**Coverage:** {len({r['date'] for r in rows})} UTC day(s), "
            f"{len({r['ticker'] for r in rows})} unique market tickers.",
            "",
            "**Research limitations:** Maker orders may not fill, fill rates are",
            "unmeasured, outcomes from one weather event are correlated, and",
            "one or a few days cannot establish a repeatable edge.",
            "",
        ]
        folder.mkdir(parents=True,exist_ok=True)
        (folder/"REPORT.md").write_text("\n".join(detail),encoding="utf-8")
    overview += [
        "",
        "## Interpretation",
        "",
        "- **Positive P/L** means the sample would have earned money only if the displayed maker bids actually filled.",
        "- **Negative P/L** means the sample lost money even under optimistic fill assumptions.",
        "- **Missing Ethereum/station rows** mean data collection has not produced a usable sample, not that trading there is unprofitable.",
        "- Treat rows with fewer than 7 days or 30 distinct markets as especially preliminary.",
        "- Never add results for different entry times as though each were an independent contract.",
        "",
        "### View timing breakdowns",
        "",
        "- [Hourly weather](weather_hourly/REPORT.md)",
        "- [Bitcoin](btc15m/REPORT.md)",
        "- [Ethereum](eth15m/REPORT.md)",
        "",
    ]
    out=Path("backtests/OVERVIEW.md")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text("\n".join(overview),encoding="utf-8")
    print("Built",out)

if __name__=="__main__":
    build()
