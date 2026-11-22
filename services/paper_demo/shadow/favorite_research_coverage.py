"""Bounded, read-only coverage telemetry for REGULAR High-Probability Favorites.

Use already-computed dashboard aggregates, never scan SQL/history/R2 and never
report event IDs, market tickers, financial account balances or individual orders.
Detailed/Wider are *cohort* counts; their sums are NOT independent event counts.
Only the Single category view deduplicates an event across all price/time cohorts.
"""
from decimal import Decimal as D, InvalidOperation
from services.paper_demo.shadow.favorite_single import (
    MIN_HOLD_RETURN_UNCERTAINTY_EVENTS, summarize_regular_attribution_subsets,
)


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


def _sensitivity_subset(report):
    """Bounded, identifier-free description of an observed return subset."""
    count = _count(report.get('return_observations'))
    low = (_finite(report.get('ci90_low_pct'))
           if count >= MIN_HOLD_RETURN_UNCERTAINTY_EVENTS else None)
    high = (_finite(report.get('ci90_high_pct'))
            if count >= MIN_HOLD_RETURN_UNCERTAINTY_EVENTS else None)
    if count < MIN_HOLD_RETURN_UNCERTAINTY_EVENTS:
        state = 'under_minimum'
    elif low is None or high is None:
        state = 'no_numerical_interval'
    elif low > 0:
        state = 'nominal_interval_above_zero'
    elif high < 0:
        state = 'nominal_interval_below_zero'
    else:
        state = 'nominal_interval_overlaps_zero'
    return dict(
        independent_held_return_events=count,
        positive_return_events=_count(report.get('positive_return_events')),
        negative_return_events=_count(report.get('negative_return_events')),
        zero_return_events=_count(report.get('zero_return_events')),
        held_roi_mean_pct=_percent(report.get('average_return_pct')),
        ci90_low_pct=_percent(low), ci90_high_pct=_percent(high),
        confidence_state=state,
        need_to_minimum=max(0, MIN_HOLD_RETURN_UNCERTAINTY_EVENTS-count),
    )


def _top_price_time_cohort(row, minimum):
    """Sanitized bounded cell evidence; never report stale sub-50 ROI bounds."""
    n = _count(row.get('return_observations'))
    raw_status = str(row.get('roi_interval_status') or 'not_available')
    status = 'under_minimum' if n < minimum else raw_status
    low = _finite(row.get('ci90_low_pct'))
    high = _finite(row.get('ci90_high_pct'))
    err = _finite(row.get('uncertainty90_pct'))
    valid = (status == 'available' and low is not None and high is not None
             and low <= high and err is not None and err >= 0)
    if status == 'available' and not valid:
        status = 'not_available'
    return dict(
        entry_price=str(row.get('price')), time_bucket=str(row.get('horizon')),
        settled_cohort_events=_count(row.get('events')),
        cohort_held_returns=n,
        estimated_cohort_held_returns=_count(row.get('estimated_return_observations')),
        need_to_minimum=max(0, minimum-n),
        mean_held_roi_pct=_percent(row.get('average_return_pct')),
        held_roi_interval_status=status,
        held_roi_uncertainty90_pp=_percent(err) if valid else None,
        held_roi_ci90_low_pct=_percent(low) if valid else None,
        held_roi_ci90_high_pct=_percent(high) if valid else None,
    )


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
    subsets = (summarize_regular_attribution_subsets(held_bots, profiles, category_for)
               if held_bots is not None and profiles is not None
               and category_for is not None else None)
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
                _top_price_time_cohort(r, minimum) for r in sampled
            ],
            **origin.get(category, dict(
                entry_cohort_rows=0,entry_cohorts_without_confirmed_outcome=0,
                legacy_claimed_resolved_without_event_ids=0)),
            flags=flags,
        )
        if subsets is not None:
            split = subsets.get(category) or {}
            exact = _sensitivity_subset(split.get('exact_only') or {})
            estimated_only = _sensitivity_subset(split.get('estimated_only') or {})
            if (exact['independent_held_return_events']
                    + estimated_only['independent_held_return_events'] != returns):
                flags.append('attribution_subsets_do_not_reconcile')
            if estimated_only['independent_held_return_events'] != estimated:
                flags.append('estimated_attribution_subsets_do_not_reconcile')
            output[category]['attribution_sensitivity'] = dict(
                exact_only=exact, estimated_only=estimated_only,
            )
    return dict(
        basis='regular_favorites_derived_held_returns',
        independent_event_source='single_category_deduplicated',
        confidence_target=minimum,
        confidence_note='approximate_90pct_student_t_not_correlated_adjusted',
        attribution_note='exact_only_means_no_cohort_flagged_estimated; nonrandom_subsets_not_correlation_adjusted',
        detailed_and_wider_counts='cohort_appearances_not_independent',
        categories=output,
    )
