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
        "# Kalshi Pocket Analytics — average maker P/L by entry time and price",
        "",
        "**Main metric:** average simulated profit/loss per contract, in cents.",
        "Each cell pools all hourly weather contracts (regardless of city), or",
        "all Bitcoin or Ethereum contracts within the specified time and purchase-price range.",
        "Each cell shows the average profit/loss followed by the number of markets (n).",
        "",
        "**These are not executed trades.** We assume a maker buy fills at the",
        "historical best bid. Fees and fill probability aren't included.",
        "Each entry time reuses some of the same underlying contracts: do not",
        "add sample counts across time rows.",
        "",
    ]
    rows_for_csv=[]
    for asset,title,folder,reference,minutes in ASSETS:
        raw=read_rows(folder)
        days=len({r["date"] for r in raw})
        markets=len({r["ticker"] for r in raw})
        overview += [
            "## "+title,
            "",
            f"**Coverage:** {days} UTC day(s), {markets} distinct markets.",
            "",
            "### Average profit/loss (¢ per contract) by time and bid price",
            "",
            *comparison_grid(raw,minutes),
            "",
        ]
        detail=[
            "# "+title+": maker profit/loss by time and purchase price",
            "",
            "**Main metric:** average profit/loss in cents per contract.",
            f"Coverage: {days} UTC day(s), {markets} distinct markets.",
            "Simulated filled maker bids; P/L excludes fees.",
            "",
            "## Average profit/loss grid",
            "",
            *comparison_grid(raw,minutes),
            "",
            "## Complete results",
            "",
            "| Time left | Price range | Markets | Wins | Win rate | Avg. purchase | Avg. P/L per contract | Hypothetical ROI | Days |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for minute in minutes:
            markets_at_time=distinct_markets_at_time(raw,minute)
            for band in BANDS:
                selected=[r for r in markets_at_time if r["price_band"]==band]
                m=metrics(selected)
                if m is None:
                    detail.append(f"| {minute}m | {band}¢ | — | — | — | — | — | — | — |")
                    continue
                winrate=100*m["wins"]/m["n"]
                rows_for_csv.append([asset,title,minute,band,m["n"],m["wins"],
                                    round(winrate,4),round(m["avg_price_cents"],4),
                                    round(m["avg_pl_cents"],4),round(m["roi_per_100"],4),m["days"]])
                detail.append(
                    f"| {minute}m | {band}¢ | {m['n']} | {m['wins']} "
                    f"| {winrate:.1f}% | {m['avg_price_cents']:.2f}¢ "
                    f"| {format_money(m['avg_pl_cents'],'¢')} "
                    f"| {format_money(m['roi_per_100'],'%')} | {m['days']} |"
                )
        if asset=="weather":
            counts=defaultdict(set)
            for r in raw:
                counts[r.get("weather_type") or "unknown"].add(r["ticker"])
            detail.extend([
                "",
                "## Weather market types in sample",
                f"- Multi-station Weather Index: {len(counts['index'])} markets",
                f"- Single-station hourly: {len(counts['station'])} markets",
                "If a type is absent, that reflects no usable data in the sampled dates.",
            ])
        detail.extend([
            "",
            "## Interpretation and limitations",
            "The same market may appear at multiple entry times. Each time/price",
            "cell includes at most one YES or NO position per ticker. Do not sum",
            "time rows as independent bets.",
            "Quote prices do not guarantee a limit-order fill or quantity.",
            "All P/L is hypothetical and before fees.",
            "A short or incomplete historical sample cannot prove an edge.",
            "",
        ])
        if raw:
            folder.mkdir(parents=True,exist_ok=True)
            (folder/"REPORT.md").write_text("\n".join(detail),encoding="utf-8")
            overview.extend([
                "For example, +4.2¢ (n=36) means an average gain of 4.2 cents per",
                "hypothetically filled contract among 36 sampled markets in that cell.",
                "",
                f"[Detailed {title} metrics]({folder.name}/REPORT.md)",
                "",
            ])
        else:
            overview.extend(["No historical observations collected yet for this market type.",""])
    overview.extend([
        "## Research cautions",
        "- These are simulated maker bids, NOT verified trades or fills.",
        "- Different entry-time rows can reflect the same underlying contract.",
        "- Hourly weather pools Weather Index and single-station contracts; see the weather details for coverage.",
        "- A dash indicates no observations, not a loss.",
        "- The report is preliminary until we collect multiple days and study maker fill likelihood.",
        "",
    ])
    Path("backtests").mkdir(exist_ok=True)
    Path("backtests/OVERVIEW.md").write_text("\n".join(overview),encoding="utf-8")
    with Path("backtests/AVERAGES_BY_TIME_AND_PRICE.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.writer(stream)
        writer.writerow(["asset","market_type","minutes_before_close","price_band_cents",
                         "sampled_markets","wins","win_rate_percent","average_purchase_price_cents",
                         "average_profit_loss_cents_per_contract","hypothetical_roi_percent","sampled_days"])
        writer.writerows(rows_for_csv)
    print("Updated entry-time by price-band reports and CSV.")

if __name__=="__main__":
    build()
