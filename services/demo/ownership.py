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


def verified_empty_finalized_intents(ticker, orders, quote, expected, actual, resting, history, fills, now):
    """Identify *unfilled* intents that are safe to retire using complete exchange reads.

    Absence of a client ID alone is never enough: require an authoritative finalized
    market, no actual or modeled inventory, no resting orders, and no unexplained
    exchange fill. The caller must provide fully paginated order and fill results;
    pagination/transport failures must leave the market blocked.
    """
    if not quote or quote.get('status') not in ('settled','finalized'):
        return []
    if float(quote.get('close',now+1)) > now-60:
        return []
    if abs(Decimal(str(expected)))>.001 or abs(Decimal(str(actual)))>.001:
        return []
    local=[order for order in orders if order.get('ticker')==ticker]
    if not local or any(order.get('status') not in ('intent','uncertain')
                        or Decimal(str(order.get('filled',0)))!=0
                        or Decimal(str(order.get('remaining',0)))!=0 for order in local):
        return []
    if any(order.get('ticker')==ticker for order in resting):
        return []
    clients={order['client_id'] for order in local}
    market_history=[order for order in history if order.get('ticker')==ticker]
    if any(order.get('client_order_id') in clients for order in market_history):
        return []
    exchange_ids={order['order_id'] for order in market_history if order.get('order_id')}
    if any(order.get('exchange_id') in exchange_ids for order in local if order.get('exchange_id')):
        return []
    # An unexplained fill could belong to a lost-response order, even when
    # unsettled inventory has dropped to zero. Never guess its ownership or P/L.
    for fill in fills:
        if (fill.get('ticker') or fill.get('market_ticker'))!=ticker:
            return []
        if not fill.get('order_id') or fill['order_id'] not in exchange_ids:
            return []
    return [order['client_id'] for order in local]
