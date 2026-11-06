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
        self.fee_refresh_at=0;self.status={};self.data_versions={}
        self.publish_at=0;self.maintenance_at=time.time()+300
        for p in self.profiles:
            self.strategy.bots[p['series']].enabled=next(r['progress'].get('desired')=='running' for r in rows if r['parameters']['id']==p['id'])
        self.audit.checkpoint()

    async def fee_policy(self,market,metadata):
        now=time.time();ticker=market['ticker']
        await asyncio.to_thread(self.verified_fees.load,ticker,market,now)
        kind,multiplier=self.verified_fees.schedule(ticker,now)
        return FeePolicy(D(str(multiplier)),D(str(multiplier)) if kind=='quadratic_with_maker_fees' else D(0))

    async def clock(self):
        while not self.done.is_set():
            await self.put('clock',{})
            await asyncio.sleep(.05)

    async def put(self,source,payload):
        if source=='market':
            series=payload['market']['ticker'].split('-')[0]
            p=next(p for p in self.profiles if p['series']==series)
            payload['market'].update(bot_revision=p['revision'],strategy_version='convexity-'+str(p['revision']))
        # Known scheduled fee changes are resolved at execution time, not merely
        # at discovery; a missing or stale schedule blocks the affected book.
        if source in ('clock','kalshi'):
            now=time.time()
            tickers=([payload.get('msg',{}).get('market_ticker')] if source=='kalshi' else list(self.selected.values()))
            for ticker in tickers:
                if not ticker or ticker not in self.engine.markets or ticker in self.engine.settled:continue
                try:
                    kind,m=self.verified_fees.schedule(ticker,now)
                    self.engine.fees[ticker]=FeePolicy(D(str(m)),D(str(m)) if kind=='quadratic_with_maker_fees' else D(0))
                except Exception:
                    if ticker in self.engine.books and self.engine.books[ticker].valid:
                        self.engine.data_gap(ticker,'current fee schedule unverified')
        await super().put(source,payload)

    async def consume(self):
        last=self.engine.now
        while not self.done.is_set():
            source,payload,received=await self.queue.get()
            now=max(received,last)
            if received<last-.01:source,payload='gap',{'reason':'local clock regressed'}
            last=now;self.audit.begin()
            try:
                self.engine.handle(source,payload,now)
            except ValueError:
                for ticker in list(self.engine.books):
                    if ticker not in self.engine.settled:self.engine.data_gap(ticker,'invalid input')
            except BaseException:
                self.audit.abort();raise
            self.audit.flush();self.queue.task_done()

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
            # One bounded fee refresh at a time, outside the feed consumer.
            now=time.time()
            due=[t for t in self.selected.values() if t in self.engine.markets and
                 now-self.verified_fees.cache.get(t,{}).get('at',0)>25]
            if due and now>=self.fee_refresh_at:
                self.fee_refresh_at=now+.25;ticker=min(due,key=lambda t:self.verified_fees.cache.get(t,{}).get('at',0))
                try:
                    market=await self.api.fetch('/markets/'+ticker)
                    await self.fee_policy(market['market'],{})
                except Exception:LOG.warning('Shadow fee refresh pending for %s',ticker)
            books=[b for t,b in self.engine.books.items() if t not in self.engine.settled and b.valid]
            state='ready' if books and self.engine.spot.ready(time.time()) else 'waiting'
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
        # Called from the trading thread; the process signal handler owns stop.
        workers=[asyncio.create_task(c) for c in (self.discover(),self.kalshi(),self.spot(),
                                                  self.clock(),self.consume(),self.control())]
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
