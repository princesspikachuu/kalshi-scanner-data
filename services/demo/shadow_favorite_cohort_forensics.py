"""Strict, no-I/O forensic checks for preserved FAVORITE_ENTRY_COHORT logs.

A validated audit cohort is not an authoritative completed trade or
independent event outcome. No P/L aggregation or strategy mutations occur.
"""
import json
from decimal import Decimal, InvalidOperation

from services.demo.shadow_history_reconcile import HistoryReconciliationError

MAX_DETAILS_BYTES=8192
MANDATORY=('key','at','price','quantity','remaining','cost',
           'remaining_cost','verified','order_id')


def _decimal(value, field, *, strictly_positive=False):
    if isinstance(value,bool) or not isinstance(value,(str,int,float)):
        raise HistoryReconciliationError('Invalid cohort '+field)
    if isinstance(value,str) and (len(value)>64 or not value):
        raise HistoryReconciliationError('Invalid cohort '+field)
    try:
        parsed=Decimal(str(value))
    except (ValueError,InvalidOperation) as exc:
        raise HistoryReconciliationError('Invalid cohort '+field) from exc
    if not parsed.is_finite() or parsed<0 or (strictly_positive and parsed<=0):
        raise HistoryReconciliationError('Invalid cohort '+field)
    return parsed


def inspect_original_cohort(original):
    if not isinstance(original,dict):
        raise HistoryReconciliationError('Invalid original cohort')
    progress=original.get('progress')
    if not isinstance(progress,dict) or progress.get('event')!='FAVORITE_ENTRY_COHORT':
        raise HistoryReconciliationError('Not a Favorites entry cohort')
    raw_details=progress.get('details')
    if not isinstance(raw_details,str) or not 1<=len(raw_details)<=MAX_DETAILS_BYTES:
        raise HistoryReconciliationError('Invalid Favorites cohort details')
    try:
        chunk=json.loads(raw_details,parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError('Nonfinite cohort number')))
    except (ValueError,TypeError,RecursionError) as exc:
        raise HistoryReconciliationError('Malformed Favorites cohort details') from exc
    if not isinstance(chunk,dict) or any(k not in chunk for k in MANDATORY):
        raise HistoryReconciliationError('Incomplete Favorites cohort details')
    if chunk['verified'] is not True and chunk['verified'] is not False:
        raise HistoryReconciliationError('Cohort verification flag malformed')
    if not isinstance(chunk['key'],str) or not chunk['key'].startswith(
            ('entry-v2|','paper-data-v3|entry-v2|')):
        raise HistoryReconciliationError('Unsupported cohort entry key')
    parts=chunk['key'].removeprefix('paper-data-v3|').split('|')
    if (len(parts)!=6 or parts[0]!='entry-v2'
            or parts[2] not in ('yes','no')
            or parts[5] not in ('market_close','estimated_game_end')):
        raise HistoryReconciliationError('Malformed Favorites cohort entry dimensions')
    if progress.get('side') != parts[2]:
        raise HistoryReconciliationError('Cohort entry side disagrees with order audit')
    if not isinstance(chunk['order_id'],str) or not 1<=len(chunk['order_id'])<=150:
        raise HistoryReconciliationError('Missing original paper order ID')
    quantity=_decimal(chunk['quantity'],'quantity',strictly_positive=True)
    remaining=_decimal(chunk['remaining'],'remaining')
    price=_decimal(chunk['price'],'price',strictly_positive=True)
    cost=_decimal(chunk['cost'],'cost',strictly_positive=True)
    remaining_cost=_decimal(chunk['remaining_cost'],'remaining_cost')
    at=_decimal(chunk['at'],'time')
    fee=_decimal(progress.get('fee'),'fee')
    logged_at=_decimal(progress.get('time'),'audited event time')
    if abs(at-logged_at)>Decimal('0.000002'):
        raise HistoryReconciliationError('Cohort time disagrees with original audit')
    audited_quantity=_decimal(progress.get('quantity'),'audited quantity',strictly_positive=True)
    audited_price=_decimal(progress.get('price'),'audited price',strictly_positive=True)
    if (quantity!=audited_quantity or price!=audited_price or price>=1 or
            not (price*100).to_integral_value()==price*100 or
            parts[3]!=str(int(price*100)) or
            remaining>quantity or remaining_cost>cost or
            cost!=quantity*price+fee):
        raise HistoryReconciliationError('Cohort does not match original audited fill')
    if not isinstance(progress.get('order_id'),str) or progress['order_id']!=chunk['order_id']:
        raise HistoryReconciliationError('Cohort and order audit ID disagree')
    if not isinstance(original.get('id'),str):
        raise HistoryReconciliationError('Missing original event UUID')
    # The cohort remains only one audit observation. It does not attest to
    # later partial sells, settlement, trading fees, or authoritative payout.
    return dict(original_id=original['id'],order_id=chunk['order_id'],
                entry_key=chunk['key'],price=str(price),quantity=str(quantity),
                entry_cost_with_fee=str(cost),original_at=str(at),
                entry_fresh=chunk['verified'],
                source_fill_consistent=True,
                authoritative_settlement_verified=False,
                realized_pnl_reconciled=False,
                eligible_for_learning=False,
                all_time_coverage_complete=False)


def inspect_cohort_page(items):
    """Validate a limited supplied original page, never infer missing cohorts."""
    if not isinstance(items,list) or len(items)>256:
        raise HistoryReconciliationError('Invalid original cohort page budget')
    inspected=[]
    for item in items:
        if not isinstance(item,dict):
            raise HistoryReconciliationError('Invalid original event')
        if isinstance(item.get('progress'),dict) and item['progress'].get('event')=='FAVORITE_ENTRY_COHORT':
            inspected.append(inspect_original_cohort(item))
    ids=[item['original_id'] for item in inspected]
    if len(ids)!=len(set(ids)):
        raise HistoryReconciliationError('Repeated original cohort UUID in page')
    return dict(inspected_cohorts=inspected,inspected_count=len(inspected),
                source_exhaustion_verified=False,
                all_time_coverage_complete=False,
                eligible_for_learning=False)
