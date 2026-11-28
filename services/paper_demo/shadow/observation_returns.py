"""Fee-inclusive event return attribution; pooled ROI is deliberately separate."""
from decimal import Decimal as D


def merge(target, source):
    for event, value in source.items():
        row = target.setdefault(event, dict(cost='0', net='0'))
        if value.get('estimated'):row['estimated']=True
        for field in ('cost', 'net'):
            row[field] = str(D(row[field]) + D(value[field]))


def summarize(events):
    values = [D(row['net']) / D(row['cost']) for row in events.values() if D(row['cost']) > 0]
    return dict(estimated_return_observations=sum(bool(row.get('estimated')) for row in events.values() if D(row['cost'])>0),
                return_observations=len(values), return_sum=str(sum(values, D(0))),
                average_return_pct=str(100 * sum(values, D(0)) / len(values)) if values else None)


def summarize_regular_held_events(events):
    """Regular Favorites-only event-based held-ROI uncertainty for a cohort.

    Caller has already pooled cost and hypothetical settlement net by *event*
    within this price/time cell. Preserve summarize() fields and the exact
    50-event, 90%-Student-t methodology used by the Single view. This is NOT
    a confidence test on contracts, entry fills, calendar days, or on the
    many different candidate cohorts selected after inspecting their results.
    """
    from .favorite_single import (
        _finite_decimal, _report, MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
    )
    base = summarize(events)
    normalized = {}
    for event, value in events.items():
        if not isinstance(value, dict):
            continue
        cost = _finite_decimal(value.get('cost'))
        net = _finite_decimal(value.get('net'))
        if cost is None or net is None or cost <= 0:
            continue
        normalized[str(event)] = dict(
            outcome=0, cost=cost, net=net,
            missing=False, estimated=bool(value.get('estimated')),
        )
    stats = _report(normalized, MIN_HOLD_RETURN_UNCERTAINTY_EVENTS)
    n = stats['return_observations']
    # The existing event count / mean are canonical; never silently create
    # additional pseudo-observations from unverified aggregate statistics.
    if n != base['return_observations']:
        return dict(base, uncertainty90_pct=None, ci90_low_pct=None,
                    ci90_high_pct=None,
                    uncertainty_min_samples=MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
                    roi_interval_status='inconsistent_event_attribution')
    if n < MIN_HOLD_RETURN_UNCERTAINTY_EVENTS:
        status = 'under_minimum'
    elif stats['uncertainty90_pct'] is None:
        status = 'insufficient_gain_loss_variation'
    else:
        status = 'available'
    return dict(
        base,
        uncertainty90_pct=stats['uncertainty90_pct'],
        ci90_low_pct=stats['ci90_low_pct'],
        ci90_high_pct=stats['ci90_high_pct'],
        uncertainty_min_samples=MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
        roi_interval_status=status,
    )
