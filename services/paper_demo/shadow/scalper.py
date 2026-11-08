"""Causal, experimental scalping over the existing read-only paper execution feed.

Parameters are versioned hypotheses, never fitted or promoted by these observations.
Public trades, not quote touches, drive maker executions in Engine.
"""
import json
import math
import statistics
from decimal import Decimal as D, ROUND_FLOOR
from .core import ConvexityStrategy, Engine, ZERO

SCALPER_FOLDERS=('volatility_scalper','scalper_fixed','scalper_grid')
CONFIGS={
    'volatility_scalper':dict(approach='mean_reversion',adaptive=True,mixed=True,take_profit=.025,stop_loss=.07,min_hold=1,max_hold=90,liquidate=30),
    'scalper_fixed':dict(approach='mean_reversion',adaptive=False,mixed=False,maker_profit_exits=True,take_profit=.03,stop_loss=.05,min_hold=0,max_hold=60,liquidate=60),
    'scalper_grid':dict(approach='range_grid',adaptive=True,mixed=True,take_profit=.02,stop_loss=.09,min_hold=2,max_hold=120,liquidate=45),
}

def dimensions(profile,market):
    series=profile['series']
    asset=profile.get('underlying') or series.removeprefix('KX').removesuffix('15M')
    category=profile.get('market_category','other')
    duration=round(market['close']-market.get('open',market['close']-900))
    return dict(category=category,underlying=asset,series=series,duration_seconds=duration)


def horizon(seconds):
    return '0–1m' if seconds<=60 else '1–3m' if seconds<=180 else '3–5m' if seconds<=300 else '5–10m' if seconds<=600 else '10m+'


def bucket():
    return dict(opportunities=0,submitted=0,entry_orders_filled=0,entry_fills=0,exit_fills=0,completed=0,wins=0,settlement_carryovers=0,
        net=0.,round_net=0.,verified_completed=0,verified_net=0.,holding_seconds=0.,profitable_exit_seconds=0.,profitable_exits=0,fill_seconds=0.,fill_events=0,
        dollar_hours=0.,peak=0.,max_drawdown=0.,rejections={})



class ScalperEngine(Engine):
    """Portfolio-local queue uncertainty, without changing other strategies."""
    def handle(self,source,payload,now):
        self._scalper_source=source
        try:return super().handle(source,payload,now)
        finally:self._scalper_source=None

    def arrive(self,order):
        super().arrive(order)
        if order.maker and order.status=='resting':
            # Unknown queue insertion/hidden competition. Seeded for replay;
            # resting volume must still be cleared by actual trade prints.
            extra=(order.ahead+order.quantity)*D(str(self.rng.uniform(.05,.35)))
            order.ahead+=extra
            self.log('SCALPER_QUEUE_ESTIMATE',order,details=json.dumps(dict(
                hidden_competition=str(extra),model='displayed-FIFO-plus-seeded-5-to-35-percent')))

