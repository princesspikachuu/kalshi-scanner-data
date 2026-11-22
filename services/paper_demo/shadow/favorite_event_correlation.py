"""Read-only dependence audit for REGULAR High Probability Favorites events.

An exchange event is the unit of observation, even if many entry fills, prices,
thresholds or bots share that event. A *different* exchange event on the same
encoded calendar date may still be correlated with other events on that date.
Date is a dependence proxy, NOT proof of a settlement date or independence
between dates.

Run only on the already-derived regular Favorites held research view, at the
existing once-per-minute workspace diagnostic cadence. No SQL, R2, account,
settlement, order or worker operations. Raw ticker/event IDs NEVER leave here.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal as D
import re

from .favorite_single import (
    _collect, _critical90, _report, MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
)

_MONTHS = ('JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
           'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC')
_EVENT_DATE = re.compile(
    r'(?:^|[-_])(?P<year>[0-9]{2})(?P<mon>JAN|FEB|MAR|APR|MAY|JUN|'
    r'JUL|AUG|SEP|OCT|NOV|DEC)(?P<day>[0-9]{2})'
    r'(?P<compact_close_hhmm>[0-9]{4})?(?![0-9])'
)
_MIN_DAY_CLUSTERS = 20
_MIN_PARSE_COVERAGE = D('.80')


def event_date_label(event):
    """Parse an exchange event's YYMONDD label; never guess an unknown date.

    These are event labels (e.g. KXHIGHNY-26NOV20 or
    KXBTC15M-26NOV021815), not authoritative outcome timestamps.
    Short-window Kalshi event tickers append HHMM directly to YYMONDD;
    validate that HHMM and reject extra digits rather than discarding
    every valid compact-time event. A venue
    event without a reliably valid label stays unknown and out of day-CI.
    """
    if not isinstance(event, str):
        return None
    match = _EVENT_DATE.search(event.strip().upper())
    if not match:
        return None
    compact = match.group('compact_close_hhmm')
    if compact is not None and (int(compact[:2]) > 23 or int(compact[2:]) > 59):
        return None
    try:
        value = date(2000 + int(match.group('year')),
                     1 + _MONTHS.index(match.group('mon')),
                     int(match.group('day')))
        return value.isoformat()
    except ValueError:
        return None


def _format_pct(value):
    if value is None:
        return None
    try:
        return str(value.quantize(D('.01')))
    except ArithmeticError:
        return None


def _event_returns(events):
    result = {}
    for event_id, value in events.items():
        if value['missing'] or value['cost'] <= 0:
            continue
        ratio = value['net'] / value['cost']
        if ratio.is_finite():
            result[event_id] = ratio
    return result


def _category_report(events):
    held = _event_returns(events)
    n = len(held)
    dated = defaultdict(list)
    for event, ratio in held.items():
        label = event_date_label(event)
        if label is not None:
            dated[label].append(ratio)

    dated_n = sum(map(len, dated.values()))
    cluster_count = len(dated)
    overlap_n = sum(len(values) for values in dated.values() if len(values) > 1)
    largest = max((len(values) for values in dated.values()), default=0)
    fraction = D(dated_n) / D(n) if n else D(0)
    positives = any(v > 0 for values in dated.values() for v in values)
    negatives = any(v < 0 for values in dated.values() for v in values)
    status = 'available'
    ci_low = ci_high = halfwidth = ratio_of_errors = None

    # Compute the nominal i.i.d. t interval over the SAME date-parseable
    # subset. Comparing it with the cluster-adjusted interval for a different
    # set would confound parsing exclusions with dependence.
    dated_events = {
        event: events[event] for event in held
        if event_date_label(event) is not None
    }
    nominal = _report(dated_events, MIN_HOLD_RETURN_UNCERTAINTY_EVENTS)
    if n < MIN_HOLD_RETURN_UNCERTAINTY_EVENTS:
        status = 'under_50_events'
    elif fraction < _MIN_PARSE_COVERAGE:
        status = 'less_than_80pct_date_coverage'
    elif dated_n < MIN_HOLD_RETURN_UNCERTAINTY_EVENTS:
        status = 'under_50_dated_events'
    elif cluster_count < _MIN_DAY_CLUSTERS:
        status = 'under_20_date_clusters'
    elif not (positives and negatives):
        status = 'no_observed_gain_and_loss'
    else:
        total = sum((v for values in dated.values() for v in values), D(0))
        mean = total / D(dated_n)
        # CR1 cluster sandwich for an event-equal intercept-only mean:
        # Var(mu) = [G/(G-1)] * Sum_g (Sum_i_in_g (r_i - mu))^2 / n^2.
        # Requires independent DAY clusters; within-day covariance arbitrary.
        # Does not correct for between-day correlation, nonrandom selection or
        # estimated historical event costs/payouts.
        contributions = [
            sum((value - mean for value in values), D(0))
            for values in dated.values()
        ]
        variance = (
            D(cluster_count) / D(cluster_count - 1)
            * sum((x*x for x in contributions), D(0))
            / D(dated_n * dated_n)
        )
        if variance <= 0:
            status = 'no_day_cluster_variance'
        else:
            error = _critical90(cluster_count - 1) * variance.sqrt()
            ci_low = _format_pct(100*(mean - error))
            ci_high = _format_pct(100*(mean + error))
            halfwidth = _format_pct(100*error)
            iid = nominal.get('uncertainty90_pct')
            if iid is not None and D(iid) > 0:
                ratio_of_errors = _format_pct(10000*error/D(iid))
    return dict(
        independent_settled_return_events=n,
        with_parseable_event_date=dated_n,
        without_parseable_event_date=n-dated_n,
        event_date_coverage_pct=_format_pct(100*fraction),
        distinct_event_dates=cluster_count,
        largest_date_event_count=largest,
        largest_date_share_pct=_format_pct(
            D(100*largest)/D(dated_n) if dated_n else D(0)),
        events_in_multi_event_dates=overlap_n,
        nominal_90pct_error_dated_subset_pp=(
            _format_pct(D(nominal['uncertainty90_pct']))
            if nominal.get('uncertainty90_pct') is not None else None),
        cluster_90pct_error_pp=halfwidth,
        cluster_90pct_low_roi_pct=ci_low,
        cluster_90pct_high_roi_pct=ci_high,
        cluster_vs_iid_error_ratio_pct=ratio_of_errors,
        cluster_interval_status=status,
    )


def summarize_regular_favorites_event_correlation(
    held_bots, profiles, category_for, *, known_single=None,
):
    """Sanitized category-level dependence diagnostics, without any raw IDs.

    Do not use this as a new trading signal. The nominal and cluster estimates
    assume different dependence models, and the latter is computed only on
    fully date-parseable events with enough calendar clusters.
    """
    categories = {}
    for bot_id, metrics in (held_bots or {}).items():
        profile = (profiles or {}).get(str(bot_id))
        if not isinstance(profile, dict) or not isinstance(metrics, dict):
            continue
        category = category_for(profile)
        target = categories.setdefault(category, {})
        rows = metrics.get('entry_timing')
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                _collect(target, row)

    event_memberships = defaultdict(set)
    output = {}
    expected = ((known_single or {}).get('rows') or {})
    for category, events in sorted(categories.items()):
        for event in events:
            event_memberships[event].add(category)
        report = _category_report(events)
        # Correlation is a separate sensitivity from the MT-027 mean-ROI
        # split: preserve the whole event's estimated classification and test
        # dependence within each attribution tier, without rewriting either.
        exact_events = {event: value for event, value in events.items()
                        if not value['missing'] and value['cost'] > 0
                        and not value['estimated']}
        estimated_events = {event: value for event, value in events.items()
                            if not value['missing'] and value['cost'] > 0
                            and value['estimated']}
        cluster_fields = (
            'independent_settled_return_events', 'with_parseable_event_date',
            'event_date_coverage_pct', 'distinct_event_dates',
            'cluster_interval_status', 'cluster_90pct_error_pp',
            'cluster_90pct_low_roi_pct', 'cluster_90pct_high_roi_pct',
        )
        exact_cluster = _category_report(exact_events)
        estimated_cluster = _category_report(estimated_events)
        report['attribution_date_clusters'] = {
            'exact_only': {key: exact_cluster[key] for key in cluster_fields},
            'estimated_only': {key: estimated_cluster[key] for key in cluster_fields},
        }
        prior = expected.get(category)
        flags = []
        if (report['independent_settled_return_events'] !=
                exact_cluster['independent_settled_return_events'] +
                estimated_cluster['independent_settled_return_events']):
            flags.append('attribution_date_cluster_counts_do_not_reconcile')
        if isinstance(prior, dict):
            if report['independent_settled_return_events'] != int(
                    prior.get('return_observations') or 0):
                flags.append('different_from_single_deduplicated_return_events')
        output[category] = dict(report, flags=flags)

    cross = sum(len(owners) > 1 for owners in event_memberships.values())
    repeated = sum(len(owners) - 1 for owners in event_memberships.values())
    return dict(
        basis='regular_favorites_held_events_same_snapshot',
        repeat_identity_unit='exchange_event_not_entry_contract_or_cohort',
        time_cluster_proxy='date_code_in_venue_event_ticker_not_settlement_timestamp',
        interval_assumption='within_date_arbitrary; between_dates_uncorrelated',
        min_dated_return_events=MIN_HOLD_RETURN_UNCERTAINTY_EVENTS,
        min_date_clusters=_MIN_DAY_CLUSTERS,
        min_date_coverage_pct=80,
        distinct_event_identities_across_categories=len(event_memberships),
        event_ids_shared_between_categories=cross,
        excess_cross_category_event_appearances=repeated,
        categories=output,
        note='Descriptive dependence sensitivity; not a trading confidence claim. '
             'No adjustment for estimated return bias, regime changes, '
             'between-date dependence or nonrandom entry selection.',
    )
