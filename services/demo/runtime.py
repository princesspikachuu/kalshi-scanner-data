"""Single fenced Demo worker. Bounded stream, durable intents, verified recovery."""
import json,os,time,signal,threading,hashlib,traceback,math
from datetime import datetime,timezone
from decimal import Decimal
from uuid import uuid5,NAMESPACE_URL
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .store import DemoStore
from .orderbook import OrderBooks
from .exchange import Exchange,ExchangeFailure,credentials,WS
from .engine import candidates,quantity,qualifies,exit_price,wire_order,protective_threshold,entry_protection_matches

LOCK=723741931
TERMINAL=('executed','canceled','cancelled')
def number(value):return float(Decimal(str(value or '0')))
def cents(value):return round(number(value)*100)
def count(raw,key):return number(raw.get(key+'_fp',raw.get(key,0)))
def timestamp(value):
    if isinstance(value,(int,float)):return float(value)
    return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()

def quote(raw,now):
    try:
        ticker=raw['ticker'];bid=cents(raw['yes_bid_dollars']);ask=cents(raw['yes_ask_dollars'])
        return ticker,dict(bid=bid,ask=ask,at=now,close=timestamp(raw['close_time']),
            exchange_index=raw.get('exchange_index',0),series=raw.get('series_ticker') or ticker.split('-')[0],result=raw.get('result'),status=raw.get('status'))
    except (KeyError,ValueError,TypeError):return None

