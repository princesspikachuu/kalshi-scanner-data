#!/usr/bin/env python3
"""Descriptive decision-state loss risk. This is not an exit-policy backtest."""
import datetime as dt
import json
import math
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

CHECKPOINTS = (360, 180, 120, 60, 45, 30, 20, 15, 10, 5, 3, 1)
EXIT_COST_STRESS_CENTS = 2


def wilson(losses, n):
    """95% binomial interval over distinct event representatives, including n=1."""
    p = losses / n
    z = 1.959963984540054
    denominator = 1 + z*z/n
    center = (p + z*z/(2*n)) / denominator
    radius = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / denominator
    return max(0, center-radius), min(1, center+radius)


def boundary(bins):
    """Bracket observed 50% crossings; never extrapolate or force monotonicity."""
    crossings = []
    for left, right in zip(bins, bins[1:]):
        if left['bid_high_cents'] != right['bid_low_cents']:
            continue  # a missing price bin cannot establish the crossing
        if left['loss_rate_percent'] > 50 and right['loss_rate_percent'] <= 50:
            crossings.append({
                'low_cents': left['bid_low_cents'], 'high_cents': right['bid_high_cents'],
                'events': left['events'] + right['events'],
                'clear_at_95_percent': left['loss_lower_percent'] > 50 and right['loss_upper_percent'] < 50,
            })
    # An upward reversal means there is no single stable threshold.
    reversal = any(a['loss_rate_percent'] <= 50 < b['loss_rate_percent'] for a, b in zip(bins, bins[1:]))
    return {'status': 'ambiguous' if reversal or len(crossings) > 1 else 'estimated' if crossings else 'unresolved',
            'ranges': crossings}


