"""Causal, experimental scalping over the existing read-only paper execution feed.

Parameters are versioned hypotheses, never fitted or promoted by these observations.
Public trades, not quote touches, drive maker executions in Engine.
"""
import json
import math
import statistics
from itertools import islice
from collections import deque
from .microstructure import MarketTape
from .execution import choose as execution_choice,size as position_size,tick_size,depth_quote,committed,passive_entry_price
from decimal import Decimal as D, ROUND_FLOOR
from .core import ConvexityStrategy, Engine, ZERO

SCALPER_FOLDERS=('volatility_scalper','scalper_fixed','scalper_grid','scalper_momentum','scalper_dislocation')
CONFIGS={
    'scalper_momentum':dict(approach='momentum',adaptive=True,mixed=True,take_profit=.02,stop_loss=.05,min_hold=1,max_hold=45,liquidate=35),
    'scalper_dislocation':dict(approach='liquidity_dislocation',adaptive=True,mixed=True,take_profit=.02,stop_loss=.05,min_hold=1,max_hold=60,liquidate=40),
    'volatility_scalper':dict(approach='mean_reversion',adaptive=True,mixed=True,take_profit=.025,stop_loss=.07,min_hold=1,max_hold=90,liquidate=30),
    'scalper_fixed':dict(approach='mean_reversion',adaptive=False,mixed=False,maker_profit_exits=True,take_profit=.03,stop_loss=.05,min_hold=0,max_hold=60,liquidate=60),
    'scalper_grid':dict(approach='range_grid',adaptive=True,mixed=True,take_profit=.02,stop_loss=.09,min_hold=2,max_hold=120,liquidate=45),
}

EXECUTION_DEFAULTS=dict(order_ttl=10,reprice_ticks=2,reprice_seconds=3,min_net=.005,depth_fraction=.25,
    portfolio_exposure=.35,market_exposure=.03,event_exposure=.06,category_exposure=.15,
    reduce_hold=120,restrict_entries=60,eval_seconds=2,signal_threshold=.01,
    category_phases={'crypto':dict(reduce_hold=120,restrict_entries=55,liquidate=30),
                     'finance':dict(reduce_hold=180,restrict_entries=90,liquidate=45),
                     'commodities':dict(reduce_hold=180,restrict_entries=75,liquidate=40)})

def dimensions(profile,market):
    series=profile['series']
    asset=profile.get('underlying') or series.removeprefix('KX').removesuffix('15M')
    category=profile.get('market_category','other')
    duration=round(market['close']-market.get('open',market['close']-900))
    return dict(category=category,underlying=asset,series=series,duration_seconds=duration)


def horizon(seconds):
    return '0–1m' if seconds<=60 else '1–3m' if seconds<=180 else '3–5m' if seconds<=300 else '5–10m' if seconds<=600 else '10–15m' if seconds<=900 else '15–60m' if seconds<=3600 else '1–6h' if seconds<=21600 else '6–24h' if seconds<=86400 else '1–7d' if seconds<=604800 else '7–30d' if seconds<=2592000 else '30d+'


def bucket():
    return dict(opportunities=0,submitted=0,entry_orders_filled=0,maker_entry_orders_filled=0,maker_submitted=0,taker_submitted=0,spread_sum=0.,spread_rounds=0,entry_fills=0,exit_fills=0,completed=0,wins=0,settlement_carryovers=0,
        entry_quantity=0.,entry_cost=0.,closed_quantity=0.,winning_quantity=0.,attempted=0,partial_fills=0,canceled=0,repriced=0,missed=0,risk_rejected=0,economics_rejected=0,maker_fills=0,taker_fills=0,adverse_losses=0.,maker_net=0.,taker_net=0.,net=0.,round_net=0.,verified_completed=0,verified_net=0.,holding_seconds=0.,profitable_exit_seconds=0.,profitable_exits=0,fill_seconds=0.,fill_events=0,
        dollar_hours=0.,peak=0.,max_drawdown=0.,rejections={})



