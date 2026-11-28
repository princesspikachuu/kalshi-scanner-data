"""Bounded read-only inventory of *verified supplied* Favorites audit events.

Never infer a win, settlement, investment return, or an all-time evidence
sample from a single diagnostic or partial source page. Source pages must be
verified independently, then reconciled by original UUID before this audit.
"""
from collections import Counter

from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, reconcile_verified_pages,
)

KINDS = frozenset((
    'FAVORITE_ENTRY_COHORT', 'FAVORITE_TRIAL_QUALITY',
    'FAVORITE_ENTRY_DECISION', 'FAVORITE_REPEAT_OPPORTUNITY',
    'FAVORITE_STAT_DECISION', 'SETTLED',
))
MAX_ORIGINALS = 256


def summarize_supplied_favorites_evidence(pages):
    """Return an explicitly partial presence inventory, never statistical P/L.

    A SETTLED audit line by itself does not establish which favorite cohort
    closed, validity, the entry basis, or the realized net P/L. Matching
    tickers are a review aid only and never transformed into outcome samples.
    """
    result = reconcile_verified_pages(pages)
    if result['unique_events'] > MAX_ORIGINALS:
        raise HistoryReconciliationError('Favorites audit exceeds bounded page budget')
    counts = Counter()
    tickers_by_kind = {kind:set() for kind in KINDS}
    missing_ticker = Counter()
    for item in result['items']:
        progress = item.get('progress')
        if not isinstance(progress,dict):
            raise HistoryReconciliationError('Original Favorites progress missing')
        kind = progress.get('event')
        if kind not in KINDS:
            continue
        counts[kind] += 1
        ticker = progress.get('ticker')
        if isinstance(ticker,str) and 0 < len(ticker) <= 140:
            tickers_by_kind[kind].add(ticker)
        else:
            missing_ticker[kind] += 1
    cohort_tickers = tickers_by_kind['FAVORITE_ENTRY_COHORT']
    settlement_tickers = tickers_by_kind['SETTLED']
    quality_tickers = tickers_by_kind['FAVORITE_TRIAL_QUALITY']
    all_seen = sorted(cohort_tickers | settlement_tickers | quality_tickers)
    return dict(
        contract='mt019-favorites-evidence-presence-v1',
        input_original_events=result['input_events'],
        unique_original_events=result['unique_events'],
        duplicate_source_copies=result['duplicate_copies'],
        event_kind_counts={kind:counts[kind] for kind in sorted(KINDS)},
        distinct_cohort_tickers=len(cohort_tickers),
        distinct_settlement_tickers=len(settlement_tickers),
        distinct_quality_tickers=len(quality_tickers),
        candidate_ticker_links=dict(
            cohort_and_settlement=len(cohort_tickers & settlement_tickers),
            cohort_and_quality=len(cohort_tickers & quality_tickers),
            all_three=len(cohort_tickers & settlement_tickers & quality_tickers),
            cohort_without_supplied_settlement=len(cohort_tickers - settlement_tickers),
            settlement_without_supplied_cohort=len(settlement_tickers - cohort_tickers),
        ),
        missing_ticker_by_kind={kind:missing_ticker[kind] for kind in sorted(KINDS)},
        observed_relevant_tickers=len(all_seen),
        # Even a complete inventory of these event types is insufficient
        # to reconstruct cash cost/fees, confirmed payouts or independent
        # resolved market event outcomes. Never promote into strategy cells.
        financial_reconciliation_complete=False,
        authoritative_outcome_samples=0,
        source_exhaustion_verified=False,
        all_time_coverage_complete=False,
        safe_to_train=False,
        real_orders_enabled=False,
    )