def summarize(items):
    grouped = defaultdict(list)
    for item in items:
        # 100 is included in the final bin. Zero is retained as outcome evidence.
        grouped[min(90, int(item['bid'] // 10) * 10)].append(item)
    bins = []
    for low, group in sorted(grouped.items()):
        n = len(group)
        losses = sum(1 - x['won'] for x in group)
        lower, upper = wilson(losses, n)
        mean_bid = sum(x['bid'] for x in group) / n
        has_zero_bid = any(x['bid'] == 0 for x in group)
        bins.append({'bid_low_cents': low, 'bid_high_cents': low + 10,
            'events': n, 'losses': losses, 'loss_rate_percent': round(100*losses/n, 4),
            'loss_lower_percent': round(100*lower, 4), 'loss_upper_percent': round(100*upper, 4),
            'mean_bid_cents': round(mean_bid, 4),
            'zero_bid_events': sum(x['bid'] == 0 for x in group),
            'below_entry_events': sum(x['bid'] < x['entry'] for x in group),
            'sale_advantage_cents': None if has_zero_bid else round(mean_bid - EXIT_COST_STRESS_CENTS - 100*(1-losses/n), 4),
            'sale_advantage_lower_cents': None if has_zero_bid else round(mean_bid - EXIT_COST_STRESS_CENTS - 100*(1-lower), 4),
            'sale_advantage_upper_cents': None if has_zero_bid else round(mean_bid - EXIT_COST_STRESS_CENTS - 100*(1-upper), 4)})
    return bins


def analyze_risk(rows, paths, asset):
    from loss_prevention import canonical
    saved = canonical(rows)
    representatives = {}
    eligible = 0
    # Older archives have checkpoint entry quotes but no full candle sidecar.
    # Reuse only an actually saved quote for this SAME contract and side.
    # Never infer a bid from the opposite side's bid.
    saved_quotes = defaultdict(list)
    for r in rows:
        try:
            close = int(dt.datetime.fromisoformat(r['close_time'].replace('Z', '+00:00')).timestamp())
            age = float(r.get('quote_age_seconds') or 0)
            bid = 100 * float(r['maker_bid'])
            ts = close - 60*int(r['minutes_before_close']) - age
        except (KeyError, ValueError, TypeError):
            continue
        if 0 <= age <= 60 and math.isfinite(bid) and 0 <= bid <= 100:
            saved_quotes[(r['date'], r['ticker'], r['side'])].append((ts, bid))
    quote_index = {}
    for key, quotes in saved_quotes.items():
        quotes.sort()
        quote_index[key] = (quotes, [q[0] for q in quotes])
    # Choose one outcome-blind event representative before examining quote coverage.
    # Stable event IDs, without a collection-date prefix, prevent repeat-day inflation.
    for r in saved:
        try:
            entry = 100 * float(r['maker_bid'])
            minute = int(r['minutes_before_close'])
            won = int(r['won'])
            age = float(r.get('quote_age_seconds') or 0)
        except (ValueError, TypeError):
            continue
        if not (0 < entry < 100 and won in (0, 1) and 0 <= age <= 60):
            continue
        eligible += 1
        family = r.get('series') or r.get('weather_type') or asset
        event = r.get('event_ticker') or r['ticker']
        key = (family, minute, r['price_band'], event)
        rank = (-entry, r['ticker'], r.get('side', ''), r['date'])
        if key not in representatives or rank < representatives[key][0]:
            representatives[key] = (rank, r)
    grid = defaultdict(list)
    requested = defaultdict(int)
    covered = set()
    path_cache = {}
    for key, (_, r) in representatives.items():
        family, minute, band, event = key
        path_key = (r['date'], r['ticker'])
        path = paths.get(path_key)
        if path_key not in path_cache and path is not None:
            # Latest bar at/before a checkpoint wins; an explicit null is not backfilled.
            bars = sorted(path['bars'], key=lambda b: b[0])
            path_cache[path_key] = (bars, [int(b[0]) for b in bars])
        for decision in CHECKPOINTS:
            if decision >= minute:
                continue
            group = (family, minute, band, decision)
            requested[group] += 1
            try:
                close = int(path['close_ts']) if path is not None else int(dt.datetime.fromisoformat(r['close_time'].replace('Z', '+00:00')).timestamp())
            except (KeyError, ValueError, TypeError):
                continue
            target = close - 60*decision
            bid = None
            source = 'minute_path'
            if path is not None:
                bars, times = path_cache[path_key]
                index = bisect_right(times, target) - 1
                if index >= 0:
                    b = bars[index]
                    if 0 <= target-int(b[0]) <= 60 and int(b[0]) > close-60*minute:
                        bid = b[1 if r['side'] == 'yes' else 2]
            if bid is None:
                quotes, times = quote_index.get((r['date'], r['ticker'], r['side']), ([], []))
                index = bisect_right(times, target) - 1
                if index >= 0 and 0 <= target-times[index] <= 60 and times[index] > close-60*minute:
                    bid = quotes[index][1]
                    source = 'saved_checkpoint'
            if not isinstance(bid, (int, float)) or not math.isfinite(bid) or not 0 <= bid <= 100:
                continue
            grid[group].append({'event': event, 'bid': bid, 'won': int(r['won']),
                                'entry': 100*float(r['maker_bid']), 'source': source})
            covered.add(key)
    records = []
    for (family, minute, band, decision), count in sorted(requested.items()):
        items = grid[(family, minute, band, decision)]
        bins = summarize(items)
        records.append({'asset': asset, 'family': family, 'minutes_before_close': minute,
                        'price_band_cents': band, 'decision_minutes_remaining': decision,
                        'eligible_events': count, 'observed_events': len(items),
                        'saved_checkpoint_events': sum(x['source'] == 'saved_checkpoint' for x in items),
                        'bins': bins, 'boundary': boundary(bins)})
    return {'records': records, 'saved_observations': len(saved),
            'eligible_entry_observations': eligible, 'event_entry_groups': len(representatives),
            'covered_event_entry_groups': len(covered),
            'note': 'Counts are distinct event representatives within each entry category/checkpoint; rows reuse events. Older checkpoint-only archives save 50–100-cent quotes, so their lower-price coverage is incomplete. No opposite-side bid is converted into a sale bid. Missing quotes are excluded, not interpreted as safe holding.'}


def build_risk_report():
    from build_report import ASSETS, read_rows
    from loss_prevention import read_paths
    report = {'version': 2, 'model': 'conditional-outcome-v1',
              'published_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'exit_cost_stress_cents': EXIT_COST_STRESS_CENTS,
              'historical': {},
              'method': 'Observed settlement-loss rates by series, original entry category, current bid and remaining time. One event representative per category; Wilson 95% intervals. Descriptive, not an optimized or validated exit policy. Complete future paths are not required. The 2-cent sale cost is a stress assumption, not verified fees.'}
    for asset, _, folder, _, _ in ASSETS:
        report['historical'][asset] = analyze_risk(read_rows(folder), read_paths(folder), asset)
    Path('backtests/LOSS_PREVENTION.json').write_text(json.dumps(report, separators=(',', ':'), allow_nan=False) + '\n')
    print('Published conditional loss risk; original holding results are unchanged.')
