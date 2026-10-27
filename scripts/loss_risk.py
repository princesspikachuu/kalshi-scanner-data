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


def analyze_risk(rows, paths, asset, include_snapshots=False):
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
                                'entry': 100*float(r['maker_bid']), 'source': source,
                                'key': (r['date'], r['ticker'], minute), 'close_ts': close, 'decision_ts': target})
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
    result = {'records': records, 'saved_observations': len(saved),
            'eligible_entry_observations': eligible, 'event_entry_groups': len(representatives),
            'covered_event_entry_groups': len(covered),
            'note': 'Counts are distinct event representatives within each entry category/checkpoint; rows reuse events. Older checkpoint-only archives save 50–100-cent quotes, so their lower-price coverage is incomplete. No opposite-side bid is converted into a sale bid. Missing quotes are excluded, not interpreted as safe holding.'}

    if include_snapshots:
        result['_snapshot_groups'] = grid
    return result


def latest_membership(asset, rows):
    """Use exact saved run membership; never assign historical exits to a new run."""
    import os
    from loss_prevention import canonical
    from build_report import read_rows
    stage = Path(os.environ.get('POCKET_COLLECTION_STAGE', '.run-collection')) / asset
    target = Path('backtests/LATEST_MEMBERSHIP.json')
    membership = json.loads(target.read_text()) if target.exists() else {}
    meta_path = Path('backtests/LATEST_METADATA.json')
    meta = json.loads(meta_path.read_text()).get(asset, {}) if meta_path.exists() else {}
    run_id = meta.get('run_id')
    if stage.exists():
        keys = sorted((r['date'], r['ticker'], int(r['minutes_before_close'])) for r in canonical(read_rows(stage)))
        membership[asset] = {'run_id': run_id, 'keys': keys}
        target.write_text(json.dumps(membership, separators=(',', ':'))+'\n')
        return {tuple(k) for k in keys}
    cached = membership.get(asset, {})
    if isinstance(cached, dict) and run_id and cached.get('run_id') == run_id:
        return {tuple(k) for k in cached['keys']}
    # Recover an older full-date run only when its complete saved rows match
    # both run metadata and every published entry cell. Otherwise leave unknown.
    meta_path = Path('backtests/LATEST_METADATA.json')
    grid_path = Path('backtests/LATEST_BY_CATEGORY.csv')
    if not meta_path.exists() or not grid_path.exists():
        return None
    import csv
    from build_report import distinct_markets_at_time, metrics
    meta = json.loads(meta_path.read_text()).get(asset, {})
    dates = (meta.get('first_date'), meta.get('last_date'))
    if not all(dates):
        return None
    selected = [r for r in rows if dates[0] <= r['date'] <= dates[1]]
    if len(selected) != meta.get('total_observations') or len({(r['date'],r['ticker']) for r in selected}) != meta.get('markets_sampled_total'):
        return None
    with grid_path.open() as stream:
        expected = [r for r in csv.DictReader(stream) if r['asset'] == asset]
    if not expected:
        return None
    for r in expected:
        subset = [x for x in distinct_markets_at_time(selected, int(r['minutes_before_close'])) if x['price_band'] == r['price_band_cents']]
        m = metrics(subset)
        if not m or m['n'] != int(r['sampled_markets']) or m['wins'] != int(r['wins']) or abs(m['avg_price_cents']-float(r['average_purchase_price_cents'])) > .00011:
            return None
    keys = {(r['date'],r['ticker'],int(r['minutes_before_close'])) for r in canonical(selected)}
    membership[asset] = {'run_id': run_id, 'keys': sorted(keys)}
    target.write_text(json.dumps(membership, separators=(',', ':'))+'\n')
    return keys


def build_risk_report():
    from build_report import ASSETS, read_rows
    from loss_prevention import read_paths
    report = {'version': 2, 'model': 'conditional-outcome-v2', 'roi_policy_version': 1,
              'published_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'exit_cost_stress_cents': EXIT_COST_STRESS_CENTS,
              'historical': {}, 'latest': {},
              'method': 'Category-level 50% conditional-loss threshold from an event-weighted monotone fit. Freeze on earlier events and replay one later checkpoint on later nonoverlapping events. Paired actual-bid sale-minus-hold differences only; missed recoveries and a 2-cent exit-cost stress included. Full original sample retained. Exploratory simulated results, not verified fills or a validated live edge. Remaining-time checkpoint is automatically at or before half the original entry window. No full-future-path requirement.'}
    for asset, _, folder, _, _ in ASSETS:
        rows = read_rows(folder)
        scope = analyze_risk(rows, read_paths(folder), asset, include_snapshots=True)
        from loss_policy import policy_cells
        latest_keys = latest_membership(asset, rows)
        historical_cells, latest_cells = policy_cells(scope.pop('_snapshot_groups'), latest_keys)
        # Publish compact table summaries, not thousands of unused bin details.
        scope.pop('records')
        from build_report import distinct_markets_at_time, metrics
        for cell in historical_cells:
            selected = [r for r in distinct_markets_at_time(rows, cell['minutes_before_close']) if r['price_band'] == cell['price_band_cents']]
            m = metrics(selected)
            if m:
                cell.update(base_n=m['n'], base_wins=m['wins'], base_price_cents=round(m['avg_price_cents'],4))
        import csv
        latest_grid = Path('backtests/LATEST_BY_CATEGORY.csv')
        latest_base = {}
        if latest_grid.exists():
            with latest_grid.open() as stream:
                latest_base = {(int(r['minutes_before_close']), r['price_band_cents']): r for r in csv.DictReader(stream) if r['asset'] == asset}
        for cell in latest_cells:
            base = latest_base.get((cell['minutes_before_close'],cell['price_band_cents']))
            if base:
                cell.update(base_n=int(base['sampled_markets']), base_wins=int(base['wins']), base_price_cents=float(base['average_purchase_price_cents']))
        meta_path = Path('backtests/LATEST_METADATA.json')
        latest_meta = json.loads(meta_path.read_text()).get(asset,{}) if meta_path.exists() else {}
        scope['policy_cells'] = historical_cells
        report['historical'][asset] = scope
        report['latest'][asset] = {'policy_cells': latest_cells, 'run_id': latest_meta.get('run_id'), 'latest_membership_known': latest_keys is not None}
    Path('backtests/LOSS_PREVENTION.json').write_text(json.dumps(report, separators=(',', ':'), allow_nan=False) + '\n')
    print('Published conditional loss thresholds and later-event paired exit results.')
