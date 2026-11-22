"""MT-033: forward-date, read-only validation for preselected REGULAR Favorites cells.

These four exploratory coordinates were frozen before any 2026-11-23
exchange-event labels. This is a strict forward-*label* check, not a claim
that Kalshi's event labels are authoritative settlement/first-observation
timestamps. Raw event IDs never leave this module.

No calendar-day *sample-size* gate. One exchange event is one ROI sample
within each fixed cell; repeated entry fills and bot overlap are pooled.
"""
from decimal import Decimal as D

from .favorite_event_correlation import event_date_label
from .favorite_single import (
    _collect, _report, MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
)

CUTOFF_EVENT_DATE = '2026-11-22'
FROZEN_COHORTS = (
    ('commodities-15m', 70, '10–15m'),
    ('commodities-15m', 75, '10–15m'),
    ('crypto-15m', 70, '5–10m'),
    ('finance-15m', 75, '10–15m'),
)


def summarize_forward_regular_favorites(held_bots, profiles, category_for):
    """Measure only new independently settled venue events in frozen cells.

    Call from the existing minute-rate API report on already-derived held
    Favorites data. Never query DB/R2, mutate observations or move money.
    Missing/invalid/unparseable labels cannot be placed into the holdout.
    """
    events = {coordinate: {} for coordinate in FROZEN_COHORTS}
    skipped = {coordinate: dict(unparseable=0, historical=0) for coordinate in FROZEN_COHORTS}
    # An event appearing more than once in this cell is pooled, not counted twice.
    for bot_id, metric in (held_bots or {}).items():
        if not isinstance(metric, dict):
            continue
        profile = (profiles or {}).get(str(bot_id), {})
        if not isinstance(profile, dict) or not profile:
            continue
        category = category_for(profile)
        for row in metric.get('entry_timing') or ():
            if not isinstance(row, dict):
                continue
            try:
                price = D(str(row.get('price')))
                if not price.is_finite() or not D('.70') <= price <= D('.95'):
                    continue
                band = int(price * 100 // 5) * 5
            except (ValueError, TypeError, ArithmeticError):
                continue
            coordinate = (category, band, row.get('horizon'))
            if coordinate not in events:
                continue
            source = row.get('outcome_events')
            if not isinstance(source, dict) or not source:
                continue
            accepted = {}
            for event, outcome in source.items():
                if outcome not in (0, 1, '0', '1'):
                    continue
                date = event_date_label(str(event))
                if date is None:
                    skipped[coordinate]['unparseable'] += 1
                elif date <= CUTOFF_EVENT_DATE:
                    skipped[coordinate]['historical'] += 1
                else:
                    accepted[event] = outcome
            if accepted:
                # _collect handles incomplete return attribution, fee-inclusive
                # event pooling, and estimated historical event-cost flags.
                _collect(events[coordinate], dict(
                    outcome_events=accepted,
                    return_events=row.get('return_events'),
                ))

    output = []
    for category, band, horizon in FROZEN_COHORTS:
        coord = (category, band, horizon)
        report = _report(events[coord], MIN_HOLD_RETURN_UNCERTAINTY_EVENTS)
        n = report['return_observations']
        low, high = report['ci90_low_pct'], report['ci90_high_pct']
        state = ('under_minimum' if n < MIN_HOLD_RETURN_UNCERTAINTY_EVENTS
                 else 'insufficient_gain_loss_variation' if low is None or high is None
                 else 'available')
        output.append(dict(
            category=category, price_band_cents=band, time_bucket=horizon,
            resolved_events=report['resolved_events'],
            independent_held_return_events=n,
            incomplete_settled_events=report['incomplete_events'],
            estimated_held_return_events=report['estimated_return_observations'],
            held_roi_mean_pct=report['average_return_pct'],
            held_roi_ci90_low_pct=low if state == 'available' else None,
            held_roi_ci90_high_pct=high if state == 'available' else None,
            held_roi_uncertainty90_pp=(report['uncertainty90_pct']
                                       if state == 'available' else None),
            confidence_status=state,
            need_to_minimum=max(0, MIN_HOLD_RETURN_UNCERTAINTY_EVENTS - n),
            historical_cohort_appearances_excluded=skipped[coord]['historical'],
            unparseable_cohort_appearances_excluded=skipped[coord]['unparseable'],
        ))
    return dict(
        basis='regular_favorites_forward_event_date_proxy',
        frozen_as_of='2026-11-21',
        holdout_event_label_after=CUTOFF_EVENT_DATE,
        confidence_target=MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
        note=('Forward venue date-label proxy, not first-seen or settlement time; '
              'nominal event-based 90pct Student-t, not multiple-testing adjusted. '
              'No calendar-day sample requirement.'),
        cells=output,
    )