class ScalperEngine(Engine):
    """Portfolio-local queue uncertainty, without changing other strategies."""
    covered_maker_sells=True
    filter_unchanged_quotes=True
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.tape=MarketTape();self._print_times=deque()
    def handle(self,source,payload,now):
        self._scalper_source=source
        try:
            result=super().handle(source,payload,now)
            if source=='kalshi' and payload.get('type')=='trade':
                t=payload.get('msg',{}).get('market_ticker')
                if t in self.books and self.book_fresh(t):self.tape.trade(t,payload['msg'],now)
            return result
        finally:self._scalper_source=None
    def cancel_buys(self,ticker):
        for o in self.orders.values():
            if o.ticker==ticker and o.action=='buy' and o.purpose!='scalper_maker_profit_exit':self.cancel(o.id)
    def data_gap(self,ticker,reason):
        super().data_gap(ticker,reason);self.tape.clear(ticker)
        for o in self.orders.values():
            if o.ticker==ticker and o.maker and o.action=='sell':self.cancel(o.id)
    def place(self,ticker,side,action,quantity,price,**kwargs):
        if kwargs.get('maker',True) and action=='sell':
            reserved=sum((o.remaining for o in self.orders.values() if o.ticker==ticker and o.side==side and o.action=='sell' and o.status in ('pending','resting')),ZERO)
            if D(quantity)>self.wallet.inventory(ticker,side)-reserved:raise ValueError('uncovered maker sale')
        return super().place(ticker,side,action,quantity,price,**kwargs)
    def arrive(self,order):
        book=self.books[order.ticker]
        if order.maker and order.action=='sell':
            bid=book.bid(order.side)
            if (not self.book_fresh(order.ticker) or self.now>=self.markets[order.ticker]['close'] or
                bid is not None and order.price<=bid or self.wallet.inventory(order.ticker,order.side)<order.remaining):
                order.status='rejected';order.reserved=ZERO;self.wallet.stat(order.ticker).rejected_orders+=1
                self.log('ORDER_REJECTED',order,reason='uncovered, closed, stale or crossing maker sell');return
            other='no' if order.side=='yes' else 'yes'
            order.ahead=book.levels[other].get(1-order.price,ZERO)+sum((o.remaining for o in self.orders.values() if o.id!=order.id and o.ticker==order.ticker and o.side==order.side and o.action=='sell' and o.price==order.price and o.status=='resting'),ZERO)
            order.status='resting';self.log('MAKER_RESTING',order,quantity=order.remaining,price=order.price)
        else:super().arrive(order)
        if order.maker and order.status=='resting':
            extra=(order.ahead+order.quantity)*D(str(self.rng.uniform(.05,.35)));order.ahead+=extra
            self.log('SCALPER_QUEUE_ESTIMATE',order,details=json.dumps(dict(hidden_competition=str(extra),model='displayed-FIFO-plus-seeded-5-to-35-percent')))
    def trade(self,ticker,trade):
        # Equivalent YES sells / NO buys compete for the SAME observed print.
        if ticker in self.settled or trade.get('is_block_trade'):return
        while self._print_times and self.now-self._print_times[0][0]>self.stale_seconds:
            _,old=self._print_times.popleft();self.trade_ids.discard(old)
        ident=(ticker,trade['trade_id'])
        if ident in self.trade_ids:return
        if not self.book_fresh(ticker):return
        side=trade.get('taker_outcome_side',trade.get('taker_side'))
        if side not in ('yes','no'):self.data_gap(ticker,'unknown aggressor direction');return
        resting='no' if side=='yes' else 'yes'
        price=D(trade['yes_price_dollars']) if resting=='yes' else 1-D(trade['yes_price_dollars'])
        volume=D(trade['count_fp']);at=trade.get('ts_ms',trade.get('ts',0)*1000)/1000
        if not price.is_finite() or not volume.is_finite() or not ZERO<=price<=1 or volume<=0:raise ValueError('invalid trade price/quantity')
        if not math.isfinite(at) or abs(self.now-at)>self.stale_seconds:self.data_gap(ticker,'stale/future trade print');return
        if len(self._print_times)>=32768:
            self.data_gap(ticker,'trade deduplication capacity reached');return
        self.trade_ids.add(ident);self._print_times.append((self.now,ident))
        self.tape.trade(ticker,trade,self.now)
        def terms(o):return (o.side,o.price) if o.action=='buy' else ('no' if o.side=='yes' else 'yes',1-o.price)
        orders=sorted((o for o in self.orders.values() if o.ticker==ticker and o.status=='resting' and o.arrives<=at and terms(o)[0]==resting and price<=terms(o)[1]),key=lambda o:(-terms(o)[1],o.arrives,o.id))
        remaining=volume;used={}
        for o in orders:
            limit=terms(o)[1];effective=volume-sum((q for p,q in used.items() if p>limit),ZERO)
            through=price<=limit-tick_size(self.markets[ticker],limit)
            eligible=effective if through else max(ZERO,effective-o.ahead)
            if not through:o.ahead=max(ZERO,o.ahead-effective)
            take=min(o.remaining,remaining,eligible)
            if o.action=='sell':take=min(take,self.wallet.inventory(ticker,o.side))
            if take>0:
                self.fill(o,take,o.price,'TRADE_THROUGH' if through else 'QUEUE_EXHAUSTED');remaining-=take;used[limit]=used.get(limit,ZERO)+take


