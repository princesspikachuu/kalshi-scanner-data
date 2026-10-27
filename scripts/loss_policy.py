"""Frozen checkpoint exits with a paired, later-event return overlay."""
import math
from collections import defaultdict

EXIT_COST_CENTS = 2


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
    from loss_risk import CHECKPOINTS
    cells = defaultdict(list)
    for (family, minute, band, decision), items in groups.items():
        checkpoint = next((t for t in CHECKPOINTS if t <= minute/2), None)
        if decision == checkpoint:
            cells[(minute, band)].extend(items)
    historical, latest = [], []
    for (minute, band), candidates in sorted(cells.items()):
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