class Worker:
    def __init__(self,store,exchange,stop,guard):
        self.store,self.exchange,self.stop,self.guard=store,exchange,stop,guard
        self.quotes={};self.states={};self.bots=[];self.orders=[];self.blocked=set();self.account={}
        self.last_reconcile=0;self.last_discovery=0;self.last_health=0;self.last_snapshot=0;self.last_diagnostic=0;self.stage="starting"
        self.socket=None;self.subscription=set();self.book_sid=None;self.stream_command=2;self.sequence={};self.recovered=False;self.series_index=0;self.discovery_turn=0
        self.funding=None;self.shard_reservations={};self.rejections_repaired=False
        self.legacy_exit_evidence=None;self.issue=None;self.last_health_state=None;self.context_market=None;self.context_order=None;self.context_bot=None
        self.book_pong=None;self.last_book_ping=0;self.books=OrderBooks();self.cursor={};self.last_discovered={};self.last_account_write=0;self.trigger_digest={};self.order_cache={};self.bot_revisions={}
    def entry_diagnostics(self,now):
        from .engine import entry_price,side_quote
        summary={}
        for bot in self.bots:
            config=bot['config'];matched=fresh=available=submitted=blocked=maker=budget=stop_blocked=minimum=0
            market_exposure={};bot_exposure=0;exit_waiting=None
            for entry in self.orders:
                if entry['kind']!='entry' or entry['bot']!=bot['id'] or not entry.get('exit_triggered') or entry.get('filled',0)<=entry.get('sold',0):continue
                q=self.quotes.get(entry['ticker']);ceiling=entry.get('exit_ceiling_cents')
                working=any(o.get('parent')==entry['client_id'] and o['status'] not in ('closed','rejected') for o in self.orders)
                if q and now-q['at']<=5 and now<q['close'] and ceiling is not None and not working and side_quote(q,entry['side'])[0]>=ceiling:
                    exit_waiting=f'Protective exit retains its {ceiling}¢ limit, which would now cross the current bid; waiting for a maker-only quote'
                    break
            for order in self.orders:
                if order['kind']!='entry':continue
                amount=(order.get('remaining',0)+max(0,order.get('filled',0)-order.get('sold',0)))*order['price']
                market_exposure[order['ticker']]=market_exposure.get(order['ticker'],0)+amount
                if order['bot']==bot['id']:bot_exposure+=amount
            for ticker,q in self.quotes.items():
                from services.research.reports import SERIES
                if not any(q['series'] in SERIES[s['asset']] for s in config['squares']):continue
                available+=1
                if now-q['at']>5:continue
                fresh+=1
                for index,square in enumerate(config['squares']):
                    for side in ('yes','no'):
                        if not qualifies(square,q,side,now,config['qualification']):continue
                        matched+=1
                        if ticker in self.blocked:blocked+=1;continue
                        if self.states.get(bot['id'],{}).get(f'{ticker}/{index}/{side}',{}).get('submitted'):submitted+=1;continue
                        if not entry_protection_matches(config,square,q,side):stop_blocked+=1;continue
                        price=entry_price(config,q,side)
                        if price is None:
                            if config.get('minimum_cents') is not None and entry_price(dict(config,minimum_cents=None),q,side) is not None:minimum+=1
                            else:maker+=1
                            continue
                        if quantity(config,price,self.account.get('equity_cents',0),self.account.get('cash_cents',0),market_exposure.get(ticker,0),bot_exposure)<1:budget+=1
            if exit_waiting:message=exit_waiting
            elif bot['desired']!='running':message='New entries paused'
            elif not available:message='No open Demo markets found for these categories yet'
            elif not fresh:message=f'{available} Demo markets found; waiting for fresh streaming prices'
            elif not matched:message=f'{fresh} fresh Demo markets checked; none match the selected price/time windows'
            elif blocked==matched:message='Matching markets need ownership reconciliation'
            elif submitted==matched:message='Matching conditions already attempted; waiting for a new qualifying cycle'
            elif stop_blocked==matched:message='Entry skipped: current ASK is already at or below the protective exit trigger'
            elif minimum==matched:message='Matching conditions found; calculated bids are below the minimum bid'
            elif maker==matched:message='Matching conditions found; entry price would cross the ask'
            elif budget==matched:message='Matching conditions found; spending limits cannot fund one contract'
            else:message=f'{matched} matching conditions across {fresh} fresh Demo markets'
            summary[bot['id']]=dict(message=message,markets=available,fresh=fresh,matches=matched,attempted=submitted,blocked=blocked,maker_blocked=maker,budget_blocked=budget,exit_blocked=stop_blocked,minimum_blocked=minimum,exit_waiting=bool(exit_waiting))
        return summary
    def health(self,state,message):
        now=time.time()
        if state=='ready':self.issue=None
        if now-self.last_health>=10 or state!=self.last_health_state:
            self.store.put('health',dict(state=state,message=message,at=now,
                watched=len(self.quotes),read_requests=self.exchange.reads,write_requests=self.exchange.writes,
                reconciled_at=self.last_reconcile,blocked_markets=sorted(self.blocked),bots=self.entry_diagnostics(now),issue=self.issue))
            self.last_health=now;self.last_health_state=state
        if now-self.last_diagnostic>=60:
            print(json.dumps(dict(event='demo_diagnostic',state=state,stage=self.stage,
                running=sum(b['desired']=='running' for b in self.bots),bots=len(self.bots),
                conditions=sum(len(b['config']['squares']) for b in self.bots if b['desired']=='running'),
                categories=sorted({s['asset'] for b in self.bots if b['desired']=='running' for s in b['config']['squares']}),
                watched=len(self.quotes),fresh=sum(now-q['at']<=5 for q in self.quotes.values()),
                orders=len(self.orders),read_requests=self.exchange.reads,write_requests=self.exchange.writes,
                reconciled=self.recovered,entry_diagnostics=self.entry_diagnostics(now))),flush=True)
            self.last_diagnostic=now
    def load_bots(self):
        self.bots=[]
        for row in self.store.rows('bot/',100):
            key=row['idempotency_key'].split('/')[-1]
            self.bots.append(dict(id=key,config=row['parameters']['config'],revision=row['parameters']['revision'],**row['progress']))
            if key not in self.states or self.bot_revisions.get(key)!=row['parameters']['revision']:
                prior=self.store.get('trigger/'+key)
                self.states[key]=prior['progress'] if prior and prior['parameters'].get('revision')==row['parameters']['revision'] else {}
                self.bot_revisions[key]=row['parameters']['revision']
                self.trigger_digest[key]=json.dumps(self.states[key],sort_keys=True)
                config=row['parameters']['config']
                print(json.dumps(dict(event='demo_entry_policy',categories=sorted({s['asset'] for s in config['squares']}),
                    qualification=config['qualification'],price_reference=config['price_reference'],
                    adjustment_cents=config['adjustment_cents'],maximum_cents=config.get('maximum_cents'),minimum_cents=config.get('minimum_cents'))),flush=True)
        self.orders=self.store.active_orders()
        active={o['client_id'] for o in self.orders}
        self.order_cache={k:v for k,v in self.order_cache.items() if k in active}
    def repair_rejected_entries(self):
        if self.rejections_repaired:return
        with self.store.pool.connection() as c:
            rows=c.execute("""SELECT parameters,progress FROM research_job
                WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                AND parameters->>'kind'='entry' AND progress->>'status'='rejected'
                AND NOT(parameters ? 'funding_retry_v1') ORDER BY created_at DESC LIMIT 501""").fetchall()
        if len(rows)>500:raise ExchangeFailure('rejected_order_repair_capacity')
        bots={b['id']:b for b in self.bots}
        for row in rows:
            order={**row['parameters'],**row['progress']};bot=bots.get(order['bot'])
            if bot and order['revision']==bot['revision']:
                key=f"{order['ticker']}/{order['square']}/{order['side']}"
                memory=self.states.get(bot['id'],{}).get(key)
                if memory and memory.get('submitted'):
                    memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
                    self.store.put('trigger/'+bot['id'],self.states[bot['id']],parameters=dict(revision=bot['revision']))
            order['funding_retry_v1']=True;self.save_order(order)
        self.rejections_repaired=True
    def save_order(self,order):
        data={k:v for k,v in order.items() if k not in ('status','filled','remaining','fees','exchange_id','closed_at','realized_cents')}
        state={k:v for k,v in order.items() if k in ('status','filled','remaining','fees','exchange_id','closed_at','realized_cents')}
        packed=json.dumps([data,state],sort_keys=True)
        if self.order_cache.get(order['client_id'])!=packed:
            self.store.put('order/'+order['client_id'],state,parameters=data)
            self.order_cache[order['client_id']]=packed
    def record(self,kind,order,message,**detail):
        self.store.event(kind,message,bot=order.get('bot'),ticker=order.get('ticker'),details=dict(order_kind=order.get('kind'),client_id=order.get('client_id'),exchange_id=order.get('exchange_id'),side=order.get('side'),price=order.get('price'),quantity=order.get('quantity'),condition=order.get('condition'),quote=self.quotes.get(order.get('ticker')),**detail))
    def reconcile(self):
        """Complete paginated exchange state; gaps never manufacture fills."""
        now=time.time();self.load_bots()
        balance=self.exchange.call('GET','/portfolio/balance')
        positions=list(self.exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
        # Resting orders include manual orders. Recent records resolve lost responses.
        remote=list(self.exchange.pages('/portfolio/orders','orders',status='resting'))
        self.shard_reservations={}
        for raw in remote:
            index=raw.get('exchange_index',0)
            # Conservative full contract collateral for all resting orders,
            # including manual orders; never sweep their reserved collateral.
            self.shard_reservations[index]=self.shard_reservations.get(index,0)+math.ceil(count(raw,'remaining_count')*100)
        earliest=min((o['created_at'] for o in self.orders),default=now)
        recent=list(self.exchange.pages('/portfolio/orders','orders',min_ts=int(earliest)-60)) if self.orders else []
        by_client={o.get('client_order_id'):o for o in remote+recent}
        known_ids={o['client_id'] for o in self.orders};blocked={o['ticker'] for o in remote if o.get('client_order_id') not in known_ids}
        for order in self.orders:
            self.context_market=order['ticker'];self.context_order=order.get('exchange_id') or order['client_id'];self.context_bot=order['bot']
            raw=by_client.get(order['client_id'])
            if raw is None and order.get('exchange_id'):
                result=self.exchange.call('GET','/portfolio/orders/'+order['exchange_id']);raw=result.get('order',result)
            if raw is None:
                # A durable intent may have crossed the network before a crash.
                # Absence in paginated history is not permission to submit again.
                order['status']='uncertain';blocked.add(order['ticker']);self.save_order(order);continue
            previous=order.get('filled',0);prior_status=order.get('status')
            order.update(exchange_id=raw['order_id'],filled=count(raw,'fill_count'),remaining=count(raw,'remaining_count'),
                fees=cents(raw.get('maker_fees_dollars',0))+cents(raw.get('taker_fees_dollars',0)))
            order['status']='resting' if raw['status']=='resting' else 'held' if order['kind']=='entry' and order['filled'] else 'closed'
            if order['kind']=='exit' and raw['status'] in TERMINAL:order['status']='closed'
            self.save_order(order)
            if order['filled']>previous:self.record('fill',order,'Exchange-confirmed '+order['kind']+' fill',filled=order['filled'])
            if prior_status not in ('closed','held') and order['status']=='closed':self.record('cancel',order,'Exchange order is no longer resting')
        # Reload includes fills committed above and closed exits for per-entry allocation.
        parents=[o['client_id'] for o in self.orders if o['kind']=='entry']
        with self.store.pool.connection() as c:
            exits=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz' AND parameters->>'kind'='exit' AND parameters->>'parent'=ANY(%s) AND progress->>'filled' IS NOT NULL LIMIT 5001",(parents,)).fetchall()
        if len(exits)>5000:raise ExchangeFailure('entry_exit_reconciliation_capacity')
        sold={};exit_fees={}
        for row in exits:
            parent=row['parameters'].get('parent')
            sold[parent]=sold.get(parent,0)+row['progress'].get('filled',0)
            exit_fees[parent]=exit_fees.get(parent,0)+row['progress'].get('fees',0)
        self.orders=self.store.active_orders()
        for order in self.orders:
            if order['kind']=='entry':
                order['sold']=sold.get(order['client_id'],0)
                if order.get('filled',0)>0 and order['sold']>=order['filled'] and order.get('remaining',0)==0:
                    sale_total=sum(r['progress'].get('filled',0)*r['parameters']['price'] for r in exits if r['parameters'].get('parent')==order['client_id'])
                    order['realized_cents']=round(sale_total-order['filled']*order['price']-order.get('fees',0)-exit_fees.get(order['client_id'],0))
                    order['status']='closed';order['closed_at']=now;self.save_order(order)
                    self.record('realized',order,'Entry fully exited',realized_cents=order['realized_cents'])
        expected={}
        for order in self.orders:
            if order['kind']=='entry':
                order['sold']=sold.get(order['client_id'],0)
                posted=[r['parameters']['price'] for r in exits if r['parameters'].get('parent')==order['client_id'] and r['progress'].get('status')!='rejected' and r['parameters'].get('created_at',0)>=order.get('exit_rule_started_at',0)]
                if posted:order['exit_ceiling_cents']=min(order.get('exit_ceiling_cents',99),*posted)
                self.save_order(order)
            if order['kind']=='entry' and order['status']!='closed':expected[order['ticker']]=expected.get(order['ticker'],0)+(order.get('filled',0)-sold.get(order['client_id'],0))*(1 if order['side']=='yes' else -1)
        actual={p['ticker']:number(p.get('position_fp',p.get('position',0))) for p in positions}
        for ticker in set(expected)|set(actual):
            q=self.quotes.get(ticker)
            if q and q.get('status') in ('settled','finalized') and q.get('result') in ('yes','no'):
                for order in self.orders:
                    if order['kind']=='entry' and order['ticker']==ticker and order.get('filled',0)>order.get('sold',0):
                        payout=100 if q.get('result')==order['side'] else 0
                        sale_total=sum(r['progress'].get('filled',0)*r['parameters']['price'] for r in exits if r['parameters'].get('parent')==order['client_id'])
                        order['realized_cents']=round(sale_total+(order['filled']-order.get('sold',0))*payout-order['filled']*order['price']-order.get('fees',0)-exit_fees.get(order['client_id'],0))
                        order.update(status='closed',closed_at=now);self.save_order(order)
                        self.record('settlement',order,'Exchange-confirmed settlement',realized_cents=order['realized_cents'])
                continue
            if abs(expected.get(ticker,0)-actual.get(ticker,0))>.001:blocked.add(ticker)
        self.blocked=blocked
        if blocked:self.store.alert('ownership','New entries paused in '+str(len(blocked))+' market(s): manual or unreconciled exposure. Unrelated markets continue.',True)
        else:self.store.clear_alert('ownership')
        self.account=dict(cash_cents=int(balance['balance']),position_value_cents=int(balance['portfolio_value']),
            equity_cents=int(balance['balance'])+int(balance['portfolio_value']),at=now,
            held_markets=len([p for p in positions if number(p.get('position_fp',p.get('position',0)))]))
        self.store.put('account',self.account)
        if int(now//900)!=int(self.last_snapshot//900):
            self.store.put('equity/'+str(int(now//900)),dict(at=now,value=self.account['equity_cents']));self.last_snapshot=now
        self.last_reconcile=now;self.recovered=True
        self.store.clear_alert('recovery');self.store.clear_alert('exchange')
    def discover(self):
        now=time.time()
        from services.research.reports import SERIES
        series=sorted({s for b in self.bots if b['desired']=='running' for q in b['config']['squares'] for s in SERIES[q['asset']]})
        pinned={o['ticker'] for o in self.orders}
        if pinned and (self.discovery_turn%5==0 or not series):params=dict(tickers=','.join(sorted(pinned)[:100]),limit=200)
        elif series:
            current=series[self.series_index%len(series)];params=dict(series_ticker=current,status='open',limit=200,min_close_ts=int(now),max_close_ts=int(now+86400))
            if self.cursor.get(current):params['cursor']=self.cursor[current]
        else:self.last_discovery=now;return
        page=self.exchange.call('GET','/markets',params=params)
        if not isinstance(page.get('markets'),list) or len(page['markets'])>200:raise ExchangeFailure('discovery_capacity')
        if 'series_ticker' in params:self.cursor[params['series_ticker']]=page.get('cursor') or ''
        for raw in page['markets']:
            parsed=quote(raw,now)
            if parsed:
                ticker,q=parsed
                # REST discovery does not qualify a new trade; wait for stream verification.
                old=self.quotes.get(ticker)
                if old:
                    # Price and observation time are one piece of evidence. REST
                    # metadata must not replace a verified stream price while
                    # inheriting its timestamp (including stale stream quotes).
                    q=dict(old,close=q['close'],status=q['status'],result=q['result'],exchange_index=q['exchange_index'],series=q['series'])
                else:q['at']=0
                self.quotes[ticker]=q;self.last_discovered[ticker]=now
        rank=lambda item:(item[0] not in pinned,item[1]['close'],item[0])
        kept=[(t,q) for t,q in self.quotes.items() if t in pinned or q['close']>now]
        self.quotes=dict(sorted(kept,key=rank)[:100]);self.last_discovered={t:v for t,v in self.last_discovered.items() if t in self.quotes};self.last_discovery=now;self.discovery_turn+=1
        if 'series_ticker' in params:self.series_index+=1
    def observe_exit_triggers(self,ticker,now,previous=None):
        """Latch the first crossing before another ticker message can replace it."""
        from .engine import side_quote
        q=self.quotes.get(ticker)
        if not q or now-q['at']>5 or now>=q['close'] or ticker in self.blocked:return False
        bots={b['id']:b for b in self.bots};triggered=False
        for order in self.orders:
            if order['ticker']!=ticker or order['kind']!='entry' or order.get('exit_triggered') or order.get('status')=='uncertain' or order.get('filled',0)<=order.get('sold',0):continue
            bot=bots.get(order['bot'])
            if not bot:continue
            threshold=protective_threshold(bot['config'],bot['config']['squares'][order['square']])
            bid,ask=side_quote(q,order['side'])
            if threshold is None or not 0<=bid<ask<100 or ask>threshold:continue
            if q.get('source')=='orderbook' and not q.get('book_ready'):continue
            order['exit_triggered']=True;order['exit_reference']='ask';self.save_order(order)
            prior_ask=side_quote(previous,order['side'])[1] if previous else None
            gap=round(q.get('event_at',q['at'])-previous.get('event_at',previous['at']),3) if previous and previous.get('at') else None
            self.record('exit_trigger',order,'Current ASK reached the protective exit trigger',threshold=threshold,reference='ask',previous_ask=prior_ask,observation_gap_seconds=gap)
            print(json.dumps(dict(event='demo_exit_trigger',threshold=threshold,bid=bid,ask=ask,side=order['side'],quote_age=now-q['at'],entry_price=order['price'],previous_ask=prior_ask,observation_gap_seconds=gap,source=q.get('source'),clock=q.get('clock'),seq=q.get('seq'))),flush=True)
            triggered=True
        return triggered

    def stream(self):
        desired=set(self.quotes)
        if not desired:return
        if self.socket is None:
            self.close_stream()
            from websockets.sync.client import connect
            self.socket=connect(WS,additional_headers=self.exchange.signer.headers('GET','/trade-api/ws/v2'),
                max_size=262144,max_queue=8,open_timeout=8,close_timeout=2,ping_interval=10,ping_timeout=10,compression=None)
            self.socket.send(json.dumps(dict(id=1,cmd='subscribe',params=dict(channels=['orderbook_delta'],market_tickers=sorted(desired),update_interval_ms=0))))
            self.socket.send(json.dumps(dict(id=2,cmd='subscribe',params=dict(channels=['fill','user_orders']))))
            self.subscription=desired;self.sequence={};self.recovered=False
        elif desired!=self.subscription and self.book_sid is not None:
            # Add/remove markets on the existing sequence instead of repeatedly
            # disconnecting held positions whenever discovery finds a market.
            for action,markets in [('add_markets',desired-self.subscription),('delete_markets',self.subscription-desired)]:
                if markets:
                    self.stream_command+=1
                    self.socket.send(json.dumps(dict(id=self.stream_command,cmd='update_subscription',params=dict(sids=[self.book_sid],market_tickers=sorted(markets),action=action))))
            self.subscription=desired
            self.books.books={t:b for t,b in self.books.books.items() if t in desired}
        for index in range(100):
            try:message=json.loads(self.socket.recv(timeout=.5 if index==0 else 0))
            except TimeoutError:
                # A quiet but sequenced book remains current after a confirmed
                # transport round trip and an empty receive queue. No REST polls.
                now=time.time()
                if self.book_pong is not None and self.book_pong.is_set():
                    for ticker in self.books.books:
                        q=self.quotes.get(ticker)
                        if q and q.get('source')=='orderbook':q['at']=now
                    self.book_pong=None
                if self.book_pong is None and now-self.last_book_ping>=2 and hasattr(self.socket,'ping'):
                    self.book_pong=self.socket.ping();self.last_book_ping=now
                break
            if message.get('type')=='error':raise ExchangeFailure('stream_subscription')
            if message.get('type')=='subscribed':
                if message.get('msg',{}).get('channel')=='orderbook_delta':self.book_sid=message['msg']['sid']
                continue
            if 'seq' in message and 'sid' in message:
                sid=message['sid'];seq=message['seq']
                if sid in self.sequence and seq!=self.sequence[sid]+1:raise ExchangeFailure('stream_gap')
                self.sequence[sid]=seq
            raw=message.get('msg',{})
            if message.get('type') in ('fill','user_orders'):self.last_reconcile=0
            # Verify newly filled exposure before consuming later price changes;
            # otherwise its first stop crossing could arrive while filled=0.
            if message.get('type')=='fill':return
            if message.get('type') in ('orderbook_snapshot','orderbook_delta'):
                ticker=raw.get('market_ticker')
                if ticker not in self.quotes:continue
                self.book_sid=message['sid']
                now=time.time();old=self.quotes[ticker]
                ticker,observed=self.books.apply(message,now)
                self.quotes[ticker]=dict(old,**observed)
                # Yield on the first crossing instead of collapsing a burst of
                # exchange changes into its last (potentially much lower) price.
                if observed['book_ready'] and self.observe_exit_triggers(ticker,now,old):return
    def close_stream(self):
        if self.socket:
            try:self.socket.close()
            except Exception:pass
        self.socket=None;self.subscription=set();self.book_sid=None;self.book_pong=None;self.last_book_ping=0;self.books.clear()
        for q in self.quotes.values():q['at']=0
    def cancel(self,order,reason):
        self.context_market=order['ticker'];self.context_order=order.get('exchange_id') or order['client_id'];self.context_bot=order['bot']
        if not order.get('remaining',0) or not order.get('exchange_id'):return
        self.exchange.cancel(order['exchange_id'],order['ticker']);order['remaining']=0
        order['status']='held' if order['kind']=='entry' and order.get('filled',0) else 'closed'
        self.save_order(order);self.record('cancel',order,reason)
        # Reconcile races/fills before considering any replacement or released cash.
        self.recovered=False;self.last_reconcile=0
    def submit(self,intent):
        self.context_market=intent['ticker'];self.context_order=intent['client_id'];self.context_bot=intent['bot']
        # Durable intent precedes network write. Ambiguous writes are never replayed.
        self.save_order(intent);self.record('order_intent',intent,'Verified '+intent['kind']+' order prepared')
        try:
            result=self.exchange.submit(intent)
            intent.update(exchange_id=result['order_id'],status='resting',remaining=number(result['remaining_count']),filled=number(result['fill_count']))
            self.save_order(intent);self.record('order',intent,'Kalshi Demo accepted maker-only '+intent['kind'])
            print(json.dumps(dict(event='demo_order_accepted',kind=intent['kind'],exchange_index=intent.get('exchange_index'),remaining=intent['remaining'],filled=intent['filled'],price=intent['price'],side=intent['side'])),flush=True)
        except ExchangeFailure as error:
            intent['status']='uncertain' if error.ambiguous else 'rejected';self.save_order(intent)
            self.record('order_uncertain' if error.ambiguous else 'order_rejected',intent,'Exchange confirmation incomplete' if error.ambiguous else 'Exchange rejected order',rejection_code=error.provider_code,rejection_reason=error.reason,http_status=error.status)
            if error.ambiguous:self.blocked.add(intent['ticker'])
            raise
        finally:self.recovered=False;self.last_reconcile=0
    def upgrade_legacy_exits(self):
        legacy=[o for o in self.orders if o['kind']=='entry' and o.get('exit_triggered') and o.get('exit_reference')!='ask']
        if not legacy:return False
        if self.legacy_exit_evidence is None:
            with self.store.pool.connection() as c:
                rows=c.execute("""SELECT progress->'details' AS details FROM research_job
                    WHERE idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
                    AND parameters->>'kind'='exit_trigger' AND progress->'details'->>'client_id'=ANY(%s)
                    ORDER BY created_at DESC LIMIT 5001""",([o['client_id'] for o in legacy],)).fetchall()
            if len(rows)>5000:raise ExchangeFailure('exit_policy_reconciliation_capacity')
            self.legacy_exit_evidence={}
            for row in rows:
                d=row['details'] or {};self.legacy_exit_evidence.setdefault(d.get('client_id'),d)
        from .engine import side_quote
        for order in legacy:
            original=self.legacy_exit_evidence.get(order['client_id']) or {};q=original.get('quote') or {}
            # Reset only a proven old BID-only trigger that never met the new
            # ASK rule. Missing evidence retains its existing protective exit.
            known='bid' in q and 'ask' in q and original.get('threshold') is not None
            original_ask=side_quote(q,order['side'])[1] if known else None
            invalid=known and (not 0<original_ask<100 or original_ask>original['threshold'])
            children=[o for o in self.orders if o.get('parent')==order['client_id']]
            if invalid:
                if any(o['status']=='uncertain' for o in children):self.blocked.add(order['ticker']);continue
                for child in children:
                    if child.get('remaining',0)>0:
                        self.cancel(child,'Replacing an old BID-only exit with the requested ASK policy');return True
                order['exit_triggered']=False;order.pop('exit_ceiling_cents',None);order['exit_rule_started_at']=time.time()
                self.record('exit_policy_updated',order,'Old BID-only trigger cleared; protection now follows current ASK')
            order['exit_reference']='ask';self.save_order(order)
        return False
    def trade(self):
        now=time.time();bots={b['id']:b for b in self.bots}
        if self.recovered and self.upgrade_legacy_exits():return
        exiting={o['ticker'] for o in self.orders if o.get('kind')=='exit' and o.get('status') not in ('closed','rejected')}
        for order in self.orders:
            bot=bots.get(order['bot']);q=self.quotes.get(order['ticker'])
            if order.get('status')=='uncertain':continue
            if self.recovered and order['kind']=='entry' and order.get('remaining',0)>0 and bot and bot['config'].get('maximum_cents') is not None and order.get('entry_pricing')!='cap_v2':
                self.cancel(order,'Replacing the old fixed maximum with a capped calculated bid')
                order['entry_pricing']='cap_v2';self.save_order(order)
                if not order.get('filled',0):
                    key=f"{order['ticker']}/{order['square']}/{order['side']}"
                    memory=self.states.get(order['bot'],{}).get(key)
                    if memory:
                        memory.update(submitted=False,attempt=memory.get('attempt',0)+1)
                        self.store.put('trigger/'+order['bot'],self.states[order['bot']],parameters=dict(revision=bot['revision']))
                return
            if order['kind']=='entry' and order.get('remaining',0)>0:
                explicitly_invalid=(not bot or bot['desired']!='running' or order['revision']!=bot['revision'] or now>=order['close'])
                fresh=q is not None and now-q['at']<=5
                condition_invalid=fresh and bot and (not qualifies(bot['config']['squares'][order['square']],q,order['side'],now,bot['config']['qualification']) or not entry_protection_matches(bot['config'],bot['config']['squares'][order['square']],q,order['side']))
                # A reconnect is not evidence that a resting bid is invalid.
                # Preserve it until fresh data verifies the condition or expiry.
                if explicitly_invalid or condition_invalid:self.cancel(order,'Entry no longer matches verified conditions');return
            if not bot or not q or now-q['at']>5 or now>=q['close'] or order['ticker'] in self.blocked:continue
            config=bot['config']
            if order['kind']=='exit' and order.get('remaining',0)>0:
                parent=next((o for o in self.orders if o.get('client_id')==order.get('parent')),None)
                ceiling=min(order['price'],parent.get('exit_ceiling_cents',99) if parent else 99)
                price=exit_price(q,order['side'],ceiling)
                if price is not None and price<order['price']:
                    if parent:parent['exit_ceiling_cents']=price;self.save_order(parent)
                    self.cancel(order,'Lowering protective maker exit as current ASK falls');return
            if order['kind']!='entry' or order.get('filled',0)<=order.get('sold',0):continue
            threshold=protective_threshold(config,config['squares'][order['square']])
            from .engine import side_quote
            bid,ask=side_quote(q,order['side'])
            if not 0<=bid<ask<=100:continue
            if not order.get('exit_triggered') and threshold is not None and 0<ask<100 and ask<=threshold:
                self.observe_exit_triggers(order['ticker'],now)
            if order.get('exit_triggered'):
                exiting.add(order['ticker'])
                for other in self.orders:
                    if other['ticker']==order['ticker'] and other['kind']=='entry' and other.get('remaining',0)>0:self.cancel(other,'Protective exit blocks new entries');return
                if any(o.get('parent')==order['client_id'] and o['status'] not in ('closed','rejected') for o in self.orders):continue
                price=exit_price(q,order['side'],order.get('exit_ceiling_cents'))
                if price and price>bid:
                    order['exit_ceiling_cents']=price
                    attempt=order.get('exit_attempt',0)+1;order['exit_attempt']=attempt;self.save_order(order)
                    identifier=str(uuid5(NAMESPACE_URL,f"demo-exit/{order['client_id']}/{attempt}"))
                    self.submit(dict(client_id=identifier,kind='exit',parent=order['client_id'],bot=order['bot'],revision=order['revision'],ticker=order['ticker'],side=order['side'],price=price,quantity=order['filled']-order.get('sold',0),close=q['close'],created_at=now,exit_reference='ask',status='intent',remaining=0,filled=0));return
        if not self.recovered or now-self.last_reconcile>35:return
        options=candidates(self.bots,self.quotes,self.states,now,self.blocked|exiting)
        direction={o['ticker']:o['side'] for o in self.orders if o['kind']=='entry' and (o.get('remaining',0)>0 or o.get('filled',0)>o.get('sold',0))}
        for item in options:
            self.context_market=item['ticker'];self.context_order=None;self.context_bot=item['bot']
            if len({o['ticker'] for o in self.orders})>=100 and item['ticker'] not in {o['ticker'] for o in self.orders}:continue
            if len(self.orders)>=490:continue
            if item['ticker'] in direction and direction[item['ticker']]!=item['side']:continue
            bot=bots[item['bot']];config=bot['config'];equity=self.account['equity_cents']
            market=sum((o.get('remaining',0)+max(0,o.get('filled',0)-o.get('sold',0)))*o['price'] for o in self.orders if o['kind']=='entry' and o['ticker']==item['ticker'])
            exposure=sum((o.get('remaining',0)+max(0,o.get('filled',0)-o.get('sold',0)))*o['price'] for o in self.orders if o['kind']=='entry' and o['bot']==item['bot'])
            if config.get('daily_loss_percent') is not None:
                with self.store.pool.connection() as c:
                    pnl=c.execute("""SELECT coalesce(sum((progress->>'realized_cents')::numeric),0) AS pnl FROM research_job
                        WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                        AND parameters->>'bot'=%s AND (progress->>'closed_at')::numeric >= %s""",(item['bot'],int(now//86400)*86400)).fetchone()['pnl']
                if pnl<=-equity*config['daily_loss_percent']/100:continue
            amount=quantity(config,item['price'],equity,self.account['cash_cents'],market,exposure)
            if amount<1:continue
            if self.funding is None:
                from .funding import ShardFunding
                self.funding=ShardFunding(self.store,self.exchange)
            if not self.funding.ensure(self.quotes[item['ticker']].get('exchange_index',0),amount*item['price'],max(amount*item['price'],equity*config['bot_percent']/100-exposure),self.shard_reservations):return
            # Funding requests take time: recheck prices and entry qualification
            # on the next stream tick before preparing any order.
            if time.time()-self.quotes[item['ticker']]['at']>5 or not qualifies(config['squares'][item['square']],self.quotes[item['ticker']],item['side'],time.time(),config['qualification']):return
            memory=self.states[item['bot']][item['key']];memory['submitted']=True
            self.store.put('trigger/'+item['bot'],self.states[item['bot']],parameters=dict(revision=bot['revision']))
            identifier=str(uuid5(NAMESPACE_URL,f"demo-entry/{item['bot']}/{bot['revision']}/{item['key']}/{item['cycle']}/{item['first_at']:.6f}/{memory.get('attempt',0)}"))
            self.submit(dict(client_id=identifier,kind='entry',entry_pricing='cap_v2',condition=config['squares'][item['square']],exit_reference='ask',exchange_index=self.quotes[item['ticker']].get('exchange_index',0),bot=item['bot'],revision=bot['revision'],ticker=item['ticker'],side=item['side'],square=item['square'],cycle=item['cycle'],price=item['price'],quantity=amount,close=self.quotes[item['ticker']]['close'],created_at=now,status='intent',remaining=0,filled=0));return
        for bot in self.bots:
            # Compare state before writing; quiet ticks produce no database writes.
            packed=json.dumps(self.states[bot['id']],sort_keys=True)
            if self.trigger_digest.get(bot['id'])!=packed:
                self.store.put('trigger/'+bot['id'],self.states[bot['id']],parameters=dict(revision=bot['revision']));self.trigger_digest[bot['id']]=packed
    def loop(self):
        next_reconcile=0;next_controls=0;maintenance_at=0;backoff=1;credential_check=0;credential_version=None
        try:
            while not self.stop.is_set():
                now=time.time()
                try:
                    self.context_market=self.context_order=self.context_bot=None
                    self.guard()
                    if now>=credential_check:
                        credential_check=now+30;record=self.store.get('credentials');changed=record['progress'].get('changed_at') if record else None
                        if credential_version is not None and changed!=credential_version:
                            signer=credentials(self.store,os.environ)
                            if signer:self.exchange.signer=signer;self.close_stream();self.recovered=False
                        credential_version=changed
                    self.stage='controls'
                    if now>=next_controls:self.load_bots();self.repair_rejected_entries();next_controls=now+5
                    request=self.store.get('refresh') if now>=next_controls-1 else None
                    if request and request['progress']['requested_at']>self.last_reconcile:self.last_reconcile=0
                    self.stage="discovery"
                    if now-self.last_discovery>=5:self.discover()
                    self.stage="stream";self.stream()
                    self.stage="reconciliation"
                    if not self.recovered or now-self.last_reconcile>=30:self.reconcile()
                    self.stage='trade';self.trade();self.health('ready' if self.recovered else 'reconciling','Demo account verified' if self.recovered else 'Verifying exchange order state')
                    if now>=maintenance_at:
                        from .maintenance import maintenance
                        maintenance(self.store,os.environ,self.stop);maintenance_at=now+300
                    backoff=1
                except ExchangeFailure as error:
                    print(json.dumps(dict(event='demo_exchange_failure',stage=self.stage,code=error.code,ambiguous=error.ambiguous,status=error.status,provider_code=error.provider_code,reason=error.reason)),flush=True)
                    self.recovered=False
                    from .diagnostics import exchange_issue
                    self.issue=exchange_issue(error,self.stage,market=self.context_market,order_id=self.context_order,bot=self.context_bot)
                    self.issue['at']=time.time()
                    self.store.alert('exchange',self.issue['summary']+' '+self.issue['action'],True)
                    self.health('attention',self.issue['summary'])
                    if error.code.startswith('stream') or error.code=='connection':self.close_stream()
                    self.stop.wait(backoff);backoff=min(60,backoff*2)
                except Exception as error:
                    print(json.dumps(dict(event='demo_runtime_failure',stage=self.stage,error_type=type(error).__name__,frames=[dict(function=f.name,line=f.lineno) for f in traceback.extract_tb(error.__traceback__)[-4:]])),flush=True)
                    self.recovered=False;self.close_stream()
                    from .diagnostics import runtime_issue
                    self.issue=runtime_issue(self.stage,market=self.context_market,order_id=self.context_order,bot=self.context_bot)
                    self.issue['at']=time.time()
                    self.store.alert('recovery',self.issue['summary']+' '+self.issue['action'],True)
                    self.health('attention',self.issue['summary'])
                    self.stop.wait(backoff);backoff=min(60,backoff*2)
                self.stop.wait(.5)
        finally:
            self.close_stream();self.health('recovering','Worker restarting; preserve exchange orders for reconciliation')

def run(stop):
    from services.api.db_privileges import audit_database
    url=os.environ['DATABASE_URL']
    if not audit_database(url,'research')['privilege_boundary_ready']:raise RuntimeError('Runtime database is not ready')
    with ConnectionPool(url,min_size=1,max_size=3,kwargs=dict(row_factory=dict_row,connect_timeout=5,options='-c statement_timeout=5000')) as pool:
        store=DemoStore(pool)
        # Session advisory lock is held for the process lifetime; verify the same
        # connection before every write. DB loss aborts before any new order.
        with pool.connection() as lock:
            notice_at=0
            while True:
                acquired=lock.execute('SELECT pg_try_advisory_lock(%s) AS locked',(LOCK,)).fetchone()['locked']
                lock.commit()
                if acquired:break
                if time.time()>=notice_at:
                    latest=store.get('health')
                    bots=store.rows('bot/',100)
                    print(json.dumps(dict(event='demo_lock_wait',health=latest['progress'] if latest else None,
                        running=sum(r['progress'].get('desired')=='running' for r in bots),bots=len(bots))),flush=True)
                    notice_at=time.time()+60
                if stop.wait(5):return
            print(json.dumps(dict(event='demo_worker_ready',environment='demo',max_connections=3,watch_limit=100)),flush=True)
            # Retain legacy results/checkpoints but stop obsolete queued work so
            # collection analysis does not keep yielding to an absent replayer.
            with pool.connection() as c:
                c.execute("""UPDATE research_job SET status='cancelled',finished_at=clock_timestamp(),lease_token=NULL,lease_expires_at=NULL
                    WHERE status IN ('queued','running') AND
                    ((idempotency_key>='paper-replay/' AND idempotency_key<'paper-replay/zzzz')
                    OR (idempotency_key>='paper-live/' AND idempotency_key<'paper-live/zzzz'))""")
            def guard():
                if lock.closed:raise RuntimeError('Trading fence lost')
                result=lock.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=%s) AS owned",(LOCK,)).fetchone()
                lock.commit()
                if not result['owned']:raise RuntimeError('Trading fence lost')
            try:
                next_maintenance=0;connection_notice=False
                while not stop.is_set():
                    signer=credentials(store,os.environ)
                    if signer:break
                    if not connection_notice:
                        print(json.dumps(dict(event='demo_connection_required',trading_active=False)),flush=True);connection_notice=True
                    store.put('health',dict(state='connection_required',message='Connect your Kalshi Demo API key to verify the account',at=time.time()))
                    from .maintenance import maintenance
                    if time.time()>=next_maintenance:
                        maintenance(store,os.environ,stop);next_maintenance=time.time()+300
                    stop.wait(30)
                if stop.is_set():return
                exchange=Exchange(signer,guard=guard)
                try:Worker(store,exchange,stop,guard).loop()
                finally:exchange.close()
            finally:
                if not lock.closed:lock.execute('SELECT pg_advisory_unlock(%s)',(LOCK,));lock.commit()
