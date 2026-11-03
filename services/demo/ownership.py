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


def market_ledger(orders, expected, actual, resting, blocked=(), bot_names=None):
    """One account-level market view with signed, individually attributable bot lots.

    Exchange positions are net YES contracts. Per-bot quantities below are
    attribution of verified local entry fills, not separate exchange accounts.
    Never infer an individual fill or allocate unowned exposure to a bot.
    """
    bot_names=bot_names or {}
    local_by_ticker={};remote_by_ticker={}
    for order in orders:
        local_by_ticker.setdefault(order['ticker'],[]).append(order)
    for order in resting:
        remote_by_ticker.setdefault(order['ticker'],[]).append(order)
    tickers=set(local_by_ticker)|set(remote_by_ticker)|set(expected)|set(actual)|set(blocked)
    ledger={}
    for ticker in sorted(tickers):
        local=local_by_ticker.get(ticker,[])
        known={o.get('client_id') for o in local}
        known_exchange={o.get('exchange_id') for o in local if o.get('exchange_id')}
        unowned=[o for o in remote_by_ticker.get(ticker,[])
                 if o.get('client_order_id') not in known and o.get('order_id') not in known_exchange]
        participants={}
        for order in local:
            bot_id=str(order.get('bot') or 'unknown')
            person=participants.setdefault(bot_id,dict(id=bot_id,name=bot_names.get(bot_id,bot_id),
                held_yes=0,held_no=0,net_contracts=0,orders=0))
            person['orders']+=1
            if order.get('kind')=='entry' and order.get('status')!='closed':
                held=max(0,round(float(order.get('filled',0))-float(order.get('sold',0)),4))
                if order.get('side')=='yes':person['held_yes']=round(person['held_yes']+held,4)
                if order.get('side')=='no':person['held_no']=round(person['held_no']+held,4)
        for person in participants.values():
            person['net_contracts']=round(person['held_yes']-person['held_no'],4)
        detail=[dict(bot_id=o.get('bot'),bot_name=bot_names.get(o.get('bot'),o.get('bot')),
            client_id=o.get('client_id'),exchange_id=o.get('exchange_id'),
            kind=o.get('kind'),exit_role=o.get('exit_role'),parent=o.get('parent'),
            side=o.get('side'),status=o.get('status'),price=o.get('price'),
            filled=o.get('filled',0),remaining=o.get('remaining',0),
            held=max(0,round(float(o.get('filled',0))-float(o.get('sold',0)),4)) if o.get('kind')=='entry' else 0)
            for o in local]
        detail.sort(key=lambda o:(o['status'] not in ('uncertain','intent','cancel_pending'),
                                  o['kind']!='entry',-(o['held'] or 0),str(o['client_id'])))
        exchange=float(actual.get(ticker,0));modeled=float(expected.get(ticker,0))
        ledger[ticker]=dict(
            expected_contracts=modeled,exchange_contracts=exchange,
            difference_contracts=round(exchange-modeled,4),
            shared_by_bots=len(participants)>1,
            bots=sorted(participants.values(),key=lambda row:(row['name'],row['id'])),
            orders=detail[:30],order_count=len(detail),truncated_orders=max(0,len(detail)-30),
            unowned_orders=[dict(client_id=o.get('client_order_id'),exchange_id=o.get('order_id'),
                status=o.get('status'),remaining=o.get('remaining_count_fp',o.get('remaining_count')))
                for o in unowned[:15]],
            unowned_order_count=len(unowned),
            unconfirmed_order_count=sum(o.get('status') in ('uncertain','intent') for o in local),
            cancel_pending_count=sum(o.get('status')=='cancel_pending' for o in local),
            blocked=ticker in blocked)
    return ledger


def transient_sync(market, now, changed_at, blocked_since, last_verified):
    """Mask *only* a recent, fully identified REST snapshot race from UI alarms.

    The market remains trading-blocked until exchange ownership really matches.
    Unknown orders, ambiguous submissions and enduring differences are never
    treated as routine synchronization.
    """
    return bool(market and abs(market['difference_contracts'])>.001
        and market['unowned_order_count']==0 and market['unconfirmed_order_count']==0
        and changed_at>0 and last_verified>0
        and 0<=now-changed_at<=12 and 0<=now-blocked_since<=7
        and 0<=now-last_verified<=60)

def describe(blocked,expected,actual,quotes,orders,remote,now,missing=None,ledger=None):
    missing=missing or {};ledger=ledger or {};details={}
    owned={o['ticker'] for o in orders}
    for ticker in sorted(blocked,key=lambda t:(t not in owned,t))[:100]:
        q=quotes.get(ticker,{})
        live=any(o['ticker']==ticker and (o.get('remaining',0)>0 or o.get('status') in ('intent','uncertain','cancel_pending')) for o in orders)
        live=live or any(o['ticker']==ticker for o in remote)
        end=q.get('close',missing.get(ticker,{}).get('market_end'))
        ended=q.get('status') in ('closed','settled','finalized','determined') or (end is not None and end<=now and (q.get('metadata_at',0)>=end or ticker in missing))
        # A verified ended market cannot accept more trades. Keep the ticker
        # blocked in the reconciliation ledger, but do not leave a running bot
        # in Needs Attention for an old, locally uncertain order unless Kalshi
        # still shows an actual resting order. Never hide live-market exposure.
        remote_resting=any(o['ticker']==ticker for o in remote)
        info=bool(ended and not remote_resting)
        entry=ledger.get(ticker,{})
        reason=('market_unavailable' if info and ticker in missing else 'awaiting_settlement' if info
            else 'unowned_resting_order' if entry.get('unowned_order_count')
            else 'order_verification' if entry.get('unconfirmed_order_count')
            else 'position_difference' if abs(float(expected.get(ticker,0))-float(actual.get(ticker,0)))>.001
            else 'order_verification' if live else 'ownership_mismatch')
        details[ticker]=dict(expected_contracts=expected.get(ticker,0),exchange_contracts=actual.get(ticker,0),market_state=q.get('status','unavailable'),market_end=end,reason=reason,informational=info,**{key:entry[key] for key in ('difference_contracts','shared_by_bots','bots','orders','order_count','truncated_orders','unowned_orders','unowned_order_count','unconfirmed_order_count','cancel_pending_count') if key in entry})
    return details


def verified_empty_finalized_intents(ticker, orders, quote, expected, actual, resting, history, fills, now):
    """Identify *unfilled* intents that are safe to retire using complete exchange reads.

    Absence of a client ID alone is never enough: require an authoritative finalized
    market, no actual or modeled inventory, no resting orders, and no unexplained
    exchange fill. The caller must provide fully paginated order and fill results;
    pagination/transport failures must leave the market blocked.
    """
    if not quote or quote.get('status') not in ('closed','settled','finalized','determined'):
        return []
    if float(quote.get('close',now+1)) > now-60:
        return []
    if abs(Decimal(str(expected)))>.001 or abs(Decimal(str(actual)))>.001:
        return []
    local=[order for order in orders if order.get('ticker')==ticker]
    if not local or any(order.get('status') not in ('intent','uncertain','cancel_pending','resting')
                        or Decimal(str(order.get('filled',0)))!=0 for order in local):
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
    # Even an already-settled fill is evidence that an unlinked order might
    # have traded. Full market-level fill history must be empty to retire it.
    if fills:return []
    return [order['client_id'] for order in local]
