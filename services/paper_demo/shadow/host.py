"""One fenced, durable 28-market paper executor hosted by the existing worker."""
import asyncio,json,time,logging
from types import SimpleNamespace
from decimal import Decimal as D
from services.paper_demo.exchange import credentials,ProductionData,Fees
from services.paper_demo.read_budget import PRODUCTION_READS
from services.trading.mode import read_mode,write_mode,LOCK as MODE_LOCK
from .core import Engine,StrategyFleet,FeePolicy
from .runner import ForwardRun,ProductionData as PublicData
from .storage import HostedAudit,put
from .state import restore
from .accounting import snapshot as money_snapshot
from .folders import initialize_folders
from .experiments import ExperimentSuite
from .set_discovery import discover_sets
from .weather import initialize_weather,discover_weather
from .performance import record_balances
from .bot_performance import record_bot_balances
from .sports import initialize_sports,discover_sports
from .scope import initialize_scope,initialize_restored_favorites
from .sequential_comparison import initialize_comparison,BOT_LIMIT
from .hourly import discover_hourly

LOG=logging.getLogger('shadow-host')

class NoCapture:
    def write(self,data):pass
    def flush(self):pass
    def close(self):pass

class HostedRun(ForwardRun):
    def __init__(self,store,guard,stop,signer):
        self.store,self.guard,self.outer_stop=store,guard,stop
        self.audit=HostedAudit(store,guard)
        initialize_folders(store,guard)
        initialize_weather(store,guard)
        initialize_sports(store,guard)
        initialize_scope(store,guard)
        initialize_restored_favorites(store,guard)
        initialize_comparison(store,guard)
        all_rows=store.rows('shadow/bot/',BOT_LIMIT)
        rows=[r for r in all_rows if r['parameters'].get('strategy','convexity')=='convexity']
        self.profiles=[r['parameters'] for r in rows]
        self.engine=Engine(self.audit,cash='1000',latency_ms=150,seed=7,toxic_fill_probability=.35)
        self.allow_rest_settlement_recovery=True  # Approved fallback for missed WS settlement notifications.
        self.settlement_checks={}
        self.strategy=StrategyFleet(self.engine,self.profiles)
        self.audit.engine,self.audit.fleet=self.engine,self.strategy
        prior=store.get('shadow/checkpoint')
        self.prior_halts=set()
        if prior:
            self.prior_halts={t for b in prior['progress'].get('fleet',{}).values() for t in b.get('halted',[])}
        if prior:restore(self.engine,self.strategy,prior['progress'])
        self.api=PublicData(signer);self.signer=signer
        self.verified_data=ProductionData(signer);self.verified_fees=Fees(self.verified_data)
        self.queue=asyncio.Queue(maxsize=20000);self.done=asyncio.Event()
        self.selected={ticker.split('-')[0]:ticker for ticker,m in self.engine.markets.items() if not m.get('paid')}
        self.raw=NoCapture();self.config={};self.refill_offset=0
        self.args=SimpleNamespace(output=str(self.audit.path))
        self.revisions={p['id']:p['revision'] for p in self.profiles}
        self.fee_slots=asyncio.Semaphore(4);self.fee_locks={}
        self.status={};self.data_versions={};self.health_log_at=0
        self.suspend_idle_feeds=True
        self.experiments=ExperimentSuite(self,all_rows,prior['progress'].get('experiments') if prior else None)
        self.experiments.share_external_markets()
        self.experiments.share_legacy_markets()
        self.audit.experiments=self.experiments
        self.experiments.extra.update({t:t for t in self.experiments.feed_markets()})
        self.experiments.extra.update({t:t for t,m in self.experiments.portfolios['complete_set'][0].markets.items() if not m.get('paid')})
        # Surface backup/archive failures soon after recovery, then use the
        # normal five-minute cadence without adding Kalshi REST requests.
        self.publish_at=0;self.maintenance_at=time.time()+60
        for p in self.profiles:
            self.strategy.bots[p['series']].enabled=next(r['progress'].get('desired')=='running' for r in rows if r['parameters']['id']==p['id'])
        # Honor the migration immediately, including restored resting entries.
        for order in self.engine.orders.values():
            owner=self.strategy.owner(order.ticker)
            if owner and not owner.enabled and order.maker:self.engine.cancel(order.id)
        self.audit.checkpoint()

    def spot_required(self):
        return (any(b.enabled for b in self.strategy.bots.values()) or bool(self.engine.wallet.lots)
            or any(o.status in ('pending','resting') for o in self.engine.orders.values()))

    def subscription_books(self):
        books=dict(self.engine.books)
        if hasattr(self,'experiments'):
            for e,f,_ in self.experiments.portfolios.values():
                if getattr(self,'suspend_idle_feeds',False) is True and self.experiments.idle_feed(e,f):continue
                for ticker,book in e.books.items():
                    # A healthy copy must not hide another portfolio's need for
                    # a replacement snapshot on the shared subscription.
                    if ticker not in books or not book.valid:books[ticker]=book
        return books

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

    def resnapshot_allowed(self,ticker):
        try:self.verified_fees.schedule(ticker,time.time());return True
        except Exception:return False

    async def market_metadata(self,market,series):
        # Fees.load already verifies series metadata; do not request it twice.
        fee=await self.fee_policy(market,{})
        kind,m=self.verified_fees.schedule(market['ticker'],time.time())
        return dict(fee_type=kind,fee_multiplier=m),fee

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
            engines=[self.engine]+([v[0] for v in self.experiments.portfolios.values()] if hasattr(self,'experiments') else [])
            await self.fee_policy(dict(next(e.markets[ticker] for e in engines if ticker in e.markets),ticker=ticker),{})
            return True
        except Exception as exc:
            await self.metadata_unavailable('fee_refresh',exc,ticker=ticker,series=ticker.split('-')[0])
            return False

    async def fee_maintenance(self):
        # Independent of the once-per-second UI/control loop. Four bounded
        # verifiers share the data adapter's global request pacing/cooldown.
        while not self.done.is_set():
            remaining=PRODUCTION_READS.remaining()
            if remaining:
                await asyncio.sleep(min(5,remaining));continue
            now=time.time()
            due=[t for t in set(self.selected.values())|set(getattr(getattr(self,'experiments',None),'extra',{})) if t in self.subscription_books() and
                 t not in self.engine.settled and now-self.verified_fees.cache.get(t,{}).get('at',0)>25]
            if due:await asyncio.gather(*(self.refresh_fee(t) for t in due))
            await asyncio.sleep(1)

    async def clock(self):
        due=time.monotonic()
        while not self.done.is_set():
            self.loop_lag_max=max(getattr(self,'loop_lag_max',0),max(0,time.monotonic()-due))
            await self.put('clock',{})
            due=time.monotonic()+.1
            await asyncio.sleep(.1)

    async def put(self,source,payload):
        if not hasattr(self,'input_counts'):self.input_counts={}
        kind=source+':'+str(payload.get('type','')) if source=='kalshi' else source
        self.input_counts[kind]=self.input_counts.get(kind,0)+1
        if (source=='kalshi' and payload.get('type')=='market_lifecycle_v2'
                and payload.get('seq') is None):
            # Lifecycle is an exchange-wide stream. Ignore unsequenced notices
            # for markets no portfolio owns or watches before they enter the
            # durable trading queue. Sequenced frames always remain intact.
            ticker=payload.get('msg',{}).get('market_ticker')
            engines=[self.engine]+([v[0] for v in self.experiments.portfolios.values()] if getattr(self,'experiments',None) else [])
            if isinstance(ticker,str) and ticker and not any(ticker in e.markets for e in engines):
                self.lifecycle_dropped=getattr(self,'lifecycle_dropped',0)+1
                now=time.monotonic()
                if now>=getattr(self,'lifecycle_drop_log_at',0):
                    self.lifecycle_drop_log_at=now+30
                    print(json.dumps(dict(event='shadow_transport_filter',unrelated_lifecycle_dropped=self.lifecycle_dropped,
                        real_orders_enabled=False)),flush=True)
                return
        if source=='kalshi' and payload.get('type')=='orderbook_snapshot' and not getattr(self,'snapshot_schema_logged',False):
            self.snapshot_schema_logged=True;msg=payload.get('msg',{})
            print(json.dumps(dict(event='shadow_book_schema',yes_fp_levels=len(msg.get('yes_dollars_fp',[])),
                no_fp_levels=len(msg.get('no_dollars_fp',[])),has_yes_dollars='yes_dollars' in msg,
                has_no_dollars='no_dollars' in msg,has_legacy_yes='yes' in msg)),flush=True)
        if source=='market':
            series=payload['market']['ticker'].split('-')[0]
            p=next(p for p in self.profiles if p['series']==series)
            payload['market'].update(bot_revision=p['revision'],strategy_version='convexity-recovery-v2-'+str(p['revision']),
                partial_profit_price='.40')
        await super().put(source,payload)

    def prepare_fees(self,source,payload,now):
        # Resolve policies in receipt order, inside the same audit transaction as
        # simulated execution. In particular a replacement snapshot must never
        # make a fee-blocked book tradable again.
        blocked=set()
        targets={self.engine.orders[item[3]].ticker for item in self.engine.pending if item[0]<=now}
        if source in ('clock','refill'):targets.update(self.engine.books)
        elif source=='kalshi':targets.add(payload.get('msg',{}).get('market_ticker'))
        for ticker in targets:
            if ticker not in self.engine.books:continue
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
            if payload.get('type')=='orderbook_snapshot':
                self.engine.books[payload['msg']['market_ticker']].sid=payload.get('sid')
            payload=dict(payload,type='fee_blocked')
        return payload

    def pipeline_sample(self,count,simulation_ms,commit_ms,lag):
        if not hasattr(self,'pipeline_totals'):self.pipeline_totals=dict(inputs=0,batches=0,simulation_ms=0.,commit_ms=0.,max_queue_lag_seconds=0.)
        totals=self.pipeline_totals
        totals['inputs']+=count;totals['batches']+=1
        totals['simulation_ms']+=simulation_ms;totals['commit_ms']+=commit_ms
        totals['max_queue_lag_seconds']=max(totals['max_queue_lag_seconds'],lag)
        now=time.monotonic()
        if now<getattr(self,'pipeline_log_at',0):return
        self.pipeline_log_at=now+30
        print(json.dumps(dict(event='shadow_pipeline_cost',**totals,backlog=self.queue.qsize(),
            event_loop_lag_max_seconds=getattr(self,'loop_lag_max',0),
            last_snapshot_ms=getattr(self.audit,'snapshot_ms',0) if isinstance(self.audit,HostedAudit) else None,
            last_database_ms=getattr(self.audit,'write_ms',0) if isinstance(self.audit,HostedAudit) else None,
            last_control_ms=getattr(self,'last_control_ms',None),
            input_types=getattr(self,'input_counts',{}),real_orders_enabled=False)),flush=True)
        self.pipeline_totals=dict(inputs=0,batches=0,simulation_ms=0.,commit_ms=0.,max_queue_lag_seconds=0.)
        self.input_counts={};self.loop_lag_max=0

    def state_mutex(self):
        if not hasattr(self,'_state_mutex'):self._state_mutex=asyncio.Lock()
        return self._state_mutex

    async def flush_audit(self):
        if isinstance(self.audit,HostedAudit):await self.audit.flush_async()
        else:self.audit.flush()

    async def consume(self):
        last=self.engine.now
        while not self.done.is_set():
            item=await self.queue.get()
            async with self.state_mutex():
                self.audit.begin();completed=0;recovered=[];started=time.monotonic();max_lag=0.
                try:
                    while True:
                        source,payload,received=item
                        max_lag=max(max_lag,max(0,time.time()-received))
                        now=max(received,last)
                        if received<last-.01:source,payload='gap',{'reason':'local clock regressed'}
                        last=now
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
                                    self.engine.markets[ticker]['yes_payout_confirmed']='1' if payload['result']=='yes' else '0'
                                    self.engine.settled.add(ticker)
                                    self.engine.cancel_buys(ticker)
                                    self.engine.log('SETTLEMENT_RECOVERED',ticker=ticker,reason='production REST finalized result; WebSocket event missed')
                                    recovered.append(ticker)
                            elif source not in ('set_markets','weather_market','sports_market','hourly_market','sports_status','experiment_settlement'):
                                try:self.engine.handle(source,payload,now)
                                except ValueError as exc:self.reject_input(source,payload,exc)
                            if hasattr(self,'experiments'):self.experiments.handle(source,payload,now)
                        except ValueError as exc:
                            self.reject_input(source,payload,exc)
                        completed+=1
                        # Preserve every event and its cash value, but avoid a DB
                        # round trip/checkpoint for each partial fill in a burst.
                        if self.done.is_set() or self.queue.empty() or completed>=128 or time.monotonic()-started>=.020:
                            break
                        item=self.queue.get_nowait()
                    simulated=time.monotonic()
                    await self.flush_audit()
                    committed=time.monotonic()
                    self.pipeline_sample(completed,(simulated-started)*1000,(committed-simulated)*1000,max_lag)
                    if hasattr(self,'experiments'):
                        self.experiments.monitoring.observe(time.time(),self.queue.qsize(),max_lag,
                            (time.monotonic()-started)*1000/max(1,completed),PRODUCTION_READS.remaining())
                except BaseException:
                    self.audit.abort();raise
                for ticker in recovered:
                    print(json.dumps(dict(event='shadow_settlement_recovered',ticker=ticker,
                                          confirmation='production_rest',real_orders_enabled=False)),flush=True)
                for _ in range(completed):self.queue.task_done()
            # queue.get() doesn't yield while a burst is buffered. Socket
            # readers, pongs and controls still run between committed batches.
            await asyncio.sleep(0)

    def pending_commands(self):
        with self.store.pool.connection() as c:
            return c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key>='demo/shadow/command/' AND idempotency_key<'demo/shadow/command/zzzz' AND progress->>'done' IS DISTINCT FROM 'true' ORDER BY created_at LIMIT 100").fetchall()

    async def control(self):
        while not self.done.is_set():
            if self.outer_stop.is_set():self.done.set();return
            # Read-only configuration fetches may overlap the execution commit.
            # Command consumption remains inside the state lock to prevent a
            # prefetched refill from being applied twice across that commit.
            mode_row,all_rows=await asyncio.gather(
                self.audit.durable_io(read_mode,self.store.pool),
                self.audit.durable_io(self.store.rows,'shadow/bot/',BOT_LIMIT))
            mode=mode_row.get('mode','demo')
            async with self.state_mutex():
                control_started=time.monotonic()
                await self.audit.durable_io(self.guard)
                self.experiments.control(all_rows,mode)
                self.experiments.maintain()
                rows=[r for r in all_rows if r['parameters'].get('strategy','convexity')=='convexity']
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
                commands=await self.audit.durable_io(self.pending_commands)
                for row in commands:
                    command=row['parameters']
                    self.audit.command_key=row['idempotency_key']
                    if command.get('action')=='reset':
                        self.reset_folder(command['folder_id'])
                    else:self.engine.refill(D(command['amount_cents'])/100)
                    self.audit.command_key=None
                now=time.time()
                active=[t for t in self.selected.values() if t in self.engine.markets and self.engine.markets[t]['close']>now]
                books=[self.engine.books[t] for t in active if self.engine.books[t].valid]
                fees_ready=0
                for ticker in active:
                    try:self.verified_fees.schedule(ticker,now);fees_ready+=1
                    except Exception:pass
                legacy_needed=self.spot_required()
                strategy_books=sum(e.book_fresh(t) for e,f,ps in self.experiments.portfolios.values()
                    for t,m in e.markets.items() if m['close']>now and (f.owner(t) and f.owner(t).enabled or any(l.ticker==t for l in e.wallet.lots)))
                state='ready' if (books and fees_ready==len(active) and self.engine.spot.ready(now) if legacy_needed else strategy_books>0) else 'waiting'
                if time.monotonic()>=self.health_log_at:
                    self.health_log_at=time.monotonic()+30
                    print(json.dumps(dict(event='paper_monitoring_capacity',**self.experiments.monitoring_snapshot(now),real_orders_enabled=False)),flush=True)
                    print(json.dumps(dict(event='paper_strategy_health',portfolios={folder:dict(running_bots=sum(b.enabled for b in fleet.bots.values()),virtual_cash=str(e.wallet.cash),weather_markets=sum(bool(m.get('weather_category')) and not m.get('paid',False) for m in e.markets.values()),sports_markets=sum(bool(m.get('sports')) and not m.get('paid',False) for m in e.markets.values()),hourly_markets=sum(bool(m.get('hourly_price')) and not m.get('paid',False) for m in e.markets.values()),open_contracts=str(sum((l.quantity for l in e.wallet.lots),D(0)))) for folder,(e,fleet,ps) in self.experiments.portfolios.items()},real_orders_enabled=False)),flush=True)
                    print(json.dumps(dict(event='shadow_feed_health',state=state,active_markets=len(active),
                        valid_books=len(books),verified_fees=fees_ready,selected_markets=len(self.selected),
                    legacy_spot_required=legacy_needed,active_strategy_books=strategy_books,
                        mode=mode,running_bots=sum(b.enabled for b in self.strategy.bots.values()),
                        two_sided_books=sum(self.engine.books[t].bid('yes') is not None and self.engine.books[t].bid('no') is not None for t in active),
                        halted_markets=sum(t in self.strategy.halted for t in active),
                        prior_halted_markets=sum(t in self.prior_halts for t in active),
                        spike_cooldown_seconds=max(0,self.engine.safety_until-now),
                        phase_counts={str(phase):sum(b.phases.get(t)==phase for t in active for b in [self.strategy.owner(t)] if b) for phase in (1,2,3)},
                        awaiting_settlement=sum(1 for t in self.selected.values() if t in self.engine.markets and
                            self.engine.markets[t]['close']<=now and t not in self.engine.settled),
                        spot_ready=self.engine.spot.ready(now),input_backlog=self.queue.qsize(),
                        input_rejections=getattr(self,'input_rejections',0),
                        unrelated_lifecycle_dropped=getattr(self,'lifecycle_dropped',0),
                        valid_cycles=sum(self.engine.wallet.stat(t).valid for t in active),
                        resting_orders=sum(o.status=='resting' for o in self.engine.orders.values()),
                        pending_orders=sum(o.status=='pending' for o in self.engine.orders.values()),
                        open_contracts=str(sum((l.quantity for l in self.engine.wallet.lots),D(0))),
                        real_orders_enabled=False)),flush=True)
                if time.monotonic()>=self.publish_at:
                    self.publish_at=time.monotonic()+5
                    money=money_snapshot(self.engine,self.profiles,time.time())
                    portfolio=money['portfolio']
                    orders=money.pop('orders');positions=money.pop('positions')
                    if time.monotonic()>=getattr(self,'accounting_log_at',0):
                        self.accounting_log_at=time.monotonic()+30
                        print(json.dumps(dict(event='shadow_accounting_snapshot',**portfolio,
                                              real_orders_enabled=False)),flush=True)
                    await self.audit.durable_io(self.store.put,'health',dict(state=state,message='Production shadow feed verified · virtual funds only' if state=='ready' else 'Waiting for active markets and verified production feeds',at=time.time(),features=['paper_strategy_folders_v1'],real_orders_enabled=False))
                    experiment_snapshot=self.experiments.snapshot(time.time())
                    if int(now//60)!=getattr(self,'balance_history_minute',None):
                        accounts=dict(convexity=money,**{f:v['accounting'] for f,v in experiment_snapshot.items()})
                        await self.audit.durable_io(record_balances,self.store,accounts,now)
                        await self.audit.durable_io(record_bot_balances,self.store,accounts,experiment_snapshot,now,positions)
                        self.balance_history_minute=int(now//60)
                    await self.audit.durable_io(self.store.put,'shadow/status',dict(at=time.time(),selected=self.selected,
                        equity=portfolio['equity'],accounting=money,
                        virtual_cash=portfolio['cash'],available_cash=portfolio['available_cash'],
                        open_contracts=str(sum((l.quantity for l in self.engine.wallet.lots),D(0))),
                        market_states={t:dict(close=m['close'],paid=bool(m.get('paid')),data_valid=self.engine.wallet.stat(t).valid,
                            book_valid=self.engine.books[t].valid,entries_paused=t in self.strategy.halted) for t,m in self.engine.markets.items()},
                        orders=orders,positions=positions,experiments=experiment_snapshot,monitoring=self.experiments.monitoring_snapshot(now)))
                # Reports/audit are durable in PostgreSQL. Keep only unsettled cycle
                # execution state in the hot checkpoint; never rewrite years of history.
                self.engine.prune_terminal_orders()
                active=set(self.selected.values())
                pending_ids={item[3] for item in self.engine.pending}
                retired=[t for t,m in self.engine.markets.items() if m.get('paid') and t not in active and
                         not any(o.ticker==t and o.id in pending_ids for o in self.engine.orders.values())]
                for ticker in retired:
                    self.engine.markets.pop(ticker,None);self.engine.books.pop(ticker,None)
                    self.verified_fees.cache.pop(ticker,None);self.fee_locks.pop(ticker,None)
                    self.settlement_checks.pop(ticker,None);self.engine.gap_reasons.pop(ticker,None)
                    self.engine.fees.pop(ticker,None);self.engine.wallet.stats.pop(ticker,None)
                    self.engine.closed_reports.discard(ticker);self.engine.settled.discard(ticker)
                    self.strategy.halted.discard(ticker)
                    self.engine.orders={k:o for k,o in self.engine.orders.items() if o.ticker!=ticker}
                    for bot in self.strategy.bots.values():
                        bot.phases.pop(ticker,None);bot.emergency.pop(ticker,None);bot.last_exit.pop(ticker,None)
                        bot.safety_retries={k for k in bot.safety_retries if k[0]!=ticker}
                        bot.entered={k for k in bot.entered if k[0]!=ticker};bot.locked={k for k in bot.locked if k[0]!=ticker}
                if retired:
                    self.rejection_logs={k:v for k,v in getattr(self,'rejection_logs',{}).items() if k[1] not in retired}
                    self.metadata_logs={k:v for k,v in getattr(self,'metadata_logs',{}).items() if k[1] not in retired}
                    await self.audit.checkpoint_async()
                if mode=='draining_demo' and not self.engine.wallet.lots and not any(e.wallet.lots for e,f,p in self.experiments.portfolios.values()) and not any(o.status in ('pending','resting') for o in self.engine.orders.values()):
                    with self.store.pool.connection() as c:
                        c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
                        current=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode'").fetchone()
                        if current and current['progress'].get('mode')=='draining_demo':
                            write_mode(c,dict(current['progress'],mode='live',demo_drained_at=time.time()))
                    self.done.set();return
                self.last_control_ms=(time.monotonic()-control_started)*1000
            if time.time()>=self.maintenance_at:
                from services.demo.maintenance import maintenance
                import os
                self.maintenance_at=time.time()+300
                await self.audit.durable_io(maintenance,self.store,os.environ,self.outer_stop)
            await asyncio.sleep(1)

    def reset_folder(self,folder):
        from uuid import uuid4
        from .storage import entry
        from .core import Wallet
        row=self.store.get('shadow/folder/'+folder)
        if not row:raise ValueError('Unknown bot folder')
        archive=self.audit.snapshot() if folder=='convexity' else json.loads(json.dumps(self.experiments.state()[folder],default=str))
        if folder=='convexity':archive.pop('experiments',None)
        self.audit.extra_writes=[entry('demo/shadow/session/'+folder+'/'+row['progress']['session'],
            dict(folder_id=folder,ended_at=time.time()),archive)]
        state=dict(row['progress'],session=str(uuid4()),reset_at=time.time())
        self.audit.extra_writes.append(entry('demo/shadow/folder/'+folder,row['parameters'],state))
        self.audit.begin()
        if folder=='convexity':
            self.engine.wallet=Wallet(D(1000));self.engine.orders={};self.engine.pending=[]
            self.strategy.halted.update(t for t,m in self.engine.markets.items() if not m.get('paid'))
            self.engine.log('SESSION_RESET',reason='Fresh $1,000 paper session; previous results archived')
        else:self.experiments.reset(folder)
        self.audit.flush()

    async def run(self):
        # No restored book input may run against an empty fee cache.
        restored=[t for t in set(self.selected.values())|set(getattr(getattr(self,'experiments',None),'extra',{})) if t in self.subscription_books() and t not in self.engine.settled]
        if restored:
            results=await asyncio.gather(*(self.refresh_fee(t) for t in restored))
            print(json.dumps(dict(event='shadow_fee_warmup',markets=len(restored),verified=sum(results),
                                  real_orders_enabled=False)),flush=True)
        # Called from the trading thread; the process signal handler owns stop.
        coroutines=[self.discover(),self.kalshi(),self.spot(),self.clock(),self.consume(),self.control(),self.fee_maintenance()]
        if hasattr(self,'experiments'):coroutines.extend([discover_sets(self),discover_weather(self),discover_sports(self),discover_hourly(self)])
        workers=[asyncio.create_task(c) for c in coroutines]
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
        store.put('health',dict(state='connection_required',message='28 shadow bots ready. Connect a production Read key for market data; no real orders are enabled.',at=time.time(),features=['paper_strategy_folders_v1'],real_orders_enabled=False))
        print(json.dumps(dict(event='shadow_connection_required',bots=28,real_orders_enabled=False)),flush=True)
        if time.time()>=maintenance_at:
            from services.demo.maintenance import maintenance
            maintenance(store,env,stop);maintenance_at=time.time()+300
        stop.wait(30)
