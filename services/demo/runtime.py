"""Single fenced Demo worker. Bounded stream, durable intents, verified recovery."""
import json,os,time,signal,threading,hashlib
from datetime import datetime,timezone
from decimal import Decimal
from uuid import uuid5,NAMESPACE_URL
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from .store import DemoStore
from .exchange import Exchange,ExchangeFailure,credentials,WS
from .engine import candidates,quantity,qualifies,exit_price,wire_order

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
            series=raw.get('series_ticker') or ticker.split('-')[0],result=raw.get('result'),status=raw.get('status'))
    except (KeyError,ValueError,TypeError):return None

class Worker:
    def __init__(self,store,exchange,stop,guard):
        self.store,self.exchange,self.stop,self.guard=store,exchange,stop,guard
        self.quotes={};self.states={};self.bots=[];self.orders=[];self.blocked=set();self.account={}
        self.last_reconcile=0;self.last_discovery=0;self.last_health=0;self.last_snapshot=0
        self.socket=None;self.subscription=set();self.sequence={};self.recovered=False;self.series_index=0
        self.cursor={};self.last_discovered={};self.last_account_write=0;self.trigger_digest={};self.order_cache={}
    def health(self,state,message):
        now=time.time()
        if now-self.last_health>=10:
            self.store.put('health',dict(state=state,message=message,at=now,
                watched=len(self.quotes),read_requests=self.exchange.reads,write_requests=self.exchange.writes,
                reconciled_at=self.last_reconcile,blocked_markets=sorted(self.blocked)))
            self.last_health=now
    def load_bots(self):
        self.bots=[]
        for row in self.store.rows('bot/',100):
            key=row['idempotency_key'].split('/')[-1]
            self.bots.append(dict(id=key,config=row['parameters']['config'],revision=row['parameters']['revision'],**row['progress']))
            if key not in self.states:
                prior=self.store.get('trigger/'+key);self.states[key]=prior['progress'] if prior else {}
                self.trigger_digest[key]=json.dumps(self.states[key],sort_keys=True)
        self.orders=self.store.active_orders()
    def save_order(self,order):
        data={k:v for k,v in order.items() if k not in ('status','filled','remaining','fees','exchange_id','closed_at','realized_cents')}
        state={k:v for k,v in order.items() if k in ('status','filled','remaining','fees','exchange_id','closed_at','realized_cents')}
        packed=json.dumps([data,state],sort_keys=True)
        if self.order_cache.get(order['client_id'])!=packed:
            self.store.put('order/'+order['client_id'],state,parameters=data)
            self.order_cache[order['client_id']]=packed
    def record(self,kind,order,message,**detail):
        self.store.event(kind,message,bot=order.get('bot'),ticker=order.get('ticker'),details=dict(client_id=order.get('client_id'),exchange_id=order.get('exchange_id'),side=order.get('side'),price=order.get('price'),quantity=order.get('quantity'),condition=order.get('condition'),quote=self.quotes.get(order.get('ticker')),**detail))
    def reconcile(self):
        """Complete paginated exchange state; gaps never manufacture fills."""
        now=time.time();self.load_bots()
        balance=self.exchange.call('GET','/portfolio/balance')
        positions=list(self.exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
        # Resting orders include manual orders. Recent records resolve lost responses.
        remote=list(self.exchange.pages('/portfolio/orders','orders',status='resting'))
        earliest=min((o['created_at'] for o in self.orders),default=now)
        recent=list(self.exchange.pages('/portfolio/orders','orders',min_ts=int(earliest)-60)) if self.orders else []
        by_client={o.get('client_order_id'):o for o in remote+recent}
        known_ids={o['client_id'] for o in self.orders};blocked={o['ticker'] for o in remote if o.get('client_order_id') not in known_ids}
        for order in self.orders:
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
        with self.store.pool.connection() as c:
            exits=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz' AND parameters->>'kind'='exit' AND progress->>'filled' IS NOT NULL ORDER BY created_at DESC LIMIT 2000").fetchall()
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
            if order['kind']=='entry':order['sold']=sold.get(order['client_id'],0)
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
        if pinned and (self.series_index%5==0 or not series):params=dict(tickers=','.join(sorted(pinned)[:100]),limit=200)
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
                q['at']=self.quotes.get(ticker,{}).get('at',0)
                self.quotes[ticker]=q;self.last_discovered[ticker]=now
        rank=lambda item:(item[0] not in pinned,item[1]['close'],item[0])
        kept=[(t,q) for t,q in self.quotes.items() if t in pinned or q['close']>now]
        self.quotes=dict(sorted(kept,key=rank)[:100]);self.last_discovery=now;self.series_index+=1
    def stream(self):
        desired=set(self.quotes)
        if not desired:return
        if desired!=self.subscription or self.socket is None:
            self.close_stream()
            from websockets.sync.client import connect
            self.socket=connect(WS,additional_headers=self.exchange.signer.headers('GET','/trade-api/ws/v2'),
                max_size=262144,max_queue=8,open_timeout=8,close_timeout=2,ping_interval=10,ping_timeout=10,compression=None)
            self.socket.send(json.dumps(dict(id=1,cmd='subscribe',params=dict(channels=['ticker'],market_tickers=sorted(desired),send_initial_snapshot=True))))
            self.socket.send(json.dumps(dict(id=2,cmd='subscribe',params=dict(channels=['fill','user_orders']))))
            self.subscription=desired;self.sequence={};self.recovered=False
        for index in range(100):
            try:message=json.loads(self.socket.recv(timeout=.5 if index==0 else 0))
            except TimeoutError:break
            if message.get('type')=='error':raise ExchangeFailure('stream_subscription')
            if message.get('type')=='subscribed':continue
            if 'seq' in message and 'sid' in message:
                sid=message['sid'];seq=message['seq']
                if sid in self.sequence and seq!=self.sequence[sid]+1:raise ExchangeFailure('stream_gap')
                self.sequence[sid]=seq
            raw=message.get('msg',{})
            if message.get('type') in ('fill','user_orders'):self.last_reconcile=0
            if message.get('type')=='ticker':
                ticker=raw.get('market_ticker') or raw.get('ticker')
                if ticker not in self.quotes:continue
                old=self.quotes[ticker]
                if 'yes_bid_dollars' not in raw or 'yes_ask_dollars' not in raw:continue
                self.quotes[ticker]=dict(old,bid=cents(raw['yes_bid_dollars']),ask=cents(raw['yes_ask_dollars']),at=time.time())
    def close_stream(self):
        if self.socket:
            try:self.socket.close()
            except Exception:pass
        self.socket=None;self.subscription=set()
        for q in self.quotes.values():q['at']=0
    def cancel(self,order,reason):
        if not order.get('remaining',0) or not order.get('exchange_id'):return
        self.exchange.cancel(order['exchange_id']);order['remaining']=0
        order['status']='held' if order['kind']=='entry' and order.get('filled',0) else 'closed'
        self.save_order(order);self.record('cancel',order,reason)
        # Reconcile races/fills before considering any replacement or released cash.
        self.recovered=False;self.last_reconcile=0
    def submit(self,intent):
        # Durable intent precedes network write. Ambiguous writes are never replayed.
        self.save_order(intent);self.record('order_intent',intent,'Verified '+intent['kind']+' order prepared')
        try:
            result=self.exchange.submit(intent)
            intent.update(exchange_id=result['order_id'],status='resting',remaining=number(result['remaining_count']),filled=number(result['fill_count']))
            self.save_order(intent);self.record('order',intent,'Kalshi Demo accepted maker-only '+intent['kind'])
        except ExchangeFailure as error:
            intent['status']='uncertain' if error.ambiguous else 'rejected';self.save_order(intent)
            self.record('order_uncertain' if error.ambiguous else 'order_rejected',intent,'Exchange confirmation incomplete' if error.ambiguous else 'Exchange rejected order')
            if error.ambiguous:self.blocked.add(intent['ticker'])
            raise
        finally:self.recovered=False;self.last_reconcile=0
    def trade(self):
        now=time.time();bots={b['id']:b for b in self.bots}
        exiting={o['ticker'] for o in self.orders if o.get('kind')=='exit' and o.get('status') not in ('closed','rejected')}
        for order in self.orders:
            bot=bots.get(order['bot']);q=self.quotes.get(order['ticker'])
            if order.get('status')=='uncertain':continue
            if order['kind']=='entry' and order.get('remaining',0)>0:
                valid=bot and q and now-q['at']<=5 and bot['desired']=='running' and order['revision']==bot['revision'] and qualifies(bot['config']['squares'][order['square']],q,order['side'],now,bot['config']['qualification'])
                if not valid:self.cancel(order,'Entry no longer matches fresh conditions');return
            if not bot or not q or now-q['at']>5 or order['ticker'] in self.blocked:continue
            config=bot['config']
            if order['kind']=='exit' and order.get('remaining',0)>0:
                price=exit_price(q,order['side'])
                if price and price!=order['price']:self.cancel(order,'Repricing protective maker exit');return
            if order['kind']!='entry' or order.get('filled',0)<=order.get('sold',0):continue
            threshold=config.get('loss_cents') if config['loss_mode']=='manual' else config['squares'][order['square']].get('loss_cents') if config['loss_mode']=='research' else None
            from .engine import side_quote
            bid,ask=side_quote(q,order['side'])
            if not order.get('exit_triggered') and threshold is not None and bid<=threshold:
                order['exit_triggered']=True;self.save_order(order);self.record('exit_trigger',order,'Protective exit triggered',threshold=threshold)
            if order.get('exit_triggered'):
                exiting.add(order['ticker'])
                for other in self.orders:
                    if other['ticker']==order['ticker'] and other['kind']=='entry' and other.get('remaining',0)>0:self.cancel(other,'Protective exit blocks new entries');return
                if any(o.get('parent')==order['client_id'] and o['status'] not in ('closed','rejected') for o in self.orders):continue
                price=exit_price(q,order['side'])
                if price:
                    attempt=order.get('exit_attempt',0)+1;order['exit_attempt']=attempt;self.save_order(order)
                    identifier=str(uuid5(NAMESPACE_URL,f"demo-exit/{order['client_id']}/{attempt}"))
                    self.submit(dict(client_id=identifier,kind='exit',parent=order['client_id'],bot=order['bot'],revision=order['revision'],ticker=order['ticker'],side=order['side'],price=price,quantity=order['filled']-order.get('sold',0),close=q['close'],created_at=now,status='intent',remaining=0,filled=0));return
        if not self.recovered or now-self.last_reconcile>35:return
        options=candidates(self.bots,self.quotes,self.states,now,self.blocked|exiting)
        direction={o['ticker']:o['side'] for o in self.orders if o['kind']=='entry' and (o.get('remaining',0)>0 or o.get('filled',0)>o.get('sold',0))}
        for item in options:
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
            memory=self.states[item['bot']][item['key']];memory['submitted']=True
            self.store.put('trigger/'+item['bot'],self.states[item['bot']])
            identifier=str(uuid5(NAMESPACE_URL,f"demo-entry/{item['bot']}/{bot['revision']}/{item['key']}/{item['cycle']}"))
            self.submit(dict(client_id=identifier,kind='entry',condition=config['squares'][item['square']],bot=item['bot'],revision=bot['revision'],ticker=item['ticker'],side=item['side'],square=item['square'],cycle=item['cycle'],price=item['price'],quantity=amount,close=self.quotes[item['ticker']]['close'],created_at=now,status='intent',remaining=0,filled=0));return
        for bot in self.bots:
            # Compare state before writing; quiet ticks produce no database writes.
            packed=json.dumps(self.states[bot['id']],sort_keys=True)
            if self.trigger_digest.get(bot['id'])!=packed:
                self.store.put('trigger/'+bot['id'],self.states[bot['id']]);self.trigger_digest[bot['id']]=packed
    def loop(self):
        next_reconcile=0;next_controls=0;maintenance_at=0;backoff=1;credential_check=0;credential_version=None
        try:
            while not self.stop.is_set():
                now=time.time()
                try:
                    self.guard()
                    if now>=credential_check:
                        credential_check=now+30;record=self.store.get('credentials');changed=record['progress'].get('changed_at') if record else None
                        if credential_version is not None and changed!=credential_version:
                            signer=credentials(self.store,os.environ)
                            if signer:self.exchange.signer=signer;self.close_stream();self.recovered=False
                        credential_version=changed
                    if now>=next_controls:self.load_bots();next_controls=now+5
                    request=self.store.get('refresh') if now>=next_controls-1 else None
                    if request and request['progress']['requested_at']>self.last_reconcile:self.last_reconcile=0
                    if now-self.last_discovery>=5:self.discover()
                    self.stream()
                    if not self.recovered or now-self.last_reconcile>=30:self.reconcile()
                    self.trade();self.health('ready' if self.recovered else 'reconciling','Demo account verified' if self.recovered else 'Verifying exchange order state')
                    if now>=maintenance_at:
                        from .maintenance import maintenance
                        maintenance(self.store,os.environ,self.stop);maintenance_at=now+300
                    backoff=1
                except ExchangeFailure as error:
                    self.recovered=False
                    self.store.alert('exchange','Demo exchange '+error.code.replace('_',' ')+'. New entries wait for complete verification.',True)
                    self.health('attention','Exchange verification incomplete')
                    if error.code.startswith('stream') or error.code=='connection':self.close_stream()
                    self.stop.wait(backoff);backoff=min(60,backoff*2)
                except Exception:
                    self.recovered=False;self.close_stream()
                    self.store.alert('recovery','Trading recovery incomplete. Entries are paused until verification succeeds.',True)
                    self.health('attention','Recovery incomplete; saved orders retained')
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
            if not lock.execute('SELECT pg_try_advisory_lock(%s) AS locked',(LOCK,)).fetchone()['locked']:return
            lock.commit()
            def guard():
                if lock.closed:raise RuntimeError('Trading fence lost')
                result=lock.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=%s) AS owned",(LOCK,)).fetchone()
                lock.commit()
                if not result['owned']:raise RuntimeError('Trading fence lost')
            try:
                while not stop.is_set():
                    signer=credentials(store,os.environ)
                    if signer:break
                    store.put('health',dict(state='connection_required',message='Connect your Kalshi Demo API key to verify the account',at=time.time()))
                    from .maintenance import maintenance
                    maintenance(store,os.environ,stop);stop.wait(30)
                if stop.is_set():return
                exchange=Exchange(signer,guard=guard)
                try:Worker(store,exchange,stop,guard).loop()
                finally:exchange.close()
            finally:
                if not lock.closed:lock.execute('SELECT pg_advisory_unlock(%s)',(LOCK,));lock.commit()
