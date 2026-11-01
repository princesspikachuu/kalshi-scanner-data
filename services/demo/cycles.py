"""Two-sided low bids, fixed profit targets, and confirmed inventory offsets."""
from services.research.reports import SERIES

STRATEGY='buy_low_sell_high'

def active(order):return order.get('status') not in ('closed','rejected')

def held(order):return order.get('kind')=='entry' and round(order.get('filled',0)-order.get('sold',0),2)>0

def sell_floor(side,orders):
    prices=[o['price'] for o in orders if active(o) and o['kind']=='exit' and o['side']==side
        and (o.get('remaining',0)>0 or o.get('status') in ('intent','uncertain','cancel_pending'))]
    prices.extend(o['profit_target_cents'] for o in orders if active(o) and held(o) and o['side']==side
        and o.get('entry_strategy')==STRATEGY and not o.get('exit_triggered'))
    return min(prices,default=100)

def park_reason(order,orders):
    if order.get('kind')!='entry' or order.get('entry_strategy')!=STRATEGY or order.get('remaining',0)<=0:return None
    if any(active(o) and held(o) and o['side']!=order['side'] for o in orders):return 'opposite_inventory'
    if order['price']>=sell_floor(order['side'],orders):return 'self_trade'
    return None

def entry_block_reason(item,orders,netting=False):
    """Shared lots retain parent ownership; only incompatible orders wait."""
    rows=[o for o in orders if active(o)]
    if netting:return 'netting'
    if any(o.get('status') in ('intent','uncertain','cancel_pending') for o in rows):return 'verification'
    entries=[o for o in rows if o['kind']=='entry']
    if any(o.get('entry_strategy')!=STRATEGY for o in entries):return 'other_strategy'
    if any(o['bot']==item['bot'] and o['side']==item['side'] for o in entries):return 'duplicate'
    if any(held(o) and o['side']!=item['side'] for o in entries):return 'opposite_inventory'
    if item['price']>=sell_floor(item['side'],rows):return 'self_trade'
    return None

def shared_quantity(item,peers,config,equity,cash,market_exposure,bot_exposure):
    from .engine import quantity
    amount=quantity(config,item['price'],equity,cash,market_exposure,bot_exposure)
    if len(peers)>1:
        # Percentages are ceilings. Leave room for the other eligible bot sides
        # instead of letting the first bot consume the entire shared market cap.
        allowance=max(0,min(cash,equity*config['market_percent']/100-market_exposure))
        amount=min(amount,max(1,int(allowance/len(peers)/item['price'])))
    return amount

def retry_ready(retry,quote,now):
    return (not retry or (now>=retry['after'] and
        (quote.get('clock'),quote.get('seq'))!=(retry.get('clock'),retry.get('seq'))))

def rejection_prices(order):
    """Move away from a rejected price in outcome cents, including NO orders."""
    if order['kind']=='entry':
        buy=order['price']-2;sell=order['profit_target_cents']-2
        return (buy,sell) if 1<=buy<50 and buy<sell<=99 else None
    sell=order['price']+2
    return (None,sell) if sell<=99 else None

def eligible(config,square,quote,now):
    return (quote.get('status')=='active' and quote['series'] in SERIES[square['asset']]
        and quote.get('open',0)<=now<quote.get('entry_close',quote['close'])-config['cycle_cutoff_minutes']*60)

def diagnostics(bot,quotes,states,orders,now,blocked,netting,account,reconciled):
    from collections import Counter
    from .engine import side_quote,entry_protection_matches,quantity
    config=bot['config'];by_market={};market_cost={};bot_cost=0
    live=[o for o in orders if active(o)]
    for order in live:
        by_market.setdefault(order['ticker'],[]).append(order)
        if order['kind']=='entry':
            cost=(order.get('remaining',0)+max(0,order.get('filled',0)-order.get('sold',0)))*order['price']
            market_cost[order['ticker']]=market_cost.get(order['ticker'],0)+cost
            if order['bot']==bot['id']:bot_cost+=cost
    markets=[(t,q) for t,q in quotes.items() if any(q['series'] in SERIES[s['asset']] for s in config['squares'])]
    fresh=[(t,q) for t,q in markets if now-q['at']<=5 and q.get('source')=='orderbook' and q.get('book_verified')]
    ready=0;eligible_markets=0;reasons=Counter()
    for ticker,q in fresh:
        index=next((i for i,s in enumerate(config['squares']) if eligible(config,s,q,now)),None)
        if index is None:continue
        eligible_markets+=1;square=config['squares'][index];rows=by_market.get(ticker,[])
        for side in ('yes','no'):
            state=states.get(bot['id'],{}).get(f'{ticker}/{index}/{side}',{})
            price=state.get('retry_buy_cents',config['cycle_buy_cents'])
            item=dict(bot=bot['id'],side=side,price=price)
            reason=entry_block_reason(item,rows,ticker in netting)
            if not reason and state.get('submitted'):reason='complete'
            if not reason and not retry_ready(state.get('price_retry'),q,now):reason='price_retry'
            if not reason and (ticker in blocked or not reconciled):reason='verification'
            if not reason and any(o.get('exit_triggered') or o['kind']=='exit' and o.get('exit_role')!='profit' for o in rows):reason='protection'
            if not reason and not price<side_quote(q,side)[1]:reason='maker'
            if not reason and not entry_protection_matches(config,square,q,side):reason='stop'
            if not reason and (len(live)>=490 or len(by_market)>=100 and ticker not in by_market):reason='capacity'
            if not reason and quantity(config,price,account.get('equity_cents',0),account.get('cash_cents',0),market_cost.get(ticker,0),bot_cost)<1:reason='budget'
            if reason:reasons[reason]+=1
            else:ready+=1
    own=[o for o in live if o['bot']==bot['id']]
    lows=sum(o['kind']=='entry' and o.get('remaining',0)>0 for o in own)
    highs=sum(o.get('exit_role')=='profit' and o.get('remaining',0)>0 for o in own)
    labels=dict(verification='verifying current orders',other_strategy='another strategy owns this market',
        opposite_inventory='waiting for opposite-side positions to close',self_trade='would cross your own sell',netting='reconciling offsetting fills',
        budget='insufficient available funds or allocation',price_retry='waiting for a fresh quote to retry',protection='protective exit is active',
        maker='buy price would cross the current ask',stop='loss prevention blocks entry',capacity='order tracking limit reached')
    waiting=[f'{count} {labels[key]}' for key,count in sorted(reasons.items(),key=lambda pair:(-pair[1],pair[0])) if key in labels][:2]
    status='New entries paused' if bot['desired']!='running' else f'{ready} sides ready to bid' if ready else 'Entry bids waiting' if waiting else 'Waiting for existing bids or positions' if reasons.get('duplicate') else 'Cycle completed or stopped' if reasons.get('complete') else 'Waiting for the next market before cutoff'
    message=f'Buy {config["cycle_buy_cents"]}¢ / sell {config["cycle_sell_cents"]}¢ · {lows} waiting buys · {highs} profit sells · {status}'
    if waiting:message+=' · '+'; '.join(waiting)
    return dict(message=message,markets=len(markets),fresh=len(fresh),eligible_markets=eligible_markets,matches=ready,
        entry_blockers=dict(reasons),exit_waiting=False,categories=sorted({s['asset'] for s in config['squares']}))

