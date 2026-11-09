"""Fee/depth-aware execution hypotheses. Actual fills remain Engine decisions."""
from decimal import Decimal as D,ROUND_FLOOR
from itertools import islice
from .core import ZERO

def tick_size(market,price):
    for band in market.get('price_ranges',[]):
        try:
            if D(band['start'])<=price<D(band['end']):return D(band['step'])
        except (KeyError,ValueError):pass
    return D('.01')

def depth_quote(engine,ticker,side,action,quantity,limit):
    left=quantity;gross=ZERO;fees=ZERO;filled=ZERO;last_price=None
    for price,depth in islice(engine.books[ticker].iter_depth(side,action),20):
        if (action=='buy' and price>limit) or (action=='sell' and price<limit):break
        take=min(left,depth)
        if take>0:
            last_price=price;gross+=take*price;fees+=engine.fees[ticker].charge(take,price,False);filled+=take;left-=take
        if left<=0:break
    return dict(quantity=filled,last_price=last_price,gross=gross,fees=fees,vwap=gross/filled if filled else None)

def committed(engine,predicate=lambda m:True):
    lots=sum((l.quantity*l.price+l.entry_fee for l in engine.wallet.lots if predicate(engine.markets[l.ticker])),ZERO)
    bids=sum((o.reserved for o in engine.orders.values() if o.action=='buy' and o.status in ('pending','resting') and predicate(engine.markets[o.ticker])),ZERO)
    return lots+bids

def size(engine,ticker,contracts,price,features,config):
    m=engine.markets[ticker];capital=engine.wallet.deposits
    limits=[engine.available(),capital*D(str(config.get('portfolio_exposure',.35)))-committed(engine),
        capital*D(str(config.get('market_exposure',.03)))-committed(engine,lambda x:x['ticker']==ticker),
        capital*D(str(config.get('event_exposure',.06)))-committed(engine,lambda x:x.get('event_ticker')==m.get('event_ticker')),
        capital*D(str(config.get('category_exposure',.15)))-committed(engine,lambda x:x.get('market_category',x.get('hourly_price'))==m.get('market_category',m.get('hourly_price')))]
    # Include the worst applicable entry fee before choosing quantity.
    unit=price+engine.fees[ticker].charge(D(1),price,False)
    capital_quantity=max(ZERO,min(limits)/unit)
    volatility=max(.25,min(1.,.08/max(.01,features['sigma'])))
    liquidity=min(features['depth'],features['exit_depth'])*config.get('depth_fraction',.25)
    return max(ZERO,min(D(contracts)*D(str(volatility)),D(str(liquidity)),capital_quantity).to_integral_value(rounding=ROUND_FLOOR))

def passive_entry_price(market,bid,ask,features,config):
    tick=tick_size(market,bid)
    improve=(config.get('adaptive',True) and ask-bid>=2*tick and (features.get('trade_count',0)>0 or features.get('last_change',0)>0))
    if config.get('approach')=='market_maker' and config.get('adaptive',True) and ask-bid>=2*tick:
        if config.get('competitive_inside',False):
            # Competitive is the aggressive A/B variant: use the best post-only
            # tick whenever the verified book leaves room. Standard remains the
            # conservative one-tick-improvement control on quiet books.
            return ask-tick
        improve=True
    return min(ask-tick,bid+(tick if improve else ZERO))

def choose(engine,ticker,side,features,quantity,target,config):
    book=engine.books[ticker];bid,ask=book.bid(side),book.ask(side)
    tick=tick_size(engine.markets[ticker],bid);fee=engine.fees[ticker]
    maker_price=passive_entry_price(engine.markets[ticker],bid,ask,features,config)
    future=min(D('.99'),D(str(max(features['resistance'],float(ask)+target if config['approach']=='momentum' else features['resistance']))))
    if config['approach']=='market_maker':future=max(maker_price+tick,ask-tick)
    maker_fee=fee.charge(quantity,maker_price,True)+fee.charge(quantity,future,config.get('maker_profit_exits',False))
    maker_net=(future-maker_price)*quantity-maker_fee
    ahead=book.levels[side].get(maker_price,ZERO)
    flow=features.get('trade_volume',0)*max(.1,(1-features.get('trade_pressure',0))/2)
    wait=min(config.get('order_ttl',10),max(1,features['seconds_remaining']-config['liquidate']))
    probability=max(.05,min(.95,flow*wait/60/(float(ahead+quantity)+1))) if flow else .15
    # Uncalibrated queue heuristic is explicit. Never a fill authorization.
    take_limit=min(D('.9999'),ask+tick*D(str(config.get('slippage_ticks',2))))
    quote=depth_quote(engine,ticker,side,'buy',quantity,take_limit)
    taker_net=(future*quantity-quote['gross']-quote['fees']-fee.charge(quantity,future,False)) if quote['quantity']==quantity else -D(1000000)
    speed=max(0,features['last_change'])+max(0,features.get('acceleration',0))
    urgency=min(1.,speed/.02+(1 if features['seconds_remaining']<config.get('reduce_hold',120) else 0))
    maker_score=float(maker_net)*probability
    taker_score=float(taker_net)*(min(.95,.35+urgency*.5))
    take=config.get('mixed',True) and taker_net>D(str(config.get('min_net',.005))) and (taker_score>maker_score or probability<.25 and urgency>.5)
    return dict(maker=not take,price=take_limit if take else maker_price,
        expected_net=taker_net if take else maker_net,expected_fill_probability=min(.99,max(.1,float(quote['quantity']/quantity)*.9)) if take else probability,
        expected_wait_seconds=wait,queue_ahead=str(ahead),maker_score=maker_score,taker_score=taker_score,
        expected_slippage=str((quote['vwap']-ask) if quote['vwap'] is not None else 0),
        model='causal-flow-queue-heuristic-v1',execution_not_guaranteed=True)
