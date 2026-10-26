#!/usr/bin/env python3
"""Downside exits from minute-close bid paths; never verified order fills."""
import csv
import datetime as dt
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from decimal import Decimal, InvalidOperation

ENTRY_FEE_CENTS = 1.0
EXIT_FEE_CENTS = 2.0
THRESHOLDS = tuple(range(5, 96, 5))
MIN_TRAIN_DAYS = 5
MIN_TEST_DAYS = 2


def bid_cents(candle, side):
    def price(name, quote):
        value = candle.get(name + '_' + quote) or {}
        raw = value.get('close_dollars', value.get('close'))
        try:
            number = Decimal(str(raw)) * 100
            return float(number) if number.is_finite() and 0 <= number <= 100 else None
        except (InvalidOperation, TypeError, ValueError):
            return None
    result = price(side, 'bid')
    if result is None and side == 'no':
        ask = price('yes', 'ask')
        result = 100 - ask if ask is not None else None
    return result


def pack_path(bars, close):
    """Keep nulls and zero bids: unknown quotes differ from an empty bid book."""
    return {'close_ts': close, 'bars': sorted(
        [[int(c['end_period_ts']), bid_cents(c, 'yes'), bid_cents(c, 'no')]
         for c in bars if c.get('end_period_ts') is not None], key=lambda v: v[0])}


def canonical(rows):
    picked = {}
    for row in rows:
        key = (row['date'], row['ticker'], int(row['minutes_before_close']))
        if key not in picked or float(row['maker_bid']) > float(picked[key]['maker_bid']):
            picked[key] = row
    return list(picked.values())


