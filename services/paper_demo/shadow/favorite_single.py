"""Single-bucket Favorites hold-return evidence, pooled by independent event.

All verified entry timing cohorts are eligible (including rows whose legacy
timestamps cannot be placed in a 3x3 bin). This does not affect paper orders,
wallet accounting or the existing detailed/wide research summaries.
"""
from decimal import Decimal as D, InvalidOperation

# Two-sided 90% Student t critical values for small samples (df 1..30).
T90 = (
    '6.3138', '2.9200', '2.3534', '2.1318', '2.0150', '1.9432',
    '1.8946', '1.8595', '1.8331', '1.8125', '1.7959', '1.7823',
    '1.7709', '1.7613', '1.7531', '1.7459', '1.7396', '1.7341',
    '1.7291', '1.7247', '1.7207', '1.7171', '1.7139', '1.7109',
    '1.7081', '1.7056', '1.7033', '1.7011', '1.6991', '1.6973',
)


def _finite_decimal(value):
    try:
        number = D(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _critical90(df):
    if df <= len(T90):
        return D(T90[df - 1])
    z = D('1.6448536269514722')
    n = D(df)
    # Standard t-quantile expansion, accurate beyond 30 degrees of freedom.
    return z + (z**3 + z) / (4*n) + (5*z**5 + 16*z**3 + 3*z) / (96*n*n)


def _collect(target, row):
    """Every resolved event counts once; add costs and hold returns across bins."""
    outcomes = row.get('outcome_events')
    if not isinstance(outcomes, dict):
        return
    attributed = row.get('return_events')
    attributed = attributed if isinstance(attributed, dict) else {}
    for event, outcome in outcomes.items():
        if outcome not in (0, 1, '0', '1'):
            continue
        key = str(event)
        result = target.setdefault(key, {
            'outcome': 1, 'cost': D(0), 'net': D(0),
            'missing': False, 'estimated': False
        })
        result['outcome'] = min(result['outcome'], int(outcome))
        value = attributed.get(event)
        if not isinstance(value, dict):
            result['missing'] = True
            continue
        cost = _finite_decimal(value.get('cost'))
        net = _finite_decimal(value.get('net'))
        if cost is None or cost <= 0 or net is None:
            result['missing'] = True
            continue
        result['cost'] += cost
        result['net'] += net
        result['estimated'] |= bool(value.get('estimated'))


def _report(events):
    resolved = len(events)
    return_events = [event for event in events.values()
                     if not event['missing'] and event['cost'] > 0]
    returns = [event['net'] / event['cost'] for event in return_events]
    n = len(returns)
    result = dict(
        resolved_events=resolved,
        event_wins=sum(event['outcome'] for event in events.values()),
        return_observations=n,
        incomplete_events=resolved - n,
        estimated_return_observations=sum(event['estimated'] for event in return_events),
        average_return_pct=None, uncertainty90_pct=None,
        ci90_low_pct=None, ci90_high_pct=None,
    )
    if not n:
        return result
    mean = sum(returns, D(0)) / D(n)
    result['average_return_pct'] = str(100 * mean)
    if n > 1:
        sample_var = sum(((value - mean) ** 2 for value in returns), D(0)) / D(n - 1)
        # A zero sample variance is not zero future uncertainty: identical
        # binary-event returns can still be followed by the opposite outcome.
        # Even price-varying all-winner returns do not show the risk of a
        # losing event. Only estimate t uncertainty after both gains and
        # losses have been observed. Keep the
        # P/L observed mean, but do not present a fabricated ±0% error bar.
        if sample_var > 0 and any(value > 0 for value in returns) and any(value < 0 for value in returns):
            error = _critical90(n - 1) * (sample_var / D(n)).sqrt()
            result.update(
                uncertainty90_pct=str(100 * error),
                ci90_low_pct=str(100 * (mean - error)),
                ci90_high_pct=str(100 * (mean + error)),
            )
    return result


def summarize_single(folder_bots, profiles, category_for):
    """Compact, event-deduplicated ROI, keyed by category and by market bot."""
    categories, per_bot = {}, {}
    for bot_id, metric in folder_bots.items():
        profile = profiles.get(str(bot_id), {})
        if not profile or not isinstance(metric, dict):
            continue
        kind = category_for(profile)
        category_events = categories.setdefault(kind, {})
        bot_events = {}
        for row in metric.get('entry_timing') or []:
            if not isinstance(row, dict):
                continue
            _collect(category_events, row)
            _collect(bot_events, row)
        per_bot[str(bot_id)] = _report(bot_events)
    return dict(rows={kind: _report(events) for kind, events in categories.items()},
                by_bot=per_bot)


def summarize_statistics_holds(sources, profiles):
    """Read-only Favorites/statistics ROI evidence, separate from trade decisions.

    Resolve each event once in an exact five-cent/entry-time cohort and once
    across all cohorts of its market type. Only explicit hold-only return
    attribution qualifies for ROI; old realized exit P/L is never substituted.
    An outcome with incomplete return attribution remains visible as missing
    evidence rather than becoming a win, loss, or invented zero return.
    """
    from .favorite_statistics import PRICE_BUCKETS, TIME_BUCKETS, price_bucket

    category_events, cells = {}, {}
    for folder_bots in sources:
        if not isinstance(folder_bots, dict):
            continue
        for bot_id, bot in folder_bots.items():
            if not isinstance(bot, dict) or not isinstance(profiles.get(str(bot_id)), dict):
                continue
            for row in bot.get('entry_timing') or []:
                if not isinstance(row, dict):
                    continue
                market_type = row.get('market_type')
                time = row.get('horizon')
                price = _finite_decimal(row.get('price'))
                if not isinstance(market_type, str) or not market_type or time not in TIME_BUCKETS:
                    continue
                if price is None or not D('.70') <= price <= D('.95'):
                    continue
                bucket = price_bucket(price)
                if bucket not in PRICE_BUCKETS:
                    continue
                # Not all old "return_events" are settlement-based. Never use
                # those exit-altered values as evidence for a held trade.
                eligible = row if row.get('return_policy') == 'hold_only' else dict(row, return_events={})
                _collect(category_events.setdefault(market_type, {}), eligible)
                _collect(cells.setdefault((market_type, bucket, time), {}), eligible)

    by_cell = {}
    for (market_type, bucket, time), events in cells.items():
        by_cell.setdefault(market_type, {})[bucket + '|' + time] = _report(events)
    return dict(by_market_type={key: _report(events) for key, events in category_events.items()},
                by_cell=by_cell, basis='verified_hold_only', confidence=90)
