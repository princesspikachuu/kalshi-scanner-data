"""Describe account differences without inventing fills or settlement proceeds."""
from decimal import Decimal

def needs_recovery(parameters,progress,remote):
    if parameters.get('kind') not in ('entry','exit') or 'realized_cents' in progress or progress.get('reset_closed'):return False
    if progress.get('status') not in ('closed','rejected'):return False
    if remote.get('status') not in ('resting','executed','canceled','cancelled'):return False
    if remote.get('ticker')!=parameters.get('ticker'):return False
    if progress.get('exchange_id') and progress['exchange_id']!=remote.get('order_id'):return False
    filled=Decimal(str(remote.get('fill_count_fp',remote.get('fill_count',0))))
    remaining=Decimal(str(remote.get('remaining_count_fp',remote.get('remaining_count',0))))
    quantity=Decimal(str(parameters.get('quantity',0)))
    if not all(n.is_finite() and n>=0 for n in (filled,remaining,quantity)) or filled+remaining>quantity:return False
    if remote['status']!='resting' and remaining>0:return False
    return filled>Decimal(str(progress.get('filled',0))) or remaining>0

def describe(blocked,expected,actual,quotes,orders,remote,now,missing=None):
    missing=missing or {};details={}
    owned={o['ticker'] for o in orders}
    for ticker in sorted(blocked,key=lambda t:(t not in owned,t))[:100]:
        q=quotes.get(ticker,{})
        live=any(o['ticker']==ticker and (o.get('remaining',0)>0 or o.get('status') in ('intent','uncertain','cancel_pending')) for o in orders)
        live=live or any(o['ticker']==ticker for o in remote)
        end=q.get('close',missing.get(ticker,{}).get('market_end'))
        ended=q.get('status') in ('closed','settled','finalized','determined') or (end is not None and end<=now and (q.get('metadata_at',0)>=end or ticker in missing))
        info=bool(ended and not live)
        reason='market_unavailable' if info and ticker in missing else 'awaiting_settlement' if info else 'order_verification' if live else 'ownership_mismatch'
        details[ticker]=dict(expected_contracts=expected.get(ticker,0),exchange_contracts=actual.get(ticker,0),market_state=q.get('status','unavailable'),market_end=end,reason=reason,informational=info)
    return details
