"""Pinned pure current-main conditional loss model; no filesystem/network operations."""

import datetime as dt
import math
from bisect import bisect_right
from collections import defaultdict
from ..report_jobs import check_priority

SOURCE_COMMIT = '26c65c2325d3c5f18e3c8e9ef8142fc938f8bbdf'

CHECKPOINTS = (360,180,120,60,45,30,20,15,10,5,3,1)
EXIT_COST_STRESS_CENTS = 2
EXIT_COST_CENTS = 2

def canonical(rows,window_entries=False):
    picked = {}
    for row in rows:
        check_priority()
        key = (row['date'], row['ticker'], int(row['minutes_before_close'])) + ((row['price_band'],) if window_entries else ())
        if key not in picked or float(row['maker_bid']) > float(picked[key]['maker_bid']):
            picked[key] = row
    return list(picked.values())

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

def analyze_risk(rows, paths, asset, include_snapshots=False, compact=False, window_entries=False):
    saved = canonical(rows,window_entries)
    representatives = {}
    eligible = 0
    # Older archives have checkpoint entry quotes but no full candle sidecar.
    # Reuse only an actually saved quote for this SAME contract and side.
    # Never infer a bid from the opposite side's bid.
    saved_quotes = defaultdict(list)
    for r in rows:
        check_priority()
        try:
            close = int(dt.datetime.fromisoformat(r['close_time'].replace('Z', '+00:00')).timestamp())
            age = float(r.get('quote_age_seconds') or 0)
            bid = 100 * float(r['maker_bid'])
            ts = r['quote_period_ts'] if window_entries else close - 60*int(r['minutes_before_close']) - age
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
        check_priority()
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
        check_priority()
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
            if compact and decision==next((t for t in CHECKPOINTS if t<=minute/2),None):
                grid[group]  # Preserve empty policy cells when no exit quote exists.
            try:
                close = int(path['close_ts']) if path is not None else int(dt.datetime.fromisoformat(r['close_time'].replace('Z', '+00:00')).timestamp())
            except (KeyError, ValueError, TypeError):
                continue
            target = close - 60*decision
            entry_ts=r.get('entry_ts',close-60*minute) if window_entries else close-60*minute
            if target<=entry_ts:continue
            bid = None
            source = 'minute_path'
            if path is not None:
                bars, times = path_cache[path_key]
                index = bisect_right(times, target) - 1
                if index >= 0:
                    b = bars[index]
                    if 0 <= target-int(b[0]) <= 60 and int(b[0]) > entry_ts:
                        bid = b[1 if r['side'] == 'yes' else 2]
            if bid is None:
                quotes, times = quote_index.get((r['date'], r['ticker'], r['side']), ([], []))
                index = bisect_right(times, target) - 1
                if index >= 0 and 0 <= target-times[index] <= 60 and times[index] > entry_ts:
                    bid = quotes[index][1]
                    source = 'saved_checkpoint'
            if not isinstance(bid, (int, float)) or not math.isfinite(bid) or not 0 <= bid <= 100:
                continue
            # Reports consume only the pinned policy checkpoint, not the diagnostic
            # per-checkpoint bins. Coverage still counts EVERY observed checkpoint.
            if not compact or decision==next((t for t in CHECKPOINTS if t<=minute/2),None):
                grid[group].append({'event': event, 'bid': bid, 'won': int(r['won']),
                                    'entry': 100*float(r['maker_bid']), 'source': source,
                                    'key': (r['date'], r['ticker'], minute) + ((band,) if window_entries else ()), 'close_ts': close, 'decision_ts': target})
            covered.add(key)
    records = []
    for (family, minute, band, decision), count in (sorted(requested.items()) if not compact else []):
        items = grid[(family, minute, band, decision)]
        bins = summarize(items)
        records.append({'asset': asset, 'family': family, 'minutes_before_close': minute,
                        'price_band_cents': band, 'decision_minutes_remaining': decision,
                        'eligible_events': count, 'observed_events': len(items),
                        'saved_checkpoint_events': sum(x['source'] == 'saved_checkpoint' for x in items),
                        'bins': bins, 'boundary': boundary(bins)})
    result = {'records': records, 'saved_observations': len(saved),
            'eligible_entry_observations': eligible, 'event_entry_groups': len(representatives),
            'covered_event_entry_groups': len(covered),
            'note': 'Counts are distinct event representatives within each entry category/checkpoint; rows reuse events. Older checkpoint-only archives save 50–100-cent quotes, so their lower-price coverage is incomplete. No opposite-side bid is converted into a sale bid. Missing quotes are excluded, not interpreted as safe holding.'}

    if include_snapshots:
        result['_snapshot_groups'] = grid
    return result

