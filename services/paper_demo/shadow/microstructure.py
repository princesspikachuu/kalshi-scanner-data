"""Bounded causal tape shared by paper experiments; no HTTP or model fitting."""
from collections import deque
from itertools import islice
import math,statistics

class MarketTape:
    def __init__(self):self.markets={};self.calculations=0
    def state(self,ticker):
        return self.markets.setdefault(ticker,dict(prices=deque(maxlen=60),trades=deque(maxlen=256),ids=deque(maxlen=256),previous_depth=None,cache=None))
    def trade(self,ticker,trade,now):
        s=self.state(ticker);ident=trade.get('trade_id')
        if not ident or ident in s['ids'] or trade.get('is_block_trade'):return
        try:
            at=float(trade.get('ts_ms',float(trade.get('ts',0))*1000))/1000
            price=float(trade['yes_price_dollars']);q=float(trade['count_fp'])
            side=trade.get('taker_outcome_side',trade.get('taker_side'))
            if not all(math.isfinite(v) for v in (at,price,q)) or abs(at-now)>3 or not 0<=price<=1 or q<=0 or side not in ('yes','no'):return
        except (ValueError,TypeError,KeyError):return
        s['ids'].append(ident);s['trades'].append((at,price,q,1 if side=='yes' else -1))
    def sample(self,ticker,book,now):
        s=self.state(ticker);frame=int(now//2)
        if s['cache'] and s['cache'][0]==frame:return s['cache'][1]
        bid,ask=book.bid('yes'),book.ask('yes')
        if bid is None or ask is None:return None
        # Public depth, independent of each experiment's simulated consumption.
        buy=list(islice(book.levels['yes'].ordered_prices(),3));sell=list(islice(book.levels['no'].ordered_prices(),3))
        depth_yes=sum(float(book.levels['yes'][p]) for p in buy);depth_no=sum(float(book.levels['no'][p]) for p in sell)
        prices=s['prices'];prices.append((now,float((bid+ask)/2)))
        while prices and now-prices[0][0]>120:prices.popleft()
        values=[p for _,p in prices];changes=[b-a for a,b in zip(values,values[1:])]
        elapsed=max(1,prices[-1][0]-prices[0][0]);sigma=statistics.pstdev(values) if len(values)>1 else 0
        recent=[t for t in s['trades'] if now-60<=t[0]<=now]
        volume=sum(t[2] for t in recent);pressure=sum(t[2]*t[3] for t in recent)/volume if volume else 0
        old=s['previous_depth'];depth=depth_yes+depth_no
        withdrawal=max(0,1-depth/old) if old else 0;s['previous_depth']=depth
        f=dict(mean=statistics.mean(values),sigma=sigma,movement=statistics.mean(abs(x) for x in changes) if changes else 0,
            movements_per_minute=sum(abs(c)>=.01 for c in changes)*60/elapsed,reversals=sum(a*b<0 for a,b in zip(changes,changes[1:])),
            support=min(values),resistance=max(values),last_change=changes[-1] if changes else 0,
            previous_change=changes[-2] if len(changes)>1 else 0,trend=values[-1]-values[max(0,len(values)-6)],
            displacement=statistics.mean(values)-values[-1],recent_prices=list(prices)[-20:],observations=len(values),
            depth_yes=depth_yes,depth_no=depth_no,imbalance=(depth_yes-depth_no)/depth if depth else 0,
            trade_count=len(recent),trade_volume=volume,trade_pressure=pressure,depth_withdrawal=withdrawal,
            acceleration=(changes[-1]-changes[-2]) if len(changes)>1 else 0)
        f['reversal_frequency']=f['reversals']*60/elapsed
        s['cache']=(frame,f);self.calculations+=1;return f
    def clear(self,ticker):self.markets.pop(ticker,None)
    def prune(self,active):
        for t in list(self.markets):
            if t not in active:self.markets.pop(t)
