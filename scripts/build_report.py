#!/usr/bin/env python3
"""Create concise, decision-oriented research reports from historical maker quotes.

All profits are hypothetical: quote availability is not maker fill evidence.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

FOLDERS = (
    Path("backtests/weather_hourly"),
    Path("backtests/btc15m"),
    Path("backtests/eth15m"),
)
BANDS = ("50-60", "60-70", "70-80", "80-90", "90-100")
TIMES = {
    "weather_hourly": (60, 45, 30, 20, 15, 10, 5, 3, 1),
    "btc15m": (15, 10, 5, 3, 1),
    "eth15m": (15, 10, 5, 3, 1),
}
TYPES = ("index", "station")
def score(group):
    if not group:
        return None
    stake = sum(float(r["maker_bid"]) for r in group)
    wins = sum(int(r["won"]) for r in group)
    n = len(group)
    days = len({r["date"] for r in group})
    markets = len({r["ticker"] for r in group})
    events = len({(r["date"], r["event_ticker"]) for r in group})
    return {
        "n": n, "wins": wins, "days": days, "markets": markets, "events": events,
        "bid_cents": 100 * stake / n,
        "pnl_per_100": 100 * (wins - stake) / stake if stake else 0,
        "meets_sample_floor": days >= 7 and events >= 30,
    }

def group_rows(rows, kind, mins=None, band=None):
    return [r for r in rows if
            (kind == "all" or (r.get("weather_type") or "crypto") == kind)
            and (mins is None or int(r["minutes_before_close"]) == mins)
            and (band is None or r["price_band"] == band)]

def amount(group):
    s = score(group)
    if s is None:
        return "—"
    return f"{s['pnl_per_100']:+.1f} (n={s['n']})"

def make_report(folder):
    files = sorted(folder.glob("????-??-??.csv"))
    rows = []
    for file in files:
        with file.open(newline="") as handle:
            rows.extend(csv.DictReader(handle))
    if not rows:
        return
    weather = folder.name == "weather_hourly"
    title = "Hourly weather" if weather else ("Bitcoin 15-minute" if folder.name == "btc15m" else "Ethereum 15-minute")
    dates = sorted({r["date"] for r in rows})
    unique_markets = len({r["ticker"] for r in rows})
    kind_list = [k for k in TYPES if group_rows(rows,k)] if weather else ["crypto"]
    lines = [
        f"# {title}: maker-only historical analysis", "",
        f"**Coverage:** {len(dates)} UTC day(s), {unique_markets} distinct contracts, {len(rows)} time-specific observations.",
        "",
        "**How to read this:** Each table cell is hypothetical profit or loss **per $100 invested, before fees**,",
        "followed by the number of historical quotes examined. A positive amount is not a proven trading edge.",
        "Every number assumes a resting **maker buy** was filled at the displayed historical bid.",
        "Historical minute prices cannot establish that your limit order would have executed.",
        "",
        "> **Research status: Preliminary** — not enough independent trading days or fill evidence",
        "> to rank strategies confidently. Different entry times often use the same underlying contracts.",
        "",
        "## Quick comparison by entry time and bid-price range", "",
    ]
    if weather:
        present = {r.get("weather_type") for r in rows}
        if "station" not in present:
            lines.extend([
                "**Single-station hourly data:** None found in the dates collected so far.",
                "This does not mean station markets are nonexistent; the currently sampled dates",
                "contain only Weather Index settlements. We will keep looking on earlier dates.", ""
            ])
    for kind in kind_list:
        label = {"index":"Weather Index (multi-station)","station":"Single-station hourly","crypto":"Crypto"}[kind]
        lines.extend([f"### {label}", "",
            "| Time before close | 50–59¢ | 60–69¢ | 70–79¢ | 80–89¢ | 90–99.9¢ |",
            "|---|---:|---:|---:|---:|---:|"])
        for mins in TIMES[folder.name]:
            row = [f"{mins} min"]
            for band in BANDS:
                row.append(amount(group_rows(rows,kind,mins,band)))
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    lines.extend([
        "## Important interpretation notes", "",
        "- **Example:** +2.5 (n=25) means a simulated $2.50 gain per $100 staked across 25 quoted opportunities.",
        "- **Winning frequency is not profit:** Losing a single 90¢+ contract can erase gains from many winners.",
        "- **Not 25 confirmed trades:** A quoted bid doesn't prove an order could fill at that price or size.",
        "- **Don't add time rows together:** The same contract can appear at 60, 45, 30 minutes, etc.",
        "- **Samples are selected, not exhaustive:** See status.json for the count of markets sampled.",
        "- **Zero-data rows aren't losses:** A dash means no usable quote was found in the sample.",
        "- **Fees aren't included in the primary grid.** A maker-fee stress test remains in summary.csv.",
        "",
        "## Groups with the most evidence (not ranked by returns)", "",
        "| Type | Entry | Bid range | Wins / observations | Average bid | Simulated gain / $100 | Trading days |",
        "|---|---:|---:|---:|---:|---:|---:|"])
    candidates = []
    for kind in kind_list:
        for mins in TIMES[folder.name]:
            for band in BANDS:
                result = score(group_rows(rows,kind,mins,band))
                if result and result["n"]>=10:
                    candidates.append((result["n"],kind,mins,band,result))
    for _,kind,mins,band,s in sorted(candidates,key=lambda r:(-r[0],r[1],-r[2]))[:18]:
        lines.append(f"| {kind} | {mins}m | {band}¢ | {s['wins']} / {s['n']} "
                     f"| {s['bid_cents']:.1f}¢ | {s['pnl_per_100']:+.2f} | {s['days']} |")
    if not candidates:
        lines.append("| No cells have 10 observations yet | — | — | — | — | — | — |")
    if weather:
        lines.extend(["","## Weather coverage by city and type","","| Market type | City | Markets represented |",
            "|---|---|---:|"])
        seen = defaultdict(set)
        for r in rows:
            seen[(r.get("weather_type","unknown"), r.get("city") or "Unknown")].add(r["ticker"])
        for (kind,city),tickets in sorted(seen.items()):
            lines.append(f"| {kind} | {city} | {len(tickets)} |")
    lines.extend(["",f"**Dates collected:** {dates[0]} through {dates[-1]}.",
                  "", "Data provenance: individual market results and 1-minute Kalshi bid candlesticks.",
                  "Use this report to identify testable questions, not to assume a repeatable profit.", ""])
    (folder/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    print("Generated",folder/"REPORT.md")

for folder in FOLDERS:
    if folder.exists():
        make_report(folder)
