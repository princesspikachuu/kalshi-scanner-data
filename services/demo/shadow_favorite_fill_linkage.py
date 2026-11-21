"""Bounded linkage of original Favorites cohorts to original paper FILL audits.

This is provenance checking of already verified source pages, not an
authoritative settlement, cash ledger, all-time statistical reconstruction,
or production strategy input. There are no database/R2/network operations.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation

from services.demo.shadow_favorite_cohort_forensics import inspect_original_cohort
from services.demo.shadow_history_reconcile import (
    HistoryReconciliationError, reconcile_verified_pages,
)

MAX_ORIGINALS = 256
TIME_TOLERANCE = Decimal('0.000002')


def _number(value, field, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise HistoryReconciliationError('Invalid audited ' + field)
    if isinstance(value, str) and (not value or len(value) > 64):
        raise HistoryReconciliationError('Invalid audited ' + field)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise HistoryReconciliationError('Invalid audited ' + field) from exc
    if (not number.is_finite() or number < 0 or
            (positive and number == 0) or number > Decimal('1e15')):
        raise HistoryReconciliationError('Invalid audited ' + field)
    return number


def _ticker(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 140:
        raise HistoryReconciliationError('Missing audited ticker')
    return value


def _original_buy_fill(event):
    p = event['progress']
    if p.get('action') not in ('buy', 'sell'):
        raise HistoryReconciliationError('Invalid original fill action')
    if p['action'] != 'buy':
        return None
    order_id = p.get('order_id')
    if not isinstance(order_id, str) or not 1 <= len(order_id) <= 150:
        raise HistoryReconciliationError('Missing paper fill order identifier')
    side = p.get('side')
    if side not in ('yes', 'no'):
        raise HistoryReconciliationError('Invalid original fill side')
    price = _number(p.get('price'), 'fill price', positive=True)
    if price >= 1:
        raise HistoryReconciliationError('Invalid original fill price')
    return dict(id=event['id'], order_id=order_id,
                ticker=_ticker(p.get('ticker')), side=side,
                quantity=_number(p.get('quantity'), 'fill quantity', positive=True),
                price=price, fee=_number(p.get('fee'), 'fill fee'),
                at=_number(p.get('time'), 'fill time'))


def inspect_supplied_favorite_fill_links(pages):
    """Match only unambiguous *supplied* original FILL and cohort audit rows.

    Matching on order ID alone is unsafe: one order can have multiple partial
    fills. An exact link requires the same ticker, side, filled quantity,
    executed price, fee and near-identical audit time, and is unique in both
    directions. No missing event is treated as proof no fill occurred.
    """
    evidence = reconcile_verified_pages(pages)
    if evidence['unique_events'] > MAX_ORIGINALS:
        raise HistoryReconciliationError('Favorites audit exceeded bounded budget')
    cohorts = []
    for item in evidence['items']:
        p = item['progress']
        if p.get('event') == 'FAVORITE_ENTRY_COHORT':
            inspected = inspect_original_cohort(item)
            cohorts.append(dict(id=item['id'], order_id=inspected['order_id'],
                                ticker=_ticker(p.get('ticker')),
                                side=p.get('side'),
                                quantity=_number(inspected['quantity'], 'cohort quantity',
                                                 positive=True),
                                price=_number(inspected['price'], 'cohort price',positive=True),
                                fee=_number(p.get('fee'), 'cohort fee'),
                                at=_number(inspected['original_at'], 'cohort time'),
                                entry_fresh=inspected['entry_fresh']))
    order_ids = {item['order_id'] for item in cohorts}
    fills = []
    for item in evidence['items']:
        p = item['progress']
        if p.get('event') != 'FILL':
            continue
        oid = p.get('order_id')
        if not isinstance(oid, str):
            raise HistoryReconciliationError('Invalid original paper fill order ID')
        if oid in order_ids:
            parsed = _original_buy_fill(item)
            if parsed is not None:
                fills.append(parsed)
    candidates = []
    for cohort in cohorts:
        matches = [fill for fill in fills if
                   fill['order_id'] == cohort['order_id'] and
                   fill['ticker'] == cohort['ticker'] and
                   fill['side'] == cohort['side'] and
                   fill['quantity'] == cohort['quantity'] and
                   fill['price'] == cohort['price'] and
                   fill['fee'] == cohort['fee'] and
                   abs(fill['at'] - cohort['at']) <= TIME_TOLERANCE]
        candidates.append(matches)
    use_counts = Counter(fill['id'] for matches in candidates for fill in matches)
    links = []
    unmatched = ambiguous = 0
    for cohort, matches in zip(cohorts, candidates):
        if not matches:
            unmatched += 1
        elif len(matches) != 1 or use_counts[matches[0]['id']] != 1:
            ambiguous += 1
        else:
            fill = matches[0]
            links.append(dict(cohort_original_id=cohort['id'],
                              fill_original_id=fill['id'],
                              order_id=cohort['order_id'],ticker=cohort['ticker'],
                              side=cohort['side'],quantity=str(cohort['quantity']),
                              executed_price=str(cohort['price']),
                              entry_fee=str(cohort['fee']),
                              entry_fresh=cohort['entry_fresh']))
    return dict(contract='mt019-supplied-favorite-fill-linkage-v1',
                source_original_copies=evidence['input_events'],
                unique_original_events=evidence['unique_events'],
                duplicate_source_copies=evidence['duplicate_copies'],
                supplied_cohorts=len(cohorts),
                relevant_supplied_buy_fills=len(fills),
                unambiguous_fill_links=len(links),
                unmatched_cohorts_in_supplied_pages=unmatched,
                ambiguous_cohorts_in_supplied_pages=ambiguous,
                matched_originals=links,
                # Evidence pairings are diagnostic, never trade settlement
                # or independent market outcome samples.
                authoritative_settlement_verified=False,
                realized_pnl_reconciled=False,
                authoritative_outcome_samples=0,
                source_exhaustion_verified=False,
                all_time_coverage_complete=False,
                eligible_for_learning=False,
                safe_to_train=False,
                real_orders_enabled=False)
