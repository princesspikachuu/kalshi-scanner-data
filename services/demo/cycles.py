"""Two-sided low bids, fixed profit targets, and confirmed inventory offsets."""
from services.research.reports import SERIES

STRATEGY='buy_low_sell_high'

def eligible(config,square,quote,now):
    return (quote.get('status')=='active' and quote['series'] in SERIES[square['asset']]
        and quote.get('open',0)<=now<quote.get('entry_close',quote['close'])-config['cycle_cutoff_minutes']*60)

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
            if state['submitted'] or bot['desired']!='running':continue
            _,ask=side_quote(q,side);price=config['cycle_buy_cents']
            if not price<ask or not entry_protection_matches(config,square,q,side):continue
            result.append(dict(bot=bot['id'],ticker=ticker,side=side,square=index,key=key,cycle=state['cycle'],
                first_at=state['first_at'],price=price,expected_roi=0))
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
        if ticker in blocked or any(o.get('status') in ('intent','uncertain') or o.get('entry_strategy')!=STRATEGY for o in rows):continue
        held=lambda o:max(0,o.get('filled',0)-sold.get(o['client_id'],0)-o.get('offset_quantity',0))
        expected=sum(held(o)*(1 if o['side']=='yes' else -1) for o in rows)
        if abs(expected-actual.get(ticker,0))>.001:continue
        yes=sorted([o for o in rows if o['side']=='yes' and held(o)>0],key=lambda o:(o['created_at'],o['client_id']))
        no=sorted([o for o in rows if o['side']=='no' and held(o)>0],key=lambda o:(o['created_at'],o['client_id']))
        if not yes or not no:continue
        parents={o['client_id'] for o in yes+no}
        if any(o['kind']=='exit' and o.get('parent') in parents and (o.get('remaining',0)>0 or o.get('status') in ('intent','uncertain')) for o in orders):
            cancel.add(ticker);continue
        remaining={o['client_id']:held(o) for o in yes+no};i=j=0
        while i<len(yes) and j<len(no):
            a,b=yes[i],no[j];amount=min(remaining[a['client_id']],remaining[b['client_id']])
            for o in (a,b):
                identifier=o['client_id'];changes[identifier]=changes.get(identifier,0)+amount;remaining[identifier]-=amount
            if remaining[a['client_id']]<=.001:i+=1
            if remaining[b['client_id']]<=.001:j+=1
    return changes,cancel
