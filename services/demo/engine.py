"""Pure entry and maker-exit rules, expressed in cents; no network side effects."""
import math
from collections import defaultdict,deque
from services.research.reports import SERIES

def fair_budget_config(config,running_bots):
    """Enforce an equal per-running-bot account share as an additional ceiling.

    Existing bot, per-bid, and per-market limits remain unchanged. Nothing is
    transferred, sold or resized; only *new* entries use this reduced ceiling.
    A bot with a stricter saved limit keeps its stricter limit.
    """
    if running_bots<=1:return config
    cap=min(config['bot_percent'],100/running_bots)
    return dict(config,bot_percent=cap) if cap<config['bot_percent'] else config

def fair_order_candidates(items,last_bot=None,committed=None):
    """Rotate candidate opportunities across bots; retain per-bot priority.

    A busy high-cardinality series must not repeatedly take the first write
    slot while the other bots wait for their first entry. Applied to new buys
    only; existing sell and cancellation priority remains above this scheduler.
    """
    queues=defaultdict(deque)
    for item in items:queues[item['bot']].append(item)
    bots=sorted(queues)
    if last_bot in bots:
        pivot=(bots.index(last_bot)+1)%len(bots)
        bots=bots[pivot:]+bots[:pivot]
    if committed is not None:bots.sort(key=lambda bot:committed.get(bot,0))
    result=[]
    while queues:
        for bot in bots:
            queue=queues.get(bot)
            if not queue:continue
            result.append(queue.popleft())
            if not queue:queues.pop(bot,None)
    return result

def cycle_tranche(config,equity,running_bots):
    """Build a bot allocation in four steps while other bots get coverage."""
    share=equity*fair_budget_config(config,running_bots)['bot_percent']/100
    return share/(4 if running_bots>1 else 1)

def side_quote(quote,side):
    if side=='yes':return quote['bid'],quote['ask']
    return round(100-quote['ask'],4),round(100-quote['bid'],4)

def qualifies(square,quote,side,now,reference):
    bid,ask=side_quote(quote,side)
    minutes=(quote.get('entry_close',quote['close'])-now)/60
    value=bid if reference=='bid' else ask
    return (quote.get('series') in SERIES[square['asset']] and
        square['min_minutes']<minutes<=square['max_minutes'] and square['min_price']<=value<=square['max_price'])

def protective_threshold(config,square):
    if square.get('loss_prevention_cents') is not None:return square['loss_prevention_cents']
    if config['loss_mode']=='manual':return config.get('loss_cents')
    if config['loss_mode']=='research':return square.get('loss_cents')
    return None

def order_threshold(bot,order,quote,now,research_lookup=None):
    """Use the current market-time row in the position's original price band."""
    config=bot['config'];condition=order.get('condition')
    if not condition and order.get('revision',bot['revision'])==bot['revision'] and 0<=order['square']<len(config['squares']):condition=config['squares'][order['square']]
    minutes=max(1e-9,(quote.get('entry_close',quote['close'])-now)/60)
    matches=[s for s in config['squares'] if condition and s['min_price']==condition['min_price'] and s['max_price']==condition['max_price'] and quote['series'] in SERIES[s['asset']]]
    current=sorted([s for s in matches if s['min_minutes']<minutes<=s['max_minutes']],key=lambda s:(s['asset']!=(condition or {}).get('asset'),s['max_minutes']-s['min_minutes'],s['max_minutes'],s['asset']))
    if current and current[0].get('loss_prevention_cents') is not None:return current[0]['loss_prevention_cents']
    if config['loss_mode']=='manual':return config.get('loss_cents')
    if config['loss_mode']=='off':return None
    if current and current[0].get('loss_cents') is not None:return current[0]['loss_cents']
    sources=[s['report_id'] for s in matches if s.get('report_id') and s['asset']==(condition or {}).get('asset')] or [s['report_id'] for s in matches if s.get('report_id')]
    source=current[0]['report_id'] if current and current[0].get('report_id') else max(sources) if sources else (condition or {}).get('report_id')
    if source and condition and research_lookup:
        band=f"{condition['min_price']:02d}-{condition['max_price']+1:02d}"
        return research_lookup(source,band,minutes)
    return None

