"""One fenced, durable 28-market paper executor hosted by the existing worker."""
import asyncio,json,time,logging
from types import SimpleNamespace
from decimal import Decimal as D
from services.paper_demo.exchange import credentials,ProductionData,Fees
from services.trading.mode import read_mode,write_mode,LOCK as MODE_LOCK
from .core import Engine,StrategyFleet,FeePolicy
from .runner import ForwardRun,ProductionData as PublicData
from .storage import HostedAudit,put
from .state import restore

LOG=logging.getLogger('shadow-host')

class NoCapture:
    def write(self,data):pass
    def flush(self):pass
    def close(self):pass

class HostedRun(ForwardRun):
    def __init__(self,store,guard,stop,signer):
        self.store,self.guard,self.outer_stop=store,guard,stop
        self.audit=HostedAudit(store,guard)
        rows=store.rows('shadow/bot/',100)
        self.profiles=[r['parameters'] for r in rows]
        self.engine=Engine(self.audit,cash='1000',latency_ms=150,seed=7,toxic_fill_probability=.35)
        self.allow_rest_settlement_recovery=True  # Approved fallback for missed WS settlement notifications.
        self.settlement_checks={}
        self.strategy=StrategyFleet(self.engine,self.profiles)
        self.audit.engine,self.audit.fleet=self.engine,self.strategy
        prior=store.get('shadow/checkpoint')
        if prior:restore(self.engine,self.strategy,prior['progress'])
        self.api=PublicData();self.signer=signer
        self.verified_data=ProductionData(signer);self.verified_fees=Fees(self.verified_data)
        self.queue=asyncio.Queue(maxsize=20000);self.done=asyncio.Event()
        self.selected={ticker.split('-')[0]:ticker for ticker,m in self.engine.markets.items() if not m.get('paid')}
        self.raw=NoCapture();self.config={};self.refill_offset=0
        self.args=SimpleNamespace(output=str(self.audit.path))
        self.revisions={p['id']:p['revision'] for p in self.profiles}
        self.fee_slots=asyncio.Semaphore(4);self.fee_locks={}
        self.status={};self.data_versions={};self.health_log_at=0
        self.publish_at=0;self.maintenance_at=time.time()+300
        for p in self.profiles:
            self.strategy.bots[p['series']].enabled=next(r['progress'].get('desired')=='running' for r in rows if r['parameters']['id']==p['id'])
        self.audit.checkpoint()

    async def settlement_observed(self,ticker):
        if ticker in self.engine.settled:return True
        if not self.allow_rest_settlement_recovery:return False
        market=self.engine.markets[ticker];now=time.time()
        if now<market['close'] or now-self.settlement_checks.get(ticker,0)<15:return False
        self.settlement_checks[ticker]=now
        raw=(await self.api.fetch('/markets/'+ticker))['market']
        if raw.get('ticker')!=ticker or raw.get('status') not in ('finalized','settled') or raw.get('result') not in ('yes','no'):
            return False
        await self.put('rest_settlement_confirmed',dict(ticker=ticker,status=raw['status'],result=raw['result']))
        return False  # Only the serialized, audited consumer may release the barrier.

    async def fee_policy(self,market,metadata):
        ticker=market['ticker']
        async with self.fee_locks.setdefault(ticker,asyncio.Lock()):
            async with self.fee_slots:
                # A cold cache is restored before any book/clock input is consumed.
                await asyncio.to_thread(self.verified_fees.load,ticker,market,time.time())
            kind,multiplier=self.verified_fees.schedule(ticker,time.time())
            return FeePolicy(D(str(multiplier)),D(str(multiplier)) if kind=='quadratic_with_maker_fees' else D(0))

    async def refresh_fee(self,ticker):
        try:
            # Fee resolution needs the event/series identifiers already saved in
            # the market checkpoint; another /markets request only adds latency.
            await self.fee_policy(dict(self.engine.markets[ticker],ticker=ticker),{})
            return True
        except Exception as exc:
            code=getattr(exc,'code',type(exc).__name__)
            LOG.warning('SHADOW_FEE_REFRESH_FAILED ticker=%s code=%s status=%s',
                        ticker,code,getattr(exc,'status',None))
            return False

    async def fee_maintenance(self):
        # Independent of the once-per-second UI/control loop. Four bounded
        # verifiers share the data adapter's global request pacing/cooldown.
        while not self.done.is_set():
            now=time.time()
            due=[t for t in set(self.selected.values()) if t in self.engine.markets and
                 t not in self.engine.settled and now-self.verified_fees.cache.get(t,{}).get('at',0)>25]
            if due:await asyncio.gather(*(self.refresh_fee(t) for t in due))
            await asyncio.sleep(1)

    async def clock(self):
        while not self.done.is_set():
            await self.put('clock',{})
            await asyncio.sleep(.05)

    async def put(self,source,payload):
        if source=='market':
            series=payload['market']['ticker'].split('-')[0]
            p=next(p for p in self.profiles if p['series']==series)
            payload['market'].update(bot_revision=p['revision'],strategy_version='convexity-'+str(p['revision']))
        await super().put(source,payload)

    def prepare_fees(self,source,payload,now):
        # Resolve policies in receipt order, inside the same audit transaction as
        # simulated execution. In particular a replacement snapshot must never
        # make a fee-blocked book tradable again.
        blocked=set()
        for ticker in self.engine.books:
            if ticker in self.engine.settled:continue
            try:
                kind,m=self.verified_fees.schedule(ticker,now)
                self.engine.fees[ticker]=FeePolicy(D(str(m)),D(str(m)) if kind=='quadratic_with_maker_fees' else D(0))
            except Exception:
                blocked.add(ticker)
                if self.engine.books[ticker].valid:
                    self.engine.data_gap(ticker,'current fee schedule unverified')
        if source=='kalshi' and payload.get('msg',{}).get('market_ticker') in blocked and payload.get('type') in (
                'orderbook_snapshot','orderbook_delta','trade'):
            # Consume subscription sequence without applying unverified inputs.
            # The invalid book must receive a fresh snapshot after fees recover.
            payload=dict(payload,type='fee_blocked')
        return payload

    async def consume(self):
        last=self.engine.now
        while not self.done.is_set():
            source,payload,received=await self.queue.get()
            now=max(received,last)
            if received<last-.01:source,payload='gap',{'reason':'local clock regressed'}
            last=now;self.audit.begin();recovered=False
            try:
                payload=self.prepare_fees(source,payload,now)
                if source=='rest_settlement_confirmed':
                    if not self.allow_rest_settlement_recovery:raise ValueError('REST settlement recovery disabled')
                    ticker=payload['ticker']
                    if ticker not in self.engine.markets or now<self.engine.markets[ticker]['close'] or payload.get('status') not in ('finalized','settled') or payload.get('result') not in ('yes','no'):
                        raise ValueError('REST settlement confirmation invalid')
                    self.engine.advance(now)
                    if ticker not in self.engine.settled:
                        self.engine.markets[ticker]['settlement_confirmation']='production_rest'
                        self.engine.settled.add(ticker)
                        self.engine.cancel_buys(ticker)
                        self.engine.log('SETTLEMENT_RECOVERED',ticker=ticker,reason='production REST finalized result; WebSocket event missed')
                        recovered=True
                else:self.engine.handle(source,payload,now)
            except ValueError as exc:
                self.reject_input(source,payload,exc)
            except BaseException:
                self.audit.abort();raise
            self.audit.flush()
            if recovered:
                print(json.dumps(dict(event='shadow_settlement_recovered',ticker=ticker,
                                      confirmation='production_rest',real_orders_enabled=False)),flush=True)
            self.queue.task_done()

    async def control(self):
        while not self.done.is_set():
            if self.outer_stop.is_set():self.done.set();return
            self.guard();mode=read_mode(self.store.pool).get('mode','demo')
            rows=self.store.rows('shadow/bot/',100)
            for row in rows:
                p=row['parameters'];bot=self.strategy.bots[p['series']]
                enabled=row['progress'].get('desired')=='running' and mode=='demo'
                if not enabled and bot.enabled:
                    for ticker in self.engine.markets:
                        if ticker.startswith(p['series']+'-'):self.engine.cancel_buys(ticker)
                bot.enabled=enabled
                if self.revisions.get(p['id']) != p['revision']:
                    bot.contracts=D(p['contracts'])
                    for ticker in self.engine.markets:
                        if ticker.startswith(p['series']+'-') and ticker not in self.engine.settled:
                            self.strategy.halted.add(ticker);self.engine.cancel_buys(ticker)
                    self.revisions[p['id']]=p['revision']
                self.profiles=[p if old['id']==p['id'] else old for old in self.profiles]
            with self.store.pool.connection() as c:
                commands=c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key>='demo/shadow/command/' AND idempotency_key<'demo/shadow/command/zzzz' AND progress->>'done' IS DISTINCT FROM 'true' ORDER BY created_at LIMIT 100").fetchall()
            for row in commands:
                command=row['parameters']
                self.audit.command_key=row['idempotency_key']
                self.engine.refill(D(command['amount_cents'])/100)
                self.audit.command_key=None
            now=time.time()
            active=[t for t in self.selected.values() if t in self.engine.markets and self.engine.markets[t]['close']>now]
            books=[self.engine.books[t] for t in active if self.engine.books[t].valid]
            fees_ready=0
            for ticker in active:
                try:self.verified_fees.schedule(ticker,now);fees_ready+=1
                except Exception:pass
            state='ready' if books and fees_ready==len(active) and self.engine.spot.ready(now) else 'waiting'
            if time.monotonic()>=self.health_log_at:
                self.health_log_at=time.monotonic()+30
                print(json.dumps(dict(event='shadow_feed_health',state=state,active_markets=len(active),
                    valid_books=len(books),verified_fees=fees_ready,selected_markets=len(self.selected),
                    awaiting_settlement=sum(1 for t in self.selected.values() if t in self.engine.markets and
                        self.engine.markets[t]['close']<=now and t not in self.engine.settled),
                    spot_ready=self.engine.spot.ready(now),input_backlog=self.queue.qsize(),
                    real_orders_enabled=False)),flush=True)
            if time.monotonic()>=self.publish_at:
                self.publish_at=time.monotonic()+5
                self.store.put('health',dict(state=state,message='Production shadow feed verified · virtual funds only' if state=='ready' else 'Waiting for active markets and verified production feeds',at=time.time(),features=['shadow_convexity_v1'],real_orders_enabled=False))
                self.store.put('shadow/status',dict(at=time.time(),selected=self.selected,
                    equity=str(self.engine.wallet.cash+sum((l.quantity*((self.engine.books[l.ticker].bid(l.side) or D(0)) if self.engine.books[l.ticker].valid else l.price) for l in self.engine.wallet.lots),D(0))),
                    virtual_cash=str(self.engine.wallet.cash),available_cash=str(self.engine.available()),
                    open_contracts=str(sum((l.quantity for l in self.engine.wallet.lots),D(0))),
                    market_states={t:dict(close=m['close'],paid=bool(m.get('paid')),data_valid=self.engine.wallet.stat(t).valid,
                        book_valid=self.engine.books[t].valid) for t,m in self.engine.markets.items()},
                    orders=[dict(id=o.id,ticker=o.ticker,side=o.side,action=o.action,quantity=str(o.remaining),price=str(o.price),
                        status=o.status,maker=o.maker) for o in self.engine.orders.values() if o.status in ('resting','pending')],
                    positions=[dict(ticker=l.ticker,side=l.side,quantity=str(l.quantity),is_armed=l.is_armed,phase_origin=l.phase_origin)
                               for l in self.engine.wallet.lots]))
            # Reports/audit are durable in PostgreSQL. Keep only unsettled cycle
            # execution state in the hot checkpoint; never rewrite years of history.
            active=set(self.selected.values())
            pending_ids={item[3] for item in self.engine.pending}
            retired=[t for t,m in self.engine.markets.items() if m.get('paid') and t not in active and
                     not any(o.ticker==t and o.id in pending_ids for o in self.engine.orders.values())]
            for ticker in retired:
                self.engine.markets.pop(ticker,None);self.engine.books.pop(ticker,None)
                self.engine.fees.pop(ticker,None);self.engine.wallet.stats.pop(ticker,None)
                self.engine.closed_reports.discard(ticker);self.engine.settled.discard(ticker)
                self.strategy.halted.discard(ticker)
                self.engine.orders={k:o for k,o in self.engine.orders.items() if o.ticker!=ticker}
                for bot in self.strategy.bots.values():
                    bot.phases.pop(ticker,None);bot.emergency.pop(ticker,None);bot.last_exit.pop(ticker,None)
                    bot.entered={k for k in bot.entered if k[0]!=ticker};bot.locked={k for k in bot.locked if k[0]!=ticker}
            if retired:self.audit.checkpoint()
            if time.time()>=self.maintenance_at:
                from services.demo.maintenance import maintenance
                import os
                self.maintenance_at=time.time()+300
                await asyncio.to_thread(maintenance,self.store,os.environ,self.outer_stop)
            if mode=='draining_demo' and not self.engine.wallet.lots and not any(o.status in ('pending','resting') for o in self.engine.orders.values()):
                with self.store.pool.connection() as c:
                    c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
                    current=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode'").fetchone()
                    if current and current['progress'].get('mode')=='draining_demo':
                        write_mode(c,dict(current['progress'],mode='live',demo_drained_at=time.time()))
                self.done.set();return
            await asyncio.sleep(1)

    async def run(self):
        # No restored book input may run against an empty fee cache.
        restored=[t for t in set(self.selected.values()) if t in self.engine.markets and t not in self.engine.settled]
        if restored:
            results=await asyncio.gather(*(self.refresh_fee(t) for t in restored))
            print(json.dumps(dict(event='shadow_fee_warmup',markets=len(restored),verified=sum(results),
                                  real_orders_enabled=False)),flush=True)
        # Called from the trading thread; the process signal handler owns stop.
        workers=[asyncio.create_task(c) for c in (self.discover(),self.kalshi(),self.spot(),
                                                  self.clock(),self.consume(),self.control(),self.fee_maintenance())]
        waiter=asyncio.create_task(self.done.wait())
        clean_stop=False
        try:
            completed,_=await asyncio.wait([*workers,waiter],return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                if task is not waiter:task.result()
            clean_stop=self.done.is_set()
        finally:
            self.done.set()
            for task in workers+[waiter]:task.cancel()
            await asyncio.gather(*workers,waiter,return_exceptions=True)
            # A failed commit must not be followed by an un-audited checkpoint
            # of mutated memory (particularly a refill awaiting its done marker).
            if clean_stop:self.audit.checkpoint()
            self.verified_data.close();self.audit.close()


def run(stop,store,guard,env):
    maintenance_at=0
    while not stop.is_set():
        guard()
        signer=credentials(store,env)
        if signer:
            asyncio.run(HostedRun(store,guard,stop,signer).run());return
        store.put('health',dict(state='connection_required',message='28 shadow bots ready. Connect a production Read key for market data; no real orders are enabled.',at=time.time(),features=['shadow_convexity_v1'],real_orders_enabled=False))
        print(json.dumps(dict(event='shadow_connection_required',bots=28,real_orders_enabled=False)),flush=True)
        if time.time()>=maintenance_at:
            from services.demo.maintenance import maintenance
            maintenance(store,env,stop);maintenance_at=time.time()+300
        stop.wait(30)