def fit_threshold(items):
    """Weighted decreasing binomial fit; interpolate an observed 50% crossing."""
    grouped = defaultdict(list)
    for item in items:
        grouped[min(90, int(item['bid']//10)*10)].append(item)
    points = [{'low': low, 'n': len(group), 'losses': sum(1-x['won'] for x in group),
               'bid': sum(x['bid'] for x in group)/len(group)} for low, group in sorted(grouped.items())]
    blocks = []
    for i, p in enumerate(points):
        blocks.append({'first': i, 'last': i, 'n': p['n'], 'losses': p['losses']})
        while len(blocks) > 1 and blocks[-2]['losses']/blocks[-2]['n'] < blocks[-1]['losses']/blocks[-1]['n']:
            a, b = blocks[-2:]
            blocks[-2:] = [{'first': a['first'], 'last': b['last'], 'n': a['n']+b['n'], 'losses': a['losses']+b['losses']}]
    for b in blocks:
        for i in range(b['first'], b['last']+1):
            points[i]['risk'] = b['losses']/b['n']
    entry = sum(x['entry'] for x in items)/len(items) if items else 0
    for a, b in zip(points, points[1:]):
        if a['risk'] > .5 >= b['risk']:
            if b['low']-a['low'] != 10 or a['bid'] <= 0 or b['bid'] <= a['bid']:
                return None
            value = math.floor(a['bid']+(b['bid']-a['bid'])*(a['risk']-.5)/(a['risk']-b['risk'])+.5)
            return value if 0 < value < entry else None
    return None

def replay(items, threshold):
    """One later checkpoint per position. An observed bid is the sale price."""
    exits = [x for x in items if threshold is not None and 0 < x['bid'] <= threshold and x['bid'] < x['entry']]
    return {'covered_observations': len(items) if threshold is not None else 0,
            'early_exits': len(exits), 'missed_recoveries': sum(x['won'] for x in exits),
            # The common entry cost cancels exactly; charge only the added sale.
            'total_delta_cents': round(sum(x['bid']-EXIT_COST_CENTS-100*x['won'] for x in exits), 6)}

def policy_cells(groups, latest_keys=None):
    cells = defaultdict(list)
    for (family, minute, band, decision), items in groups.items():
        checkpoint = next((t for t in CHECKPOINTS if t <= minute/2), None)
        if decision == checkpoint:
            cells[(minute, band)].extend(items)
    historical, latest = [], []
    for (minute, band), candidates in sorted(cells.items()):
        check_priority()
        # The same event cannot become independent by appearing in two series.
        representatives = {}
        for x in candidates:
            rank = (-x['entry'], x['key'])
            if x['event'] not in representatives or rank < representatives[x['event']][0]:
                representatives[x['event']] = (rank, x)
        items = sorted((x for _, x in representatives.values()), key=lambda x: (x['close_ts'], x['event']))
        def study(cohort):
            train, test, cutoff = [], [], None
            if len(cohort) >= 2:
                split = max(1, min(len(cohort)-1, int(len(cohort)*.7)))
                cutoff = cohort[split-1]['close_ts']
                train = [x for x in cohort if x['close_ts'] <= cutoff]
                test = [x for x in cohort if x['decision_ts'] > cutoff]
            frozen = fit_threshold(train)
            display = frozen if frozen is not None else fit_threshold(cohort)
            base = {'minutes_before_close': minute, 'price_band_cents': band,
                    'threshold_cents': display, 'threshold_source': 'earlier-events' if frozen is not None else 'descriptive-only',
                    'decision_minutes_remaining': next(t for t in CHECKPOINTS if t <= minute/2),
                    'training_events': len(train), 'training_cutoff_ts': cutoff,
                    'replay_available': frozen is not None and bool(test)}
            return base, test, frozen
        base, test, frozen = study(items)
        historical.append(dict(base, **replay(test, frozen)))
        latest_items = [x for x in items if latest_keys is not None and x['key'] in latest_keys]
        if latest_items:
            # A latest collection may concern OLD dates. Exclude all later
            # historical outcomes from its training as well as its ROI replay.
            end = max(x['close_ts'] for x in latest_items)
            base, test, frozen = study([x for x in items if x['close_ts'] <= end])
        subset = [x for x in test if latest_keys is not None and x['key'] in latest_keys]
        latest.append(dict(base, **replay(subset, frozen), latest_membership_known=latest_keys is not None))
    return historical, latest
