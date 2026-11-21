"""Bounded, read-only coverage telemetry for REGULAR High-Probability Favorites.

Use already-computed dashboard aggregates, never scan SQL/history/R2 and never
report event IDs, market tickers, financial account balances or individual orders.
Detailed/Wider are *cohort* counts; their sums are NOT independent event counts.
Only the Single category view deduplicates an event across all price/time cohorts.
"""
from decimal import Decimal as D, InvalidOperation
from services.paper_demo.shadow.favorite_single import MIN_HOLD_RETURN_UNCERTAINTY_EVENTS


def _finite(value):
    try:
        number = D(str(value))
        return number if number.is_finite() else None
    except (ValueError, TypeError, ArithmeticError, InvalidOperation):
        return None


def _count(value):
    number = _finite(value)
    if number is None or number < 0 or number != number.to_integral_value():
        return 0
    return int(number)


def _percent(value):
    number = _finite(value)
    if number is None:
        return None
    try:
        return str(number.quantize(D('.01')))
    except ArithmeticError:
        return None


def _source_coverage(held_bots, profiles, category_for):
    """Count *cohort rows*, including sources that lack known event identities.

    A cohort row can overlap another; it must NEVER be represented as an
    independent market event or included in an uncertainty denominator.
    """
    result = {}
    for bot_id, metric in held_bots.items():
        profile = profiles.get(str(bot_id))
        if not isinstance(profile, dict) or not isinstance(metric, dict):
            continue
        category = category_for(profile)
        cell = result.setdefault(category, dict(
            entry_cohort_rows=0, entry_cohorts_without_confirmed_outcome=0,
            legacy_claimed_resolved_without_event_ids=0))
        rows = metric.get('entry_timing')
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or (_finite(row.get('contracts')) or D(0)) <= 0:
                continue
            cell['entry_cohort_rows'] += 1
            known = row.get('outcome_events')
            if isinstance(known, dict) and known:
                continue
            cell['entry_cohorts_without_confirmed_outcome'] += 1
            if ((_finite(row.get('resolved')) or D(0)) > 0
                    or (_finite(row.get('events')) or D(0)) > 0):
                cell['legacy_claimed_resolved_without_event_ids'] += 1
    return result


def summarize_regular_favorites_coverage(
    timed, wide, single, *, held_bots=None, profiles=None, category_for=None,
):
    """Return tiny audit evidence computed from one same-snapshot Favorites view.

    This is reporting, not a new profitability model. It does not aggregate
    market-type/cell samples as if they were independent across time or price.
    Numeric 90% bounds inherit the approximate Student-t assumptions from
    summarize_single; correlated events may still make them optimistic.
    """
    timed_rows = (timed or {}).get('rows') or {}
    timed_coverage = (timed or {}).get('coverage') or {}
    wide_rows = (wide or {}).get('rows') or {}
    wide_coverage = (wide or {}).get('coverage') or {}
    single_rows = (single or {}).get('rows') or {}
    origin = (_source_coverage(held_bots, profiles, category_for)
              if held_bots is not None and profiles is not None
              and category_for is not None else {})
    minimum = MIN_HOLD_RETURN_UNCERTAINTY_EVENTS
    categories = sorted(set(timed_coverage) | set(single_rows)
                        | set(wide_rows) | set(origin))
    output = {}
    for category in categories:
        summary = single_rows.get(category) or {}
        coverage = timed_coverage.get(category) or {}
        wide_details = wide_coverage.get(category) or {}
        detailed = [r for r in timed_rows.get(category, [])
                    if isinstance(r, dict)]
        wider = [r for r in wide_rows.get(category, [])
                 if isinstance(r, dict)]
        resolved = _count(summary.get('resolved_events'))
        returns = _count(summary.get('return_observations'))
        estimated = _count(summary.get('estimated_return_observations'))
        incomplete = _count(summary.get('incomplete_events'))
        low = _finite(summary.get('ci90_low_pct'))
        high = _finite(summary.get('ci90_high_pct'))
        if returns < minimum:
            confidence = 'under_minimum'
        elif low is None or high is None:
            confidence = 'no_numerical_interval'
        elif low > 0:
            confidence = 'nominal_interval_above_zero'
        elif high < 0:
            confidence = 'nominal_interval_below_zero'
        else:
            confidence = 'nominal_interval_overlaps_zero'
        sampled = sorted(
            (row for row in detailed if _count(row.get('return_observations')) > 0),
            key=lambda row: (-_count(row.get('return_observations')),
                             -_count(row.get('events')), str(row.get('price')),
                             str(row.get('horizon'))),
        )[:3]
        flags = []
        if returns > resolved or estimated > returns or incomplete != max(0, resolved - returns):
            flags.append('invalid_single_evidence_counts')
        if (resolved > 0 and not any(_count(r.get('events')) for r in detailed)):
            flags.append('resolved_events_not_placed_in_detailed')
        output[category] = dict(
            bots_total=_count(coverage.get('bots_total')),
            bots_with_timing_records=_count(coverage.get('bots_with_rows')),
            independent_resolved_events=resolved,
            independent_held_return_events=returns,
            incomplete_settled_events=incomplete,
            estimated_held_return_events=estimated,
            need_to_minimum=max(0, minimum-returns),
            held_roi_mean_pct=_percent(summary.get('average_return_pct')),
            ci90_low_pct=_percent(low), ci90_high_pct=_percent(high),
            confidence_state=confidence,
            detailed_cells_with_events=sum(_count(r.get('events'))>0 for r in detailed),
            detailed_cohort_event_appearances=sum(_count(r.get('events')) for r in detailed),
            detailed_cohort_return_appearances=sum(_count(r.get('return_observations')) for r in detailed),
            wider_cells_with_events=sum(_count(r.get('events'))>0 for r in wider),
            wider_cohort_event_appearances=sum(_count(r.get('events')) for r in wider),
            wider_legacy_cohort_exclusions=_count(wide_details.get('excluded_legacy_observations')),
            wider_price_cohort_exclusions=_count(wide_details.get('excluded_price_observations')),
            top_sampled_detailed_cohorts=[
                dict(entry_price=str(r.get('price')),time_bucket=str(r.get('horizon')),
                     settled_cohort_events=_count(r.get('events')),
                     cohort_held_returns=_count(r.get('return_observations')),
                     need_to_minimum=max(0,minimum-_count(r.get('return_observations'))),
                     mean_held_roi_pct=_percent(r.get('average_return_pct')))
                for r in sampled
            ],
            **origin.get(category, dict(
                entry_cohort_rows=0,entry_cohorts_without_confirmed_outcome=0,
                legacy_claimed_resolved_without_event_ids=0)),
            flags=flags,
        )
    return dict(
        basis='regular_favorites_derived_held_returns',
        independent_event_source='single_category_deduplicated',
        confidence_target=minimum,
        confidence_note='approximate_90pct_student_t_not_correlated_adjusted',
        detailed_and_wider_counts='cohort_appearances_not_independent',
        categories=output,
    )