class VolatilityScalper(ConvexityStrategy):
    recover_fresh_entries=True
    def __init__(self,engine,profile):
        super().__init__(engine,profile['contracts'],False,profile['series'],profile['name'])
        self.profile=profile
        self.config=dict(CONFIGS[profile['folder_id']])
        self.attempts={};self.history={};self.last_eval={};self.last_signature={}
        self.research=dict(totals=bucket(),cells={},recent=[])
        self.last_reason='Warming up · needs 5 fresh price samples; paper only'

    def export_state(self):
        # Do not restore price windows over a disconnected interval.
        return dict(research=self.research,config=self.config)

    def restore_state(self,data):
        self.research=data.get('research',self.research)
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
            config_version=self.profile.get('version','scalper-1'),execution='observed')

    def cells(self,meta):
        key='|'.join(str(meta[k]) for k in ('category','underlying','duration_seconds','horizon','split','execution'))
        cell=self.research['cells'].setdefault(key,dict(bucket(),dimensions=meta))
        return (self.research['totals'],cell)

    def increment(self,meta,**values):
        for cell in self.cells(meta):
            for k,v in values.items():cell[k]+=v

    def observe(self,ticker,side,reason,features,signal=False,submitted=False):
        meta=self.metadata(ticker)
        self.increment(meta,opportunities=int(signal),submitted=int(submitted))
        if reason:
            for cell in self.cells(meta):
                counts=cell['rejections'];counts[reason]=counts.get(reason,0)+1
        signature=(reason,signal,features['bid'],features['ask'])
        key=(ticker,side)
        if self.last_signature.get(key)==signature:return
        self.last_signature[key]=signature
        self.e.log('SCALPER_OPPORTUNITY',ticker=ticker,side=side,reason=reason or 'paper order submitted',
            details=json.dumps(dict(**meta,features={k:v for k,v in features.items() if k!='recent_prices'},signal=signal,submitted=submitted,
                config=self.config,observed_opportunity=signal,executable_at_decision=submitted,
                execution_not_guaranteed=True,reversal_probability=None)))

    def features(self,ticker,side):
        history=self.history[ticker];book=self.e.books[ticker]
        prices=[p if side=='yes' else 1-p for _,p in history]
        changes=[b-a for a,b in zip(prices,prices[1:])]
        sigma=statistics.pstdev(prices) if len(prices)>1 else 0
        movement=statistics.mean(abs(x) for x in changes) if changes else 0
        turns=sum(a*b<0 for a,b in zip(changes,changes[1:]))
        seconds=max(1,history[-1][0]-history[0][0])
        bid,ask=book.bid(side),book.ask(side)
        depth=sum((q for _,q in list(book.iter_depth(side,'buy'))[:3]),ZERO)
        exit_depth=sum((q for _,q in list(book.iter_depth(side,'sell'))[:3]),ZERO)
        return dict(bid=float(bid),ask=float(ask),spread=float(ask-bid),depth=float(depth),exit_depth=float(exit_depth),
            mean=statistics.mean(prices),sigma=sigma,movement=movement,movements_per_minute=sum(abs(c)>=.01 for c in changes)*60/seconds,
            reversals=turns,reversal_frequency=turns*60/seconds,support=min(prices),resistance=max(prices),
            last_change=changes[-1] if changes else 0,trend=prices[-1]-prices[max(0,len(prices)-6)],
            displacement=statistics.mean(prices)-prices[-1],seconds_remaining=self.e.markets[ticker]['close']-self.e.now,
            recent_prices=history[-20:],observations=len(prices))

    def decision(self,features):
        c=self.config;f=features
        threshold=max(.01,min(.05,f['sigma']*.55)) if c['adaptive'] else .02
        spacing=max(.01,min(.07,f['sigma']*.9)) if c['adaptive'] else c['take_profit']
        if c['approach']=='range_grid':
            signal=f['resistance']-f['support']>=spacing and f['bid']<=f['support']+spacing*.6
        else:
            signal=f['displacement']>=threshold and f['last_change']>=0
        # Momentum filter is intentionally broad, with its rejected signals recorded.
        falling=f['trend']<-max(.06,3*f['sigma']) and f['last_change']<0
        target=max(c['take_profit'],spacing)
        return signal,falling,target

    def active_orders(self,ticker):
        return [o for o in self.e.orders.values() if o.ticker==ticker and o.status in ('pending','resting')]

    def on_fill(self,order,quantity):
        a=self.attempts.get(order.ticker)
        if not a or a.get('recorded'):return
        execution=self.e._recent_fills[order.id][-1]
        raw_price=D(execution['price'])
        maker_exit=order.purpose=='scalper_maker_profit_exit'
        price=1-raw_price if maker_exit else raw_price
        fee=self.e.fees[order.ticker].charge(quantity,raw_price,order.maker)
        meta=a['meta'];wait=self.e.now-order.created
        self.increment(meta,fill_seconds=wait,fill_events=1,**{'entry_fills' if order.action=='buy' and not maker_exit else 'exit_fills':1})
        self.e.log('SCALPER_EXECUTION',order,quantity=quantity,price=price,fee=fee,
            details=json.dumps(dict(**meta,maker=order.maker,submission_to_fill_seconds=wait,
                time_to_profitable_exit_seconds=(self.e.now-a.get('entered_at',self.e.now)) if (order.action=='sell' or maker_exit) and price>D(str(a.get('average_price',1))) else None)))
        if order.action=='buy' and not maker_exit:
            if not a.get('first'):self.increment(meta,entry_orders_filled=1)
            a.setdefault('entered_at',self.e.now)
            a['quantity']=float(D(str(a['quantity']))+quantity)
            a['cost']=float(D(str(a['cost']))+quantity*price+fee)
            a['average_price']=a['cost']/a['quantity']
            a['first']=True
            a.setdefault('entry_execution','maker' if order.maker else 'taker')
            # Cancel remaining partial entry; wait for acknowledgement before exits.
            self.e.cancel_buys(order.ticker)
        else:
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
        self.increment(a['meta'],round_net=net if not settlement else 0,verified_completed=int(not settlement and a['verified']),verified_net=net if a['verified'] else 0,completed=int(not settlement),wins=int(net>0 and not settlement),net=net,
            settlement_carryovers=int(settlement),holding_seconds=held if not settlement else 0,
            dollar_hours=a['cost']*held/3600,profitable_exits=int(bool(a.get('profitable_at'))),
            profitable_exit_seconds=a.get('profitable_at',a['entered_at'])-a['entered_at'])
        for cell in self.cells(a['meta']):
            cell['peak']=max(cell['peak'],cell['net'])
            cell['max_drawdown']=max(cell['max_drawdown'],cell['peak']-cell['net'])
        row=dict(a,ticker=ticker,exit_at=self.e.now)
        compact={k:v for k,v in row.items() if k not in ('entry_features','config')}
        self.research['recent']=(self.research['recent']+[compact])[-20:]
        self.e.log('SCALPER_ROUND_TRIP' if not settlement else 'SCALPER_SETTLEMENT_CARRYOVER',ticker=ticker,
            details=json.dumps(row))
        self.last_reason='Round trip complete · evaluating the next movement' if not settlement else 'Scalp carried into settlement · included as a failed liquidation'

    def manage(self,ticker,a):
        e=self.e;now=e.now;m=e.markets[ticker];c=a['config'];remaining=m['close']-now
        if m.get('paid'):
            self.finish(ticker,True);return
        lots=[l for l in e.wallet.lots if l.ticker==ticker]
        if not lots:return
        bid=e.books[ticker].bid(a['side']) if e.book_fresh(ticker) else None
        if bid is not None:
            move=float(bid)-a['average_price']
            a['mfe']=max(a['mfe'],move);a['mae']=min(a['mae'],move)
        urgent=remaining<=c['liquidate'] or now-a['entered_at']>=c['max_hold']
        if urgent:e.cancel_buys(ticker)
        if remaining<=0 or bid is None or bid<=0:
            reason='closed_before_liquidation' if remaining<=0 else 'liquidation_missing_fresh_bid'
            if urgent and now-a.get('blocked_at',-1e9)>=10:
                a['blocked_at']=now
                e.log('SCALPER_LIQUIDATION_BLOCKED',ticker=ticker,reason=reason,details=json.dumps(dict(time_remaining=remaining)))
            return
        active=self.active_orders(ticker)
        if active:
            if urgent or bid is not None and float(bid)-a['average_price']<=-c['stop_loss']:
                for order in active:e.cancel(order.id)
            return
        quantity=sum((l.quantity for l in lots),ZERO)
        fee=e.fees[ticker].charge(quantity,bid)/quantity
        net_move=float(bid-fee)-a['average_price']
        stop=net_move<=-c['stop_loss']
        take=net_move>=a['target'] and now-a['entered_at']>=c['min_hold']
        a['peak_net']=max(a.get('peak_net',net_move),net_move)
        trail=a['peak_net']>=a['target'] and net_move<=a['peak_net']-max(.01,a['target']*.5)
        if c.get('maker_profit_exits') and not (urgent or stop or trail):
            # A passive sale is economically identical to buying the opposite
            # outcome and netting its guaranteed $1 collateral with our lot.
            # This reuses the existing maker queue and complementary wallet.
            desired=min(D('.99'),D(str(a['average_price']+a['target']+.005)).quantize(D('.01')))
            passive_ask=e.books[ticker].ask(a['side'])
            if passive_ask is None:passive_ask=min(D('.9999'),bid+D('.01'))
            desired=max(desired,passive_ask)
            complement=1-desired
            opposite='no' if a['side']=='yes' else 'yes'
            if complement<e.books[ticker].ask(opposite):
                e.place(ticker,opposite,'buy',quantity,complement,maker=True,
                    expiry=min(now+10,m['close']-c['liquidate']),purpose='scalper_maker_profit_exit')
                a['exit_reason']='maker_profit_exit'
            return
        if not (urgent or stop or take or trail):return
        if take and not urgent and not stop and not a.get('partial_taken') and quantity>=2:
            quantity=(quantity/2).to_integral_value(rounding=ROUND_FLOOR)
        reason='time_liquidation' if urgent else 'stop_loss' if stop else 'trailing_exit' if trail else 'partial_profit' if quantity<sum((l.quantity for l in lots),ZERO) else 'take_profit'
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
            if not ticker.startswith(self.series+'-'):continue
            a=self.attempts.get(ticker)
            if a and not a.get('first') and not a.get('recorded') and a.get('order_id'):
                order=e.orders.get(a['order_id'])
                if order is None or order.status not in ('pending','resting'):
                    a['recorded']=True
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
            if now-self.last_eval.get(ticker,-1e9)<2:continue
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
            prices=self.history.setdefault(ticker,[])
            prices.append((now,float((book.bid('yes')+book.ask('yes'))/2)))
            prices[:]=[(at,p) for at,p in prices[-60:] if at>=now-120]
            if len(prices)<5:
                self.last_reason=f'Warming up · {len(prices)}/5 price samples';continue
            candidates=[]
            for side in ('yes','no'):
                f=self.features(ticker,side);signal,falling,target=self.decision(f)
                reason=None
                if getattr(self,'resource_paused',False):reason='worker_processing_backlog'
                elif f['seconds_remaining']<=self.config['liquidate']+10:reason='entry_cutoff'
                elif self.active_orders(ticker):reason='pending_order'
                elif e.wallet.inventory(ticker,'yes') or e.wallet.inventory(ticker,'no'):reason='linked_exposure'
                elif f['spread']>.10 or f['depth']<1 or f['exit_depth']<1:reason='spread_or_depth'
                elif falling:reason='unfavorable_momentum'
                elif not signal:reason='no_reversal_or_range_signal'
                bid,ask=book.bid(side),book.ask(side)
                maker=not(self.config['mixed'] and f['last_change']>=.01-1e-9 and f['displacement']>=.04)
                price=bid if maker else ask
                quantity=min(self.contracts,D(5),D(str(math.floor(f['depth']))))
                fee=e.fees[ticker].charge(quantity,price,maker)+e.fees[ticker].charge(quantity,min(D('.99'),price+D(str(target))))
                potential=min(D('.99'),D(str(f['resistance'])))
                expected=(potential-price)*quantity-fee
                f.update(expected_net_at_recent_resistance=float(expected),estimated_round_trip_fees=float(fee),maker=maker,target=target)
                if not reason and (expected<=0 or price+D(str(target))>=1):reason='cost_exceeds_observed_rebound'
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
            ident=e.place(ticker,side,'buy',quantity,price,maker=maker,expiry=min(now+10,m['close']-self.config['liquidate']),purpose='scalper_entry')
            self.attempts[ticker]['order_id']=ident
            e.log('SCALPER_ENTRY_DECISION',ticker=ticker,order_id=ident,side=side,details=json.dumps(dict(
                **meta,features=f,quantity=str(quantity),price=str(price),maker=maker,expected_net=float(expected),
                simulated_order_status=e.orders[ident].status,config=self.config,execution_not_guaranteed=True)))
            self.increment(meta,submitted=1)
            self.last_reason=f'Paper {"maker" if maker else "taker"} entry submitted · {side.upper()}'

    def research_snapshot(self):
        r=self.research
        def report(c):
            n=c['completed'];f=c['fill_events']
            return dict(c,win_rate=100*c['wins']/n if n else None,average_net=c['round_net']/n if n else None,
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
            execution_model='trade-print-queue-and-latent-IOC',maker_exits=bool(self.config.get('maker_profit_exits')))