def entry_protection_matches(config,square,quote,side):
    threshold=protective_threshold(config,square)
    return threshold is None or side_quote(quote,side)[1]>threshold

def entry_price(config,quote,side,square=None):
    bid,ask=side_quote(quote,side)
    price=(bid if config['price_reference']=='bid' else ask)+config['adjustment_cents']
    # The maximum is a ceiling, never an instruction to raise a lower bid.
    maximum=square.get('maximum_cents') if square and square.get('maximum_cents') is not None else config.get('maximum_cents')
    if maximum is not None:price=min(price,maximum)
    price=math.floor(price)
    # A minimum filters cheap bids; it never raises a bid or overrides its reference.
    if config.get('minimum_cents') is not None and price<config['minimum_cents']:return None
    return price if 1<=price<ask and price<=99 else None

def quantity(config,price,equity,cash,market_exposure,bot_exposure):
    available=min(cash,equity*config['bid_percent']/100,
        equity*config['market_percent']/100-market_exposure,
        equity*config['bot_percent']/100-bot_exposure)
    return max(0,math.floor(available/price))

def candidates(bots,quotes,states,now,blocked=()):
    output=[]
    for bot in bots:
        config=bot['config'];memory=states.setdefault(bot['id'],{})
        if config.get('strategy')=='buy_low_sell_high':
            from .cycles import candidates as cycle_candidates
            output.extend(cycle_candidates(bot,quotes,states,now,blocked));continue
        for ticker,quote in quotes.items():
            if now-quote['at']>5 or quote.get('entry_close',quote['close'])<=now or not (0<quote['bid']<quote['ask']<100):continue
            for index,square in enumerate(config['squares']):
                for side in ('yes','no'):
                    key=f'{ticker}/{index}/{side}';match=qualifies(square,quote,side,now,config['qualification'])
                    if not match and key not in memory:continue
                    old=memory.get(key,dict(inside=False,cycle=0,submitted=False))
                    if match and not old['inside']:old=dict(inside=True,cycle=old['cycle']+1,submitted=False,first_at=now)
                    elif not match:old=dict(old,inside=False)
                    if key not in memory and sum(len(v) for v in states.values())>=10000:continue
                    memory[key]=old
                    if not match or old['submitted'] or bot['desired']!='running' or ticker in blocked:continue
                    if not entry_protection_matches(config,square,quote,side):continue
                    price=entry_price(config,quote,side,square)
                    if price is not None:output.append(dict(bot=bot['id'],ticker=ticker,side=side,square=index,
                        cycle=old['cycle'],price=price,first_at=old['first_at'],expected_roi=square.get('expected_roi') or 0,key=key))
        # Keep only current watchlist conditions, at most 100 markets x 45 squares x two sides.
        for key in list(memory):
            if key.split('/')[0] not in quotes:memory.pop(key)
    return sorted(output,key=lambda p:(p['first_at'],-p['expected_roi'],p['bot'],p['ticker'],p['square'],p['side']))

def exit_price(quote,side,ceiling=None):
    bid,ask=side_quote(quote,side)
    # ASK is the buy-now/taker price for this outcome. Once an exit is posted,
    # a rising quote must be allowed to reach it instead of chasing it upward.
    candidate=math.ceil(ask+1) if 0<=bid<ask<=98 else None
    if ceiling is not None:return min(ceiling,candidate) if candidate is not None else ceiling
    return candidate

def wire_order(intent):
    """V2 is one YES book: buying NO is selling YES at its complement."""
    entry=intent['kind']=='entry';yes=intent['side']=='yes'
    book='bid' if entry==yes else 'ask'
    price=intent['price'] if yes else 100-intent['price']
    return dict(ticker=intent['ticker'],client_order_id=intent['client_id'],side=book,
        count=f"{intent['quantity']:.2f}",price=f'{price/100:.4f}',
        time_in_force='good_till_canceled',expiration_time=int(intent['close']),exchange_index=intent.get('exchange_index',-1),
        self_trade_prevention_type='taker_at_cross',post_only=True,cancel_order_on_pause=True)