class VolatilityScalper(ConvexityStrategy):
    recover_fresh_entries=True
    def __init__(self,engine,profile):
        super().__init__(engine,profile['contracts'],False,profile['series'],profile['name'])
        self.profile=profile
        self.config=dict(EXECUTION_DEFAULTS,**CONFIGS.get(profile['folder_id'],CONFIGS['volatility_scalper']))
        self.config.update(profile.get('config',{}))
        self.event_prefix='SCALPER'
        self.attempts={};self.history={};self.last_eval={};self.last_signature={}
        self.research=dict(totals=bucket(),cells={},recent=[])
        self.last_reason='Warming up · needs 5 fresh price samples; paper only'

    def export_state(self):
        # Do not restore price windows over a disconnected interval.
        return dict(research=self.research,config=self.config)

    def restore_state(self,data):
        self.research=data.get('research',self.research)
        for c in [self.research['totals'],*self.research.get('cells',{}).values()]:
            for k,v in bucket().items():c.setdefault(k,v)
        # An in-flight trial always retains its entry-time config in attempts.

    def on_data_gap(self,ticker,reason):
        self.history.pop(ticker,None);self.last_eval.pop(ticker,None)
        a=self.attempts.get(ticker)
        if a and not a.get('recorded'):a['verified']=False
        self.last_reason='Data gap · waiting for a fresh snapshot and price window'

    def safety_cancel(self,ticker):pass
    def exit_allowed(self,order):return self.e.now<self.e.markets[order.ticker]['close']

    def metadata(self,ticker):
        m=self.e.markets[ticker]
        # Chronological blocks: five days observation, next two days validation.
        # Shared event open time keeps every side/variant of an event in one split.
        day=int(m.get('open',m['close']-900)//86400)
        return dict(dimensions(self.profile,m),horizon=horizon(m['close']-self.e.now),
            split='training' if day%7<5 else 'validation',block=day//7,
            config_version=self.profile.get('version','scalper-1')+'+execution-v2',approach=self.config['approach'],price_tier='unfilled',execution='observed')

    def cells(self,meta):
        key='|'.join(str(meta.get(k,'legacy')) for k in ('category','underlying','duration_seconds','horizon','split','execution','approach','price_tier'))
        if key not in self.research['cells'] and len(self.research['cells'])>=256:key='overflow'
        cell=self.research['cells'].setdefault(key,dict(bucket(),dimensions=meta))
        return (self.research['totals'],cell)

    def increment(self,meta,**values):
        for cell in self.cells(meta):
            for k,v in values.items():cell[k]+=v

    def observe(self,ticker,side,reason,features,signal=False,submitted=False):
        meta=self.metadata(ticker)
        signature=(reason,signal,features['bid'],features['ask']);key=(ticker,side)
        if self.last_signature.get(key)==signature:return
        self.last_signature[key]=signature
        self.increment(meta,opportunities=int(signal),submitted=int(submitted),missed=int(signal and bool(reason) and reason!='candidate_compared'),
            risk_rejected=int(reason in ('linked_exposure','capital_or_depth_limit','portfolio_cash_reserved','entry_cutoff','worker_processing_backlog')),
            economics_rejected=int(reason=='cost_exceeds_observed_rebound'))
        if reason:
            for cell in self.cells(meta):
                counts=cell['rejections'];counts[reason]=counts.get(reason,0)+1
        self.e.log('SCALPER_OPPORTUNITY',ticker=ticker,side=side,reason=reason or 'paper order submitted',
            details=json.dumps(dict(**meta,features={k:v for k,v in features.items() if k!='recent_prices'},signal=signal,submitted=submitted,
                config=self.config,observed_opportunity=signal,executable_at_decision=submitted,
                execution_not_guaranteed=True,reversal_probability=None)))

    def features(self,ticker,side):
        book=self.e.books[ticker]
        # Tape frames are cached for two seconds; live liquidity may disappear
        # inside that frame. Never turn cached statistics into a missing quote.
        bid,ask=book.bid(side),book.ask(side)
        if bid is None or ask is None:return None
        raw=self.e.tape.sample(ticker,book,self.e.now)
        if raw is None:return None
        f=dict(raw);sign=1 if side=='yes' else -1
        if side=='no':
            for key in ('mean','support','resistance'):f[key]=1-raw[key]
            f['support'],f['resistance']=f['resistance'],f['support']
            for key in ('last_change','previous_change','trend','displacement','acceleration','trade_pressure','imbalance'):f[key]=-raw[key]
        bid,ask=book.bid(side),book.ask(side)
        f.update(bid=float(bid),ask=float(ask),spread=float(ask-bid),
            depth=raw['depth_no' if side=='yes' else 'depth_yes'],exit_depth=raw['depth_yes' if side=='yes' else 'depth_no'],
            seconds_remaining=self.e.markets[ticker]['close']-self.e.now)
        return f

    def decision(self,features):
        c=self.config;f=features
        threshold=max(c.get('signal_threshold',.01),min(.05,f['sigma']*.45)) if c['adaptive'] else .02
        spacing=max(.01,min(.07,f['sigma']*.9)) if c['adaptive'] else c['take_profit']
        if c['approach']=='range_grid':
            signal=f['resistance']-f['support']>=spacing and f['bid']<=f['support']+spacing*.6
        elif c['approach']=='momentum':
            signal=(f['trend']>=threshold and f['last_change']>0 and f.get('trade_pressure',0)>=-.1 and
                f['bid']-f['mean']<=max(.08,3*f['sigma']) and f.get('acceleration',0)>-threshold)
        elif c['approach']=='liquidity_dislocation':
            signal=(f['displacement']>=threshold and f['last_change']>=0 and
                (f.get('depth_withdrawal',0)>=.2 or abs(f.get('previous_change',0))>=max(.02,f['sigma'])))
        else:
            signal=f['displacement']>=threshold and f['last_change']>=0
        # Momentum filter is intentionally broad, with its rejected signals recorded.
        falling=f['trend']<-max(.06,3*f['sigma']) and f['last_change']<0
        target=max(c['take_profit'],spacing)
        return signal,falling,target

    def matches(self,ticker,market):return ticker.startswith(self.series+'-')
    def phase(self,ticker):
        c=dict(self.config);c.update(c.get('category_phases',{}).get(self.profile.get('market_category'),{}));return c
    def refresh_config(self):
        c=dict(EXECUTION_DEFAULTS,**CONFIGS.get(self.profile['folder_id'],self.config));c.update(self.profile.get('config',{}));self.config=c

    def active_orders(self,ticker):
        return [o for o in self.e.orders.values() if o.ticker==ticker and o.status in ('pending','resting')]

    def on_fill(self,order,quantity):
        a=self.attempts.get(order.ticker)
        if not a or a.get('recorded'):return
        execution=self.e._recent_fills[order.id][-1]
        raw_price=D(execution['price'])
        maker_exit=order.purpose=='scalper_maker_profit_exit' and order.action=='buy'
        price=1-raw_price if maker_exit else raw_price
        fee=self.e.fees[order.ticker].charge(quantity,raw_price,order.maker)
        meta=a['meta'];wait=self.e.now-order.created
        if order.action=='buy' and not maker_exit and not a.get('first'):
            meta.update(horizon=horizon(self.e.markets[order.ticker]['close']-self.e.now),price_tier=str(int(price*100)//10*10)+'–'+str(int(price*100)//10*10+9)+'%')
        self.increment(meta,partial_fills=int(quantity<order.remaining+quantity),maker_fills=int(order.maker),taker_fills=int(not order.maker))
        self.increment(meta,fill_seconds=wait,fill_events=1,**{'entry_fills' if order.action=='buy' and not maker_exit else 'exit_fills':1})
        self.e.log('SCALPER_EXECUTION',order,quantity=quantity,price=price,fee=fee,
            details=json.dumps(dict(**meta,maker=order.maker,submission_to_fill_seconds=wait,
                time_to_profitable_exit_seconds=(self.e.now-a.get('entered_at',self.e.now)) if (order.action=='sell' or maker_exit) and price>D(str(a.get('average_price',1))) else None)))
        if order.action=='buy' and not maker_exit:
            if not a.get('first'):
                meta.update(horizon=horizon(self.e.markets[order.ticker]['close']-self.e.now),price_tier=str(int(price*100)//10*10)+'–'+str(int(price*100)//10*10+9)+'%')
                self.increment(meta,entry_orders_filled=1,maker_entry_orders_filled=int(order.maker))
                a['entry_remaining']=self.e.markets[order.ticker]['close']-self.e.now
            a.setdefault('entered_at',self.e.now)
            a['quantity']=float(D(str(a['quantity']))+quantity)
            a['gross_cost']=a.get('gross_cost',0)+float(quantity*price)
            a['cost']=float(D(str(a['cost']))+quantity*price+fee)
            a['average_price']=a['cost']/a['quantity']
            self.increment(meta,entry_quantity=float(quantity),entry_cost=float(quantity*price+fee))
            a['first']=True
            a.setdefault('entry_execution','maker' if order.maker else 'taker')
            # Cancel remaining partial entry; wait for acknowledgement before exits.
            self.e.cancel_buys(order.ticker)
        else:
            a['gross_proceeds']=a.get('gross_proceeds',0)+float(quantity*price)
            a['sold']+=float(quantity);a['proceeds']+=float(quantity*price-fee)
            if order.purpose=='scalper_partial_profit' and not a.get('partial_taken'):
                a['partial_taken']=True;a['target']*=1.5
            if a['proceeds']>a['cost']*(a['sold']/a['quantity']) and not a.get('profitable_at'):
                a['profitable_at']=self.e.now
            if not self.e.wallet.inventory(order.ticker,a['side']):self.finish(order.ticker)

    def finish(self,ticker,settlement=False):
        a=self.attempts.get(ticker)
        if not a or a.get('recorded') or not a.get('first'):return
        s=self.e.wallet.stat(ticker)
        net=float(s.gross-s.realized_fees)-a['baseline']
        held=self.e.now-a['entered_at']
        a.update(recorded=True,completed=not settlement,settlement=settlement,exited_at=self.e.now,net=net,
            holding_seconds=held,average_exit_price=a['proceeds']/a['sold'] if a['sold'] else None)
        self.increment(a['meta'],spread_sum=(a['gross_proceeds']/a['sold']-a['gross_cost']/a['quantity']) if a['sold'] and not settlement and 'gross_cost' in a else 0,spread_rounds=int(bool(a['sold'] and not settlement and 'gross_cost' in a)),closed_quantity=a['quantity'],winning_quantity=a['quantity'] if net>0 else 0,round_net=net if not settlement else 0,verified_completed=int(not settlement and a['verified']),verified_net=net if a['verified'] else 0,completed=int(not settlement),wins=int(net>0 and not settlement),net=net,
            settlement_carryovers=int(settlement),holding_seconds=held if not settlement else 0,
            dollar_hours=a['cost']*held/3600,profitable_exits=int(bool(a.get('profitable_at'))),
            profitable_exit_seconds=a.get('profitable_at',a['entered_at'])-a['entered_at'])
        for cell in self.cells(a['meta']):
            cell['peak']=max(cell['peak'],cell['net'])
            cell['max_drawdown']=max(cell['max_drawdown'],cell['peak']-cell['net'])
        self.increment(a['meta'],**{('maker_net' if a.get('entry_execution',a['meta'].get('execution'))=='maker' else 'taker_net'):net},adverse_losses=min(0,net) if a.get('exit_reason') in ('stop_loss','thesis_invalid','momentum_exhaustion','maker_adverse_selection') else 0)
        row=dict(a,ticker=ticker,exit_at=self.e.now,exit_remaining=max(0,self.e.markets[ticker]['close']-self.e.now))
        compact={k:v for k,v in row.items() if k not in ('entry_features','config')}
        self.research['recent']=(self.research['recent']+[compact])[-20:]
        self.e.log('SCALPER_ROUND_TRIP' if not settlement else 'SCALPER_SETTLEMENT_CARRYOVER',ticker=ticker,
            details=json.dumps(row))
        self.last_reason='Round trip complete · evaluating the next movement' if not settlement else 'Scalp carried into settlement · included as a failed liquidation'

    def manage(self,ticker,a):
        e=self.e;now=e.now;m=e.markets[ticker];c=dict(EXECUTION_DEFAULTS,**a['config']);remaining=m['close']-now
        c.update(c.get('category_phases',{}).get(self.profile.get('market_category'),{}))
        if remaining<=c['reduce_hold']:c['max_hold']=min(c['max_hold'],max(5,remaining*.25))
        if m.get('paid'):
            self.finish(ticker,True);return
        lots=[l for l in e.wallet.lots if l.ticker==ticker]
        if not lots:return
        bid=e.books[ticker].bid(a['side']) if e.book_fresh(ticker) else None
        if bid is not None:
            move=float(bid)-a['average_price']
            a['mfe']=max(a['mfe'],move);a['mae']=min(a['mae'],move)
        maker_features=(self.features(ticker,a['side']) or {}) if c['approach']=='market_maker' and ticker in self.history else {}
        maker_adverse=bool(maker_features) and (maker_features.get('trend',0)<-max(.025,2*maker_features.get('sigma',0)) or
            maker_features.get('trade_pressure',0)<-.7 or maker_features.get('depth_withdrawal',0)>.5)
        urgent=remaining<=c['liquidate'] or now-a['entered_at']>=c['max_hold'] or m.get('maker_event_window',False) or maker_adverse
        if urgent:e.cancel_buys(ticker)
        if remaining<=0 or bid is None or bid<=0:
            reason='closed_before_liquidation' if remaining<=0 else 'liquidation_missing_fresh_bid'
            if urgent and now-a.get('blocked_at',-1e9)>=10:
                a['blocked_at']=now
                e.log('SCALPER_LIQUIDATION_BLOCKED',ticker=ticker,reason=reason,details=json.dumps(dict(time_remaining=remaining)))
            return
        active=self.active_orders(ticker)
        if active:
            if urgent or bid is not None and float(bid)-a['average_price']<=-c['stop_loss'] or any(now-o.created>c.get('exit_ttl',15) for o in active):
                for order in active:e.cancel(order.id)
            return
        quantity=sum((l.quantity for l in lots),ZERO)
        fee=e.fees[ticker].charge(quantity,bid)/quantity
        net_move=float(bid-fee)-a['average_price']
        stop=net_move<=-c['stop_loss']
        f=(self.features(ticker,a['side']) or {}) if ticker in self.history else {}
        exhaustion=c['approach']=='momentum' and now-a['entered_at']>c['min_hold'] and f.get('trend',0)<-.01
        invalid=(f.get('trend',0)<-max(.04,3*f.get('sigma',0)) and f.get('trade_pressure',0)<-.5)
        urgent=urgent or exhaustion or invalid
        take=net_move>=a['target'] and now-a['entered_at']>=c['min_hold']
        a['peak_net']=max(a.get('peak_net',net_move),net_move)
        trail=a['peak_net']>=a['target'] and net_move<=a['peak_net']-max(.01,a['target']*.5)
        if c.get('maker_profit_exits') and not (urgent or stop or trail):
            # Covered maker sales reserve inventory rather than additional cash.
            desired=min(D('.99'),D(str(a['average_price']+a['target']+(0 if c['approach']=='market_maker' else .005))).quantize(D('.01')))
            passive_ask=e.books[ticker].ask(a['side'])
            if passive_ask is None:passive_ask=min(D('.9999'),bid+D('.01'))
            desired=max(desired,passive_ask-(tick_size(m,passive_ask) if c['approach']=='market_maker' else ZERO))
            e.place(ticker,a['side'],'sell',quantity,desired,maker=True,
                expiry=min(now+c.get('exit_ttl',15),m['close']-c['liquidate']),targets=[l.id for l in lots],purpose='scalper_maker_profit_exit')
            a['exit_reason']='maker_profit_exit'
            return
        if not (urgent or stop or take or trail):return
        if take and not urgent and not stop and not a.get('partial_taken') and quantity>=2:
            quantity=(quantity/2).to_integral_value(rounding=ROUND_FLOOR)
        reason='maker_adverse_selection' if maker_adverse else 'thesis_invalid' if invalid else 'momentum_exhaustion' if exhaustion else 'time_liquidation' if urgent else 'stop_loss' if stop else 'trailing_exit' if trail else 'partial_profit' if quantity<sum((l.quantity for l in lots),ZERO) else 'take_profit'
        a['exit_reason']=reason
        e.log('SCALPER_EXIT_DECISION',ticker=ticker,reason=reason,details=json.dumps(dict(
            time_remaining=remaining,net_move=net_move,unfavorable_liquidation=urgent and net_move<0,
            quantity=str(quantity),mfe=a['mfe'],mae=a['mae'])))
        # An IOC sells only observable depth at or above this explicit slippage cap.
        limit=max(D('.0001'),bid-D('.02'))
        e.place(ticker,a['side'],'sell',quantity,limit,maker=False,targets=[l.id for l in lots],purpose='scalper_'+reason)
        a['retry_at']=now+1

    def step(self,changed_ticker=None):
        e=self.e;now=e.now
        markets=[(changed_ticker,e.markets[changed_ticker])] if changed_ticker in e.markets else ([] if changed_ticker is not None else list(e.markets.items()))
        for ticker,m in markets:
            if not self.matches(ticker,m):continue
            a=self.attempts.get(ticker)
            if a and a.get('first') and not a.get('recorded') and e.book_fresh(ticker) and e.books[ticker].ask('yes') is not None:
                raw=e.tape.sample(ticker,e.books[ticker],now)
                if raw:self.history[ticker]=list(e.tape.state(ticker)['prices'])
            if a and not a.get('first') and not a.get('recorded') and a.get('order_id'):
                old=e.orders.get(a['order_id']);c=self.phase(ticker)
                if old and old.status in ('pending','resting') and e.book_fresh(ticker):
                    current=e.books[ticker].bid(old.side)
                    adverse=current is None or e.books[ticker].ask(old.side) is None
                    if not adverse and ticker in self.history:
                        fresh=self.features(ticker,old.side)
                        adverse=fresh is None or self.decision(fresh)[1] or fresh.get('depth_withdrawal',0)>.5
                    desired=current
                    if not adverse and c['approach']=='market_maker':
                        desired=passive_entry_price(m,current,e.books[ticker].ask(old.side),{},c)
                    moved=desired is not None and abs(desired-old.price)>=tick_size(m,old.price)*D(str(c['reprice_ticks']))
                    if adverse or now-old.created>=c['reprice_seconds'] and (moved or m['close']-now<=c['restrict_entries']):
                        before=len(e.pending);e.cancel(old.id)
                        if len(e.pending)>before:
                            self.increment(a['meta'],repriced=int(moved));a['replace_reason']='adverse_selection' if adverse else 'quote_moved' if moved else 'expiration_phase'
                            e.log('SCALPER_QUOTE_CANCEL',old,reason=a['replace_reason'])

                order=e.orders.get(a['order_id'])
                if order is None or order.status not in ('pending','resting'):
                    a['recorded']=True
                    self.increment(a['meta'],canceled=int(order is not None and order.status in ('cancelled','expired')),missed=1)
                    e.log('SCALPER_UNFILLED',ticker=ticker,reason=order.status if order else 'terminal_order_pruned',details=json.dumps(a))
            if a and a.get('first') and not a.get('recorded'):
                if now>=a.get('retry_at',0):self.manage(ticker,a)
                continue
            if m.get('paid') or now>=m['close'] or m.get('entry_parked') or not self.enabled:continue
            # Sample all markets/variants on the same shared clock frame. This
            # keeps two-second causal observations but amortizes the durable
            # checkpoint over the whole frame instead of one DB write per tick.
            # Position protection above still runs on every relevant book event.
            if getattr(e,'_scalper_source',None) not in (None,'clock'):continue
            if now-self.last_eval.get(ticker,-1e9)<self.config['eval_seconds']:continue
            if not e.book_fresh(ticker):
                self.last_reason='Waiting for fresh verified book';continue
            self.last_eval[ticker]=int(now//2)*2
            book=e.books[ticker]
            if book.bid('yes') is None or book.bid('no') is None:
                self.last_reason='No two-sided liquidity';continue
            if m.pop('entry_recovery_halt',False):self.halted.discard(ticker)
            if ticker in self.halted:
                # Initial fresh full snapshot allows new independent trials.
                if book.snapshot_at>0:self.halted.discard(ticker)
                else:continue
            raw=e.tape.sample(ticker,book,now)
            self.history[ticker]=list(e.tape.state(ticker)['prices'])
            if raw is None or raw['observations']<5:
                self.last_reason=f"Warming up · {raw['observations'] if raw else 0}/5 price samples";continue
            c=self.phase(ticker)
            candidates=[]
            for side in ('yes','no'):
                f=self.features(ticker,side)
                if f is None:continue
                signal,falling,target=self.decision(f)
                reason=None
                if getattr(self,'resource_paused',False):reason='worker_processing_backlog'
                elif f['seconds_remaining']<=c['restrict_entries']:reason='entry_cutoff'
                elif m.get('maker_entry_blocked'):reason='market_or_event_paused'
                elif self.active_orders(ticker):reason='pending_order'
                elif e.wallet.inventory(ticker,'yes') or e.wallet.inventory(ticker,'no'):reason='linked_exposure'
                elif f['spread']>.10 or f['depth']<1 or f['exit_depth']<1:reason='spread_or_depth'
                elif falling:reason='unfavorable_momentum'
                elif not signal:reason='no_reversal_or_range_signal'
                bid,ask=book.bid(side),book.ask(side)
                quantity=position_size(e,ticker,self.contracts,min(D('.9999'),ask+2*tick_size(m,ask)),f,c)
                if quantity<1:
                    if not reason:reason='capital_or_depth_limit'
                    self.observe(ticker,side,reason,f,signal);continue
                execution=execution_choice(e,ticker,side,f,quantity,target,c)
                maker=execution['maker'];price=execution['price'];expected=execution['expected_net']
                f.update(expected_net_at_recent_resistance=float(expected),maker=maker,target=target,
                    execution={k:str(v) if isinstance(v,D) else v for k,v in execution.items()})
                if not reason and (expected<=D(str(c['min_net'])) or price+D(str(target))>=1):reason='cost_exceeds_observed_rebound'
                if not reason and price*quantity+e.fees[ticker].charge(quantity,price,maker)>e.available():reason='portfolio_cash_reserved'
                if not reason:candidates.append((expected,side,quantity,price,maker,target,f))
                # Material observations are recorded once per evaluation, no API calls.
                self.observe(ticker,side,reason or 'candidate_compared',f,signal)
                if reason:self.last_reason=reason.replace('_',' ')
            if not candidates:continue
            expected,side,quantity,price,maker,target,f=max(candidates,key=lambda x:x[0])
            if a and a.get('first') and not a.get('recorded'):continue
            meta=dict(self.metadata(ticker),execution='maker' if maker else 'taker')
            s=e.wallet.stat(ticker)
            self.attempts[ticker]=dict(first=False,recorded=False,side=side,quantity=0.,sold=0.,cost=0.,proceeds=0.,
                started_at=now,baseline=float(s.gross-s.realized_fees),target=target,config=self.config.copy(),meta=meta,
                mfe=0.,mae=0.,verified=True,entry_features=f)
            ident=e.place(ticker,side,'buy',quantity,price,maker=maker,expiry=min(now+c['order_ttl'],m['close']-c['liquidate']),purpose='scalper_entry')
            self.attempts[ticker]['order_id']=ident
            e.log('SCALPER_ENTRY_DECISION',ticker=ticker,order_id=ident,side=side,details=json.dumps(dict(
                **meta,features=f,quantity=str(quantity),price=str(price),maker=maker,expected_net=float(expected),
                simulated_order_status=e.orders[ident].status,config=self.config,execution_not_guaranteed=True)))
            self.increment(meta,attempted=1,submitted=int(e.orders[ident].status=='pending'),maker_submitted=int(maker and e.orders[ident].status=='pending'),taker_submitted=int(not maker and e.orders[ident].status=='pending'))
            self.last_reason=f'Paper {"maker" if maker else "taker"} entry submitted · {side.upper()}'

    def research_snapshot(self):
        r=self.research
        def report(c):
            n=c['completed'];f=c['fill_events']
            return dict(c,maker_fill_rate=c['maker_entry_orders_filled']/c['maker_submitted'] if c['maker_submitted'] else None,average_spread=c['spread_sum']/c['spread_rounds'] if c['spread_rounds'] else None,win_rate=100*c['wins']/n if n else None,average_net=c['round_net']/n if n else None,
                average_holding_seconds=c['holding_seconds']/n if n else None,
                average_fill_seconds=c['fill_seconds']/f if f else None,
                execution_success=c['entry_orders_filled']/c['submitted'] if c['submitted'] else None,
                net_per_dollar_hour=c['net']/c['dollar_hours'] if c['dollar_hours'] else None)
        positions=[l for l in self.e.wallet.lots]
        priced=all(self.e.book_fresh(l.ticker) and self.e.books[l.ticker].bid(l.side) is not None for l in positions)
        equity=float(self.e.wallet.cash+sum((l.quantity*self.e.books[l.ticker].bid(l.side) for l in positions),ZERO)) if priced else None
        if equity is not None:
            r['equity_peak']=max(r.get('equity_peak',float(self.e.wallet.deposits)),equity)
            r['equity_drawdown']=max(r.get('equity_drawdown',0),r['equity_peak']-equity)
        return dict(marked_equity=equity,max_equity_drawdown=r.get('equity_drawdown',0),drawdown_incomplete=not priced,totals=report(r['totals']),cells=[report(c) for c in r['cells'].values() if c['entry_fills'] or c['completed'] or c['settlement_carryovers']],recent=r['recent'],
            config=self.config,automatic_optimization=False,price_window_seconds=120,evaluation_interval_seconds=2,
            execution_model='trade-print-queue-and-latent-IOC',maker_exits=bool(self.config.get('maker_profit_exits')),approach=self.config['approach'],
            committed_capital=str(committed(self.e)),capital_utilization=float(committed(self.e)/max(D(1),self.e.wallet.deposits)),
            shared_feature_calculations=self.e.tape.calculations)