def scenario(row, path):
    """Reject gaps before using a path; detect exits only AFTER entry, before close."""
    if path is None or int(row.get('quote_age_seconds') or 0) > 60:
        return None
    close = int(path['close_ts'])
    target = close - 60 * int(row['minutes_before_close'])
    column = 1 if row['side'] == 'yes' else 2
    quotes = {int(b[0]): b[column] for b in path['bars']}
    timestamps = list(range((target // 60 + 1) * 60, close, 60))
    if any(ts not in quotes or quotes[ts] is None for ts in timestamps):
        return None
    entry = 100 * float(row['maker_bid'])
    hold = 100 * int(row['won']) - entry - ENTRY_FEE_CENTS
    exits = {}
    # Absolute downside price thresholds, at/below the lower bound of the
    # original entry band, so the policy cannot become a profit target.
    for threshold in THRESHOLDS:
        if threshold > int(row['price_band'].split('-')[0]):
            continue
        hit = next(((ts, quotes[ts]) for ts in timestamps
                    if 0 < quotes[ts] <= threshold and quotes[ts] < entry), None)
        exits[threshold] = (hit[1] - entry - ENTRY_FEE_CENTS - EXIT_FEE_CENTS,
                            hit[1], (close - hit[0]) / 60) if hit else (hold, None, None)
    return {'row': row, 'entry': entry, 'hold': hold, 'exits': exits,
            'key': (row['date'], row['ticker'], int(row['minutes_before_close']))}


def improvement(item, threshold):
    return item['exits'][threshold][0] - item['hold']


def independent_stats(items, threshold):
    """Cluster gains by UTC date and event instead of treating strikes as independent."""
    clusters = defaultdict(list)
    for item in items:
        row = item['row']
        clusters[(row['date'], row.get('event_ticker') or row['ticker'])].append(improvement(item, threshold))
    values = [sum(v) / len(v) for v in clusters.values()]
    mean = sum(values) / len(values) if values else 0
    se = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1) / len(values)) if len(values) > 1 else float('inf')
    return {'events': len(values), 'lower_bound': mean - 1.96 * se,
            'gain': sum(improvement(x, threshold) for x in items) / len(items) if items else 0,
            'triggers': sum(x['exits'][threshold][1] is not None for x in items),
            'markets': len({(x['row']['date'], x['row']['ticker']) for x in items})}


def choose_rule(items):
    days = sorted({x['row']['date'] for x in items})
    info = {'supported': False, 'threshold_cents': None, 'candidate_cents': None,
            'path_observations': len(items), 'path_days': len(days)}
    if len(days) < MIN_TRAIN_DAYS + MIN_TEST_DAYS:
        info['reason'] = 'Need at least 7 price-path days (5 training + 2 later validation).'
        return info, [], []
    split = min(len(days) - MIN_TEST_DAYS, max(MIN_TRAIN_DAYS, int(len(days) * .7)))
    train = [x for x in items if x['row']['date'] < days[split]]
    test = [x for x in items if x['row']['date'] >= days[split]]
    info.update({'training_last_date': days[split - 1], 'validation_first_date': days[split],
                 'training_n': len(train), 'validation_n': len(test)})
    candidates = []
    for threshold in items[0]['exits']:
        stats = independent_stats(train, threshold)
        if stats['markets'] >= 30 and stats['events'] >= 10 and stats['triggers'] >= 10 and stats['lower_bound'] > 0:
            candidates.append((stats['gain'], -threshold, threshold))
    if not candidates:
        info['reason'] = 'No downside threshold has enough positive training evidence.'
        return info, train, test
    # Choose only on training. Never try another candidate on validation failure.
    threshold = max(candidates)[2]
    stats = independent_stats(test, threshold)
    info.update({'candidate_cents': threshold, 'validation_gain_cents': round(stats['gain'], 4),
                 'validation_triggers': stats['triggers'], 'validation_events': stats['events']})
    if stats['markets'] < 15 or stats['events'] < 5 or stats['triggers'] < 5 or stats['lower_bound'] <= 0:
        info['reason'] = 'Training candidate did not pass later validation; continue holding.'
        return info, train, test
    info.update({'supported': True, 'threshold_cents': threshold,
                 'reason': 'Passed chronological held-out validation under the stated fee scenario.'})
    return info, train, test


def read_paths(folder):
    out = {}
    for filename in sorted(folder.glob('????-??-??.paths.json')):
        day = filename.name[:10]
        for ticker, path in json.loads(filename.read_text()).items():
            out[(day, ticker)] = path
    return out


def analyze(rows, paths, asset, latest_keys=None):
    saved = canonical(rows)
    groups = defaultdict(list)
    prepared = []
    for row in saved:
        item = scenario(row, paths.get((row['date'], row['ticker'])))
        if item is not None:
            prepared.append(item)
            family = row.get('weather_type') or row['series']
            groups[(family, int(row['minutes_before_close']), row['price_band'])].append(item)
    rules = []
    evaluated = []
    for (family, minute, band), items in sorted(groups.items()):
        rule, train, test = choose_rule(items)
        rule.update({'family': family, 'minutes_before_close': minute, 'price_band_cents': band})
        rules.append(rule)
        # If dates are insufficient, show a matched hold baseline only.
        # Once split, exclude training observations from every comparison.
        for item in (test if train else items):
            threshold = rule['threshold_cents']
            outcome = item['exits'][threshold] if rule['supported'] else (item['hold'], None, None)
            evaluated.append((item, outcome, rule))

    def scope(keys=None):
        selected = [(x, outcome, rule) for x, outcome, rule in evaluated if keys is None or x['key'] in keys]
        grid = defaultdict(list)
        for x, outcome, rule in selected:
            grid[(rule['family'], int(x['row']['minutes_before_close']), x['row']['price_band'])].append((x, outcome, rule))
        records = []
        for (family, minute, band), items in sorted(grid.items()):
            n = len(items)
            strategy = sum(outcome[0] for x, outcome, rule in items)
            hold = sum(x['hold'] for x, outcome, rule in items)
            invested = sum(x['entry'] + ENTRY_FEE_CENTS for x, outcome, rule in items)
            exits = [(x, outcome) for x, outcome, rule in items if outcome[1] is not None]
            records.append({'asset': asset, 'family': family, 'minutes_before_close': minute, 'price_band_cents': band,
                'sampled_markets': n, 'sampled_days': len({x['row']['date'] for x, _, _ in items}),
                'wins': sum(outcome[0] > 0 for _, outcome, _ in items),
                'hold_wins': sum(x['hold'] > 0 for x, _, _ in items),
                'sampled_dates': sorted({x['row']['date'] for x, _, _ in items}),
                'win_rate_percent': round(100 * sum(outcome[0] > 0 for _, outcome, _ in items) / n, 4),
                'average_purchase_price_cents': round(sum(x['entry'] for x, _, _ in items) / n, 4),
                'average_profit_loss_cents_per_contract': round(strategy / n, 4),
                'hold_net_cents': round(hold / n, 4), 'improvement_cents': round((strategy - hold) / n, 4),
                'hypothetical_roi_percent': round(100 * strategy / invested, 4),
                'early_exits': len(exits), 'missed_recoveries': sum(int(x['row']['won']) == 1 for x, _ in exits),
                'loss_reduction_cents': round(sum(max(0, outcome[0] - x['hold']) for x, outcome in exits), 4),
                'supported_thresholds': sorted({rule['threshold_cents'] for _, _, rule in items if rule['supported']}),
                'families': sorted({rule['family'] for _, _, rule in items})})
        chosen = [x for x in prepared if keys is None or x['key'] in keys]
        requested = [r for r in saved if keys is None or (r['date'], r['ticker'], int(r['minutes_before_close'])) in keys]
        return {'records': records, 'rules': rules, 'saved_observations': len(requested),
            'path_observations': len(chosen), 'comparison_observations': len(selected),
            'days_sampled': len({x['row']['date'] for x, _, _ in selected}),
            'markets_sampled_total': len({(x['row']['date'], x['row']['ticker']) for x, _, _ in selected}),
            'first_date': min((x['row']['date'] for x, _, _ in selected), default=None),
            'last_date': max((x['row']['date'] for x, _, _ in selected), default=None)}
    return scope(), scope(latest_keys) if latest_keys is not None else None


def build_loss_report():
    from build_report import ASSETS, read_rows
    target = Path('backtests/LOSS_PREVENTION.json')
    previous = json.loads(target.read_text()) if target.exists() else {}
    result = {'version': 1, 'historical': {}, 'latest': previous.get('latest', {}),
        'entry_fee_cents': ENTRY_FEE_CENTS, 'exit_fee_cents': EXIT_FEE_CENTS,
        'threshold_step_cents': 5, 'published_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'method': 'One-contract minute-close bid simulation; entry fill assumed; no depth, queue, latency or slippage replay. Fee stress is 1 cent entry and 2 cents per early sale, not verified market fees. Triggers are evaluated after entry, strictly before close. Missing paths excluded. Thresholds selected on earlier dates and evaluated only on later dates; training rows excluded from comparison once split. Exploratory validation is not proof of a live edge.'}
    stage = Path(os.environ.get('POCKET_COLLECTION_STAGE', '.run-collection'))
    for asset, _, folder, _, _ in ASSETS:
        rows = read_rows(folder)
        latest_rows = read_rows(stage / asset)
        latest_keys = {(r['date'], r['ticker'], int(r['minutes_before_close'])) for r in canonical(latest_rows)} if (stage / asset).exists() else None
        historical, latest = analyze(rows, read_paths(folder), asset, latest_keys)
        result['historical'][asset] = historical
        if latest is not None:
            result['latest'][asset] = latest
        else:
            result['latest'].setdefault(asset, {'records': [], 'rules': [], 'path_observations': 0})
    target.write_text(json.dumps(result, separators=(',', ':'), allow_nan=False) + '\n')
    print('Published loss-prevention comparison; only collected quote paths are eligible.')

if __name__ == '__main__':
    build_loss_report()
