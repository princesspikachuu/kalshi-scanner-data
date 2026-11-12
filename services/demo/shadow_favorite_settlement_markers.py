"""Read-only diagnostic matching of linked Favorites fills to paper settlement markers.

A paper SETTLED log is neither an exchange-authenticated payout nor
position-level realized P/L. This validator never upgrades statistics.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from services.demo.shadow_favorite_fill_linkage import inspect_supplied_favorite_fill_links
from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, reconcile_verified_pages,
)


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (str,int,float)):
        raise HistoryReconciliationError('Invalid paper settlement '+field)
    if isinstance(value,str) and (not value or len(value)>64):
        raise HistoryReconciliationError('Invalid paper settlement '+field)
    try:
        number=Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HistoryReconciliationError('Invalid paper settlement '+field) from exc
    if not number.is_finite() or number<0 or number>Decimal('1e15'):
        raise HistoryReconciliationError('Invalid paper settlement '+field)
    return number


def inspect_supplied_favorite_settlement_markers(pages):
    """Find candidate paper SETTLED markers for unambiguously linked entries.

    Source verification, UUID de-duplication, and 1:1 cohort/FILL matching
    are required. A single later paper settlement marker is only a review
    lead, *never* a financial statement or a training sample.
    """
    linked=inspect_supplied_favorite_fill_links(pages)
    reconciled=reconcile_verified_pages(pages)
    by_id={item['id']:item for item in reconciled['items']}
    entry_by_ticker=defaultdict(list)
    for match in linked['matched_originals']:
        origin=by_id[match['cohort_original_id']]['progress']
        at=_number(origin.get('time'),'linked entry time')
        entry_by_ticker[match['ticker']].append(
            dict(cohort_id=match['cohort_original_id'],
                 original_fill_id=match['fill_original_id'],
                 entry_time=at))
    markers=defaultdict(list)
    for item in reconciled['items']:
        p=item['progress']
        if p.get('event')!='SETTLED':
            continue
        ticker=p.get('ticker')
        if ticker not in entry_by_ticker:
            continue
        payout=_number(p.get('price'),'yes payout')
        if payout>1:
            raise HistoryReconciliationError('Invalid paper settlement payout')
        at=_number(p.get('time'),'event time')
        markers[ticker].append(dict(
            original_id=item['id'],at=at,payout=payout))
    results=[]
    candidate=missing=ambiguous=0
    for ticker in sorted(entry_by_ticker):
        entries=entry_by_ticker[ticker]
        latest_entry=max(x['entry_time'] for x in entries)
        observed=markers[ticker]
        eligible=[x for x in observed if x['at']>=latest_entry]
        reason='candidate_paper_marker_only'
        if not observed:
            missing+=1
            reason='not_in_supplied_pages'
        elif len(observed)!=1:
            ambiguous+=1
            reason='multiple_paper_settlement_markers'
        elif not eligible:
            ambiguous+=1
            reason='paper_marker_precedes_linked_entry'
        else:
            candidate+=1
        results.append(dict(
            ticker=ticker,
            linked_entry_count=len(entries),
            supplied_paper_marker_count=len(observed),
            marker_original_ids=sorted(x['original_id'] for x in observed),
            candidate_paper_yes_payout=(str(eligible[0]['payout'])
                 if reason=='candidate_paper_marker_only' else None),
            evidence_status=reason,
            authoritative_settlement_verified=False,
            realized_pnl_reconciled=False,
            eligible_for_learning=False))
    return dict(contract='mt019-favorites-supplied-paper-settlement-marker-v1',
                unique_original_events=reconciled['unique_events'],
                linked_entry_fills=linked['unambiguous_fill_links'],
                linked_market_tickers=len(results),
                candidate_paper_settlement_tickers=candidate,
                missing_paper_marker_tickers_in_supplied_pages=missing,
                ambiguous_paper_marker_tickers=ambiguous,
                market_review_leads=results,
                paper_marker_is_not_exchange_verified=True,
                lots_and_partial_exits_reconciled=False,
                authoritative_settlement_verified=False,
                authoritative_outcome_samples=0,
                realized_pnl_reconciled=False,
                all_time_coverage_complete=False,
                source_exhaustion_verified=False,
                safe_to_train=False,
                real_orders_enabled=False)