def candidates(bot,quotes,states,now,blocked):
    from .engine import side_quote,entry_protection_matches
    config=bot['config'];memory=states.setdefault(bot['id'],{});result=[]
    for ticker,q in quotes.items():
        if ticker in blocked or now-q['at']>5 or q.get('source')!='orderbook' or not q.get('book_verified'):continue
        index=next((i for i,s in enumerate(config['squares']) if eligible(config,s,q,now)),None)
        if index is None:continue
        square=config['squares'][index]
        for side in ('yes','no'):
            key=f'{ticker}/{index}/{side}'
            if key not in memory and sum(len(v) for v in states.values())>=10000:continue
            state=memory.setdefault(key,dict(cycle=1,submitted=False,first_at=now))
            state['expires_at']=q.get('entry_close',q['close'])
            if state['submitted'] or bot['desired']!='running' or not retry_ready(state.get('price_retry'),q,now):continue
            _,ask=side_quote(q,side);price=state.get('retry_buy_cents',config['cycle_buy_cents'])
            if not price<ask or not entry_protection_matches(config,square,q,side):continue
            result.append(dict(bot=bot['id'],ticker=ticker,side=side,square=index,key=key,cycle=state['cycle'],
                first_at=state['first_at'],price=price,profit_target_cents=state.get('retry_sell_cents',config['cycle_sell_cents']),expected_roi=0))
    for key in list(memory):
        if key.split('/')[0] not in quotes and memory[key].get('expires_at',now+1)<=now:memory.pop(key)
    return result

def offset_plan(orders,sold,actual,blocked):
    """Pair only confirmed owned cycle fills, after all live sells are canceled.

    A YES and NO fill offset one contract of inventory. The $1 combined credit
    is split equally for estimated lot statistics, never represented as a sale.
    """
    changes={};cancel=set();tickers={o['ticker'] for o in orders if o.get('entry_strategy')==STRATEGY}
    for ticker in tickers:
        rows=[o for o in orders if o['ticker']==ticker and o['kind']=='entry' and o.get('status') not in ('closed','rejected')]
        if ticker in blocked or any(o.get('status') in ('intent','uncertain','cancel_pending') or o.get('entry_strategy')!=STRATEGY for o in rows):continue
        held=lambda o:max(0,o.get('filled',0)-sold.get(o['client_id'],0)-o.get('offset_quantity',0))
        expected=sum(held(o)*(1 if o['side']=='yes' else -1) for o in rows)
        if abs(expected-actual.get(ticker,0))>.001:continue
        yes=sorted([o for o in rows if o['side']=='yes' and held(o)>0],key=lambda o:(o['created_at'],o['client_id']))
        no=sorted([o for o in rows if o['side']=='no' and held(o)>0],key=lambda o:(o['created_at'],o['client_id']))
        if not yes or not no:continue
        parents={o['client_id'] for o in yes+no}
        if any(o['kind']=='exit' and o.get('parent') in parents and (o.get('remaining',0)>0 or o.get('status') in ('intent','uncertain','cancel_pending')) for o in orders):
            cancel.add(ticker);continue
        remaining={o['client_id']:held(o) for o in yes+no};i=j=0
        while i<len(yes) and j<len(no):
            a,b=yes[i],no[j];amount=min(remaining[a['client_id']],remaining[b['client_id']])
            for o in (a,b):
                identifier=o['client_id'];changes[identifier]=changes.get(identifier,0)+amount;remaining[identifier]-=amount
            if remaining[a['client_id']]<=.001:i+=1
            if remaining[b['client_id']]<=.001:j+=1
    return changes,cancel
