"""Independent paper portfolios over one read-only feed, durably checkpointed together."""
import json,time
from copy import deepcopy
from decimal import Decimal as D
from dataclasses import asdict
from .core import Engine,StrategyFleet,FeePolicy,Wallet,ZERO
from .state import encode,restore
from .accounting import snapshot
from .sequential import SequentialStrategy,PairModel
from .complete_set import CompleteSetStrategy
from .favorites import FavoritesStrategy
from .market_maker import MarketMaker,MM_FOLDERS
from .microstructure import MarketTape
from .scalper import VolatilityScalper,ScalperEngine,SCALPER_FOLDERS
from .favorite_timing import rows as favorite_timing_rows
from .monitoring import MonitoringBudget,protected,category as market_category
from .discovery_budget import CATEGORY_LIMITS
from .sequential_comparison import SEQUENTIAL_FOLDERS,EXPERIMENT_FOLDERS
from .sequential_adaptive import AdaptiveSequentialStrategy,AdaptivePairModel

class ExperimentAudit:
    def __init__(self,parent,folder):self.parent,self.folder=parent,folder;self.path=parent.path
    def log(self,now,kind,wallet,**fields):
        self.parent.log(now,'EXPERIMENT',wallet,folder_id=self.folder,experiment_kind=kind,**fields)

class ExperimentFleet(StrategyFleet):
    def __init__(self,engine,profiles,model,complete=False):
        self.e=engine;self.halted=set();self.bots={};self.complete=complete
        for p in profiles:
            b=MarketMaker(engine,p) if p.get('strategy')=='market_maker' else VolatilityScalper(engine,p) if p.get('strategy')=='volatility_scalper' else CompleteSetStrategy(engine,p) if complete else FavoritesStrategy(engine,p) if p.get('strategy')=='favorites' else (AdaptiveSequentialStrategy if p.get('variant')=='adaptive' else SequentialStrategy)(engine,p,model)
            b.halted=self.halted;self.bots[p['series']]=b
        engine.fill_callback=self.on_fill;engine.strategy=self
    def on_data_gap(self,ticker,reason):
        owner=self.owner(ticker);callback=getattr(owner,'on_data_gap',None)
        if callback:callback(ticker,reason)
    def owner(self,ticker):
        if self.complete:return next(iter(self.bots.values()),None)
        if self.e.markets.get(ticker,{}).get('market_maker'):
            ident=self.e.markets[ticker]['bot_id'];return next((b for b in self.bots.values() if b.profile['id']==ident),None)
        return super().owner(ticker)
    def step(self,changed_ticker=None):
        if self.complete:
            for b in self.bots.values():b.step(changed_ticker)
        elif isinstance(self.e,ScalperEngine) and changed_ticker is None:
            # Only owners of admitted markets need a clock pass. Empty profiles
            # cannot place or manage an order and need no duplicate book scans.
            owners={id(b):b for t in self.e.markets if (b:=self.owner(t)) is not None}
            for b in owners.values():b.step()
        else:super().step(changed_ticker)

class ExperimentSuite:
    def __init__(self,host,rows,previous=None):
        self.summary=(previous or {}).get('_summary',{})
        self.comparison=(previous or {}).get('_comparison',{})
        self.monitoring=MonitoringBudget();self.tape=MarketTape()
        self.rotation_exclusions={t:min(end,time.time()+60) for t,end in (previous or {}).get('_rotation_exclusions',{}).items()}
        self.host=host;self.rows=rows;self.portfolios={};self.models={};self.extra={};self.scanner_cursor='';self.scanner_state={}
        for folder in EXPERIMENT_FOLDERS:
            ps=[r['parameters'] for r in rows if r['parameters'].get('folder_id')==folder]
            model_data=(previous or {}).get(folder,{}).get('model')
            if model_data is None and folder=='sequential_flexible':model_data=deepcopy((previous or {}).get('sequential',{}).get('model'))
            model=(AdaptivePairModel if folder=='sequential_adaptive' else PairModel)(model_data)
            engine_class=ScalperEngine if folder in (*SCALPER_FOLDERS,*MM_FOLDERS) else Engine
            e=engine_class(ExperimentAudit(host.audit,folder),cash='1000',latency_ms=150,seed=17,toxic_fill_probability=0)
            if isinstance(e,ScalperEngine):e.tape=self.tape
            if getattr(host,'model_worker_latency',False) is True:e.wall_clock=time.time
            f=ExperimentFleet(e,ps,model,folder=='complete_set')
            state=(previous or {}).get(folder)
            if state:
                restore(e,f,state['engine'])
                for series,info in state.get('strategies',{}).items():
                    if series not in f.bots:continue
                    b=f.bots[series]
                    b.attempts=info.get('attempts',{})
                    if hasattr(b,'on_data_gap'):
                        for ticker in b.attempts:b.on_data_gap(ticker,'worker restarted during trial')
                    if hasattr(b,'exit_evidence'):b.exit_evidence.cells=info.get('exit_evidence',{})
                    if isinstance(b,SequentialStrategy):b.trial=info.get('trial',b.trial)
                    if folder=='complete_set':b.groups=info.get('groups',{})
                    if isinstance(b,VolatilityScalper):b.restore_state(info.get('scalper',{}))
            for p in ps:
                r=next(r for r in rows if r['parameters']['id']==p['id']);f.bots[p['series']].enabled=r['progress'].get('desired')=='running'
            self.portfolios[folder]=(e,f,ps);self.models[folder]=model
        self.weather_cursor={};self.weather_pages={};self.sports_cursor=0;self.sports_pages={};self.hourly_cursor=0;self.hourly_pages={}
        self.control(rows)
        if isinstance((previous or {}).get('_maker_discovery'),dict):self.maker_discovery=deepcopy(previous['_maker_discovery'])
    def state(self):
        return dict(_summary=self.summary,_comparison=self.comparison,_rotation_exclusions=self.rotation_exclusions,_maker_discovery=getattr(self,'maker_discovery',None),**{folder:dict(engine=encode(e,f),model=self.models[folder].cells,
            strategies={s:dict(scalper=b.export_state() if isinstance(b,VolatilityScalper) else {},attempts=b.attempts,groups=getattr(b,'groups',{}),exit_evidence=b.exit_evidence.cells if hasattr(b,'exit_evidence') else {},trial=getattr(b,'trial',{})) for s,b in f.bots.items()})
            for folder,(e,f,ps) in self.portfolios.items()})
    def control(self,rows,mode='demo'):
        for folder,(e,f,ps) in self.portfolios.items():
            for p in ps:
                row=next((r for r in rows if r['parameters']['id']==p['id']),None)
                if not row:continue
                b=f.bots[p['series']];enabled=row['progress'].get('desired')=='running' and mode=='demo' and not row['parameters'].get('retired')
                if not enabled and b.enabled:
                    for t in e.markets:
                        if f.owner(t) is b:e.cancel_buys(t)
                b.enabled=enabled;b.contracts=D(row['parameters']['contracts'])
                if isinstance(b,VolatilityScalper):p.update(row['parameters']);b.refresh_config()
    def add_set(self,payload,now):
        if not self.extra_capacity([p['market']['ticker'] for p in payload['markets']],now):return
        e,f,ps=self.portfolios['complete_set'];profile=ps[0]
        for p in payload['markets']:
            market=dict(p['market'],bot_id=profile['id'],bot_name=profile['name'],strategy_version='complete-set-1',bot_revision=profile['revision'])
            if market['ticker'] not in e.markets:e.handle('market',dict(p,market=market),now)
            self.extra[market['ticker']]=market['ticker']
        f.bots[profile['series']].register(payload['event'],[p['market'] for p in payload['markets']])
    def enabled_profiles(self,asset):
        found={}
        for e,f,ps in self.portfolios.values():
            for p in ps:
                if p.get('asset')==asset and f.bots[p['series']].enabled and not p.get('retired'):found.setdefault(p['id'] if asset=='market_maker' else p['series'],p)
        return list(found.values())
    def feed_markets(self):
        return {t:m for e,f,ps in self.portfolios.values() for t,m in e.markets.items()
                if not m.get('entry_parked') and not m.get('paid') and (m.get('weather_category') or m.get('sports') or m.get('hourly_price') or m.get('market_maker'))}
    def share_external_markets(self):
        # A newly added strategy must join already subscribed weather/games;
        # waiting for another discovery would strand it behind filled positions.
        now=time.time()
        for ticker,m in list(self.feed_markets().items()):
            if m['close']<=now:continue
            source=next(e for e,f,ps in self.portfolios.values() if ticker in e.markets)
            for folder in (*SEQUENTIAL_FOLDERS,'favorites',*SCALPER_FOLDERS):
                e,f,ps=self.portfolios[folder]
                if ticker in e.markets or folder in SEQUENTIAL_FOLDERS and m.get('hourly_price'):continue
                p=next((p for p in ps if p['series']==ticker.split('-')[0] and not p.get('retired')),None)
                if not p:continue
                market=dict(m,bot_id=p['id'],bot_name=p['name'],bot_revision=p['revision'],
                            strategy_version=p.get('version',folder+'-1'),discovered_at=now)
                e.add_market(market,source.fees[ticker])
    def share_legacy_markets(self,now=None):
        # Re-enabled 15m bots join the already selected public feed immediately;
        # they must not wait for the next quarter-hour rollover to discover it.
        now=time.time() if now is None else now
        for ticker,m in list(self.host.engine.markets.items()):
            if m.get('paid') or m['close']<=now:continue
            for folder in (*SEQUENTIAL_FOLDERS,'favorites',*SCALPER_FOLDERS):
                e,f,ps=self.portfolios[folder]
                if ticker in e.markets:continue
                p=next((p for p in ps if p['series']==ticker.split('-')[0] and not p.get('retired')),None)
                if not p:continue
                e.add_market(dict(m,bot_id=p['id'],bot_name=p['name'],bot_revision=p['revision'],
                    strategy_version=p.get('version',folder+'-1'),discovered_at=now),self.host.engine.fees[ticker])

    def settlement_markets(self):
        return {t:m for e,_,_ in self.portfolios.values() for t,m in e.markets.items()
                if not m.get('paid') and (m.get('weather_category') or m.get('sports') or m.get('hourly_price') or m.get('market_maker'))}
    def candidate_allowed(self,ticker,now):
        if self.rotation_exclusions.get(ticker,0)>now:return False
        owners=[f.owner(ticker) for e,f,_ in self.portfolios.values() if ticker in e.markets]
        owners=[b for b in owners if b and b.enabled]
        return not owners or not all(b.attempts.get(ticker,{}).get('first') and not (isinstance(b,VolatilityScalper) and b.attempts[ticker].get('recorded')) for b in owners)
    def monitoring_snapshot(self,now):
        limits=self.monitoring.limits(now)
        active={t for t,m in self.feed_markets().items() if m['close']>now}
        # Complete-set feeds have their own portfolio, outside feed_markets().
        active.update(t for e,_,_ in self.portfolios.values() for t,m in e.markets.items() if t in self.extra and m['close']>now and not m.get('entry_parked') and not m.get('paid'))
        care={t for t in active if protected(self,t,now)}
        probes=active-care
        markets={t:m for e,_,_ in self.portfolios.values() for t,m in e.markets.items()}
        legacy={t for t,m in self.host.engine.markets.items() if m['close']>now}
        return dict(limits,position_and_exit_markets=len(care),entry_markets=len(probes),
            subscribed_markets=len(active|legacy),legacy_markets=len(legacy),coalesced_inputs=sum(getattr(e,'coalesced_inputs',0) for e,_,_ in self.portfolios.values()),filtered_quote_updates=sum(getattr(e,'filtered_quote_updates',0) for e,_,_ in self.portfolios.values()),
            categories={c:sum(market_category(markets.get(t,{}))==c for t in probes) for c in ('weather','weather_daily','hourly','sports','complete_set','market_maker')},
            rotated_markets=len(self.rotation_exclusions))
    def search_capacity(self,category,now,slots=1):
        stats=self.monitoring_snapshot(now)
        return (stats['admitting'] and stats['categories'].get(category,0)+slots<=(4 if category=='complete_set' else min(CATEGORY_LIMITS.get(category,stats['per_category']),stats['per_category'])) and
            stats['entry_markets']+slots<=stats['entry_candidates'] and stats['subscribed_markets']+slots<=stats['total'])
    def extra_capacity(self,tickers,now):
        additions=set(tickers)-set(self.extra)
        if not additions:return True
        stats=self.monitoring_snapshot(now)
        return (stats['admitting'] and all(self.candidate_allowed(t,now) for t in additions) and
            stats['subscribed_markets']+len(additions)<=stats['total'] and
            stats['entry_markets']+len(additions)<=stats['entry_candidates'])
    def reclaim_idle_candidate(self,now):
        # Runs on the serialized engine path. Never revoke a live order or lot
        # merely to admit a new game, including pending transport arrivals.
        for t,m in sorted(self.feed_markets().items(),key=lambda item:item[1].get('discovered_at',now)):
            if m['close']<=now or m.get('sports') or now-m.get('discovered_at',now)<30 or protected(self,t,now):continue
            if any(o.ticker==t and o.status in ('pending','resting') for e,_,_ in self.portfolios.values() for o in e.orders.values()):continue
            self.park_candidate(t,m,now)
            return True
        return False
    def park_candidate(self,t,m,now):
        self.rotation_exclusions[t]=min(m['close'],now+60)
        for folder,(e,f,ps) in self.portfolios.items():
            if t not in e.markets or folder=='complete_set':continue
            b=f.owner(t);a=b.attempts.get(t,{}) if b else {}
            if a and not a.get('first') and not a.get('recorded'):
                if isinstance(b,SequentialStrategy):b.finish(t)
                else:a['recorded']=True
            e.markets[t]['entry_parked']=True;e.books[t].valid=False
        self.extra.pop(t,None)
    def rotate_candidates(self,now):
        self.rotation_exclusions={t:end for t,end in self.rotation_exclusions.items() if end>now}
        for t,m in list(self.feed_markets().items()):
            if now-m.get('discovered_at',now)<120 or protected(self,t,now):continue
            if any(o.ticker==t and o.status in ('pending','resting') for e,_,_ in self.portfolios.values() for o in e.orders.values()):continue
            self.park_candidate(t,m,now)
    def prepare(self,e,source,payload,now):
        targets={e.orders[item[3]].ticker for item in e.pending if item[0]<=now}
        if source=='clock':targets.update(e.books)
        elif source=='kalshi':targets.add(payload.get('msg',{}).get('market_ticker'))
        for ticker in targets:
            if ticker not in e.books or ticker in e.settled:continue
            try:
                kind,m=self.host.verified_fees.schedule(ticker,now)
                e.fees[ticker]=FeePolicy(D(str(m)),D(str(m)) if kind=='quadratic_with_maker_fees' else ZERO)
            except Exception:
                if e.books[ticker].valid:e.data_gap(ticker,'current fee schedule unverified')
                if source=='kalshi' and payload.get('msg',{}).get('market_ticker')==ticker:return dict(payload,type='fee_blocked')
        return payload

    @staticmethod
    def flat_portfolio(e):
        return not e.wallet.lots and not any(o.status in ('pending','resting') for o in e.orders.values())
    def coalesce_flat_input(self,e,source,payload,now):
        # Only the two newly introduced experiments use this path. The primary
        # scalper already verified this exact shared subscription frame.
        if source!='kalshi' or payload.get('type') not in ('orderbook_snapshot','orderbook_delta','trade') or not self.flat_portfolio(e):return False
        primary=self.portfolios['volatility_scalper'][0]
        sid,seq=payload.get('sid'),payload.get('seq');ticker=payload.get('msg',{}).get('market_ticker')
        if sid is None or seq is None or primary.sequences.get(sid)!=seq:return False
        if ticker in e.books and (ticker not in primary.books or not primary.book_fresh(ticker)):return False
        e.advance(now)
        e.sequences[sid]=seq;e.book_feed_at=dict(primary.book_feed_at)
        if ticker in e.books:
            e.coalesced_tickers=getattr(e,'coalesced_tickers',set());e.coalesced_tickers.add(ticker)
            # Keep this portfolio's hypothetical consumption, never the primary
            # portfolio's overlay. Real removals invalidate consumed levels.
            live=primary.books[ticker].levels
            for side in ('yes','no'):
                e.books[ticker].used[side]={p:q for p,q in e.books[ticker].used[side].items() if p in live[side]}
            e.fees[ticker]=primary.fees[ticker]
        e.coalesced_inputs=getattr(e,'coalesced_inputs',0)+1
        return True
    def sync_flat_books(self,e,now):
        pending=getattr(e,'coalesced_tickers',set())
        if not pending:return
        primary=self.portfolios['volatility_scalper'][0]
        # No pending order may execute against a later source frame. All books
        # are detached before the clock can submit the first entry.
        if not self.flat_portfolio(e):
            for t in list(pending):e.data_gap(t,'flat-feed exposure changed; fresh snapshot required')
            pending.clear();return
        for t in list(pending):
            if t not in e.books:pending.discard(t);continue
            if t not in primary.books or not primary.book_fresh(t):
                e.data_gap(t,'shared verified book unavailable');pending.discard(t);continue
            book,live=e.books[t],primary.books[t]
            book.levels={side:dict(live.levels[side]) for side in ('yes','no')}
            book.used={side:{p:q for p,q in book.used[side].items() if p in book.levels[side]} for side in ('yes','no')}
            for field in ('seq','sid','valid','at','snapshot_at'):setattr(book,field,getattr(live,field))
            pending.discard(t)
        e.book_feed_at=dict(primary.book_feed_at)

    @staticmethod
    def idle_feed(e,f):
        return (not any(b.enabled for b in f.bots.values()) and not e.wallet.lots
            and not any(o.status in ('pending','resting') for o in e.orders.values()))

    def handle(self,source,payload,now):
        # These portfolios use Kalshi books, not the legacy BTC spot valve.
        if source=='gap' and payload.get('reason')=='spot stream disconnected':return
        if source=='set_markets':self.add_set(payload,now);return
        if source=='sports_status':
            ticker=payload['ticker']
            for folder in (*SEQUENTIAL_FOLDERS,'favorites',*SCALPER_FOLDERS):
                e,f,ps=self.portfolios[folder]
                if ticker in e.markets:
                    self.prepare(e,'clock',{},now)
                    e.advance(now);e.markets[ticker].update(payload['gate']);f.step(ticker)
            return
        if source in ('weather_market','sports_market','hourly_market'):
            if source=='sports_market' and payload['market'].get('sports_live') and self.candidate_allowed(payload['market']['ticker'],now) and not self.extra_capacity([payload['market']['ticker']],now):
                if self.monitoring_snapshot(now)['admitting']:self.reclaim_idle_candidate(now)
            if not self.extra_capacity([payload['market']['ticker']],now):return
            self.extra[payload['market']['ticker']]=payload['market']['ticker']
        if source=='maker_market':
            m=payload['market'];ticker=m['ticker']
            if not self.extra_capacity([ticker],now):return
            self.extra[ticker]=ticker
            for folder in MM_FOLDERS:
                e,f,ps=self.portfolios[folder]
                profile=next((p for p in ps if p['market_category']==m['market_category']),None)
                if not profile:continue
                if ticker in e.markets:
                    e.markets[ticker].update(m,entry_parked=False)
                    e.books[ticker].valid=False
                e.handle('market',dict(payload,market=dict(m,bot_id=profile['id'],bot_name=profile['name'],bot_revision=profile['revision'],strategy_version=profile['version'])),now)
            return
        errors=[]
        resource_paused=not self.monitoring.limits(now)['admitting']
        for folder,(e,f,ps) in self.portfolios.items():
            if getattr(self.host,'suspend_idle_feeds',False) is True:
                idle=self.idle_feed(e,f)
                if not idle and getattr(e,'idle_feed_suspended',False):
                    e.sequences.clear();e.book_feed_at.clear()
                    for ticker in e.books:
                        if ticker not in e.settled:e.data_gap(ticker,'portfolio resumed; fresh snapshot required')
                    e.idle_feed_suspended=False
                if idle and (source=='book_heartbeat' or source=='kalshi' and payload.get('type') in ('orderbook_snapshot','orderbook_delta','trade')):
                    # No trading intent, outstanding orders or exposure needs
                    # this duplicate book. Keep lifecycle/settlement processing.
                    e.idle_feed_suspended=True;continue
            if folder in (*SCALPER_FOLDERS,*MM_FOLDERS):
                # The budget is identical across portfolios on this input.
                # Propagate only transitions instead of rewriting hundreds of
                # inactive profiles for every raw book delta.
                if getattr(f,'_resource_paused',None) is not resource_paused:
                    for bot in f.bots.values():bot.resource_paused=resource_paused
                    f._resource_paused=resource_paused
            if folder in ('scalper_momentum','scalper_dislocation'):
                if source=='clock':
                    pending=getattr(e,'coalesced_tickers',set())
                    due=any((b:=f.owner(t)) and b.enabled and now-b.last_eval.get(t,-1e9)>=b.config['eval_seconds'] for t in pending)
                    if due:self.sync_flat_books(e,now)
                elif self.coalesce_flat_input(e,source,payload,now):continue
                elif source=='kalshi' and payload.get('type') in ('orderbook_snapshot','orderbook_delta','trade'):
                    t=payload.get('msg',{}).get('market_ticker');pending=getattr(e,'coalesced_tickers',set())
                    if t in pending:
                        e.data_gap(t,'shared feed interrupted; fresh snapshot required');pending.discard(t)
            local=payload
            if source in ('market','weather_market','sports_market','hourly_market'):
                if folder not in (*SEQUENTIAL_FOLDERS,'favorites',*SCALPER_FOLDERS) or source=='hourly_market' and folder not in ('favorites',*SCALPER_FOLDERS):continue
                profile=next((p for p in ps if p['series']==payload['market']['ticker'].split('-')[0]),None)
                if not profile or profile.get('retired'):continue
                local=dict(payload,market=dict(payload['market'],bot_id=profile['id'],bot_name=profile['name'],strategy_version=profile.get('version',folder+'-1'),bot_revision=profile['revision']))
                ticker=local['market']['ticker']
                if e.markets.get(ticker,{}).get('entry_parked'):
                    # Readmission is explicit and still needs a replacement full
                    # snapshot. Keep inventory/history and the original bid cap.
                    e.markets[ticker].update(local['market'],entry_parked=False)
                    b=f.owner(ticker);a=b.attempts.get(ticker,{}) if b else {}
                    if a and not a.get('first'):a.update(recorded=False,retry_at=0)
                    e.books[ticker].valid=False

            if source in ('refill','spot','metadata_retry'):continue
            if source in ('rest_settlement_confirmed','experiment_settlement'):
                ticker=payload['ticker']
                if ticker in e.markets:
                    e.advance(now);e.settled.add(ticker)
                    e.markets[ticker]['yes_payout_confirmed']='1' if payload['result']=='yes' else '0'
                    e.handle('settlement',dict(ticker=ticker,yes_payout=e.markets[ticker]['yes_payout_confirmed']),now)
                continue
            if source=='settlement':
                if payload['ticker'] not in e.markets:continue
                e.markets[payload['ticker']]['yes_payout_confirmed']=payload['yes_payout']
            try:
                started=time.thread_time()
                try:
                    e.handle('market' if source in ('weather_market','sports_market','hourly_market') else source,self.prepare(e,source,local,now),now)
                finally:
                    if not hasattr(self,'processing_costs'):self.processing_costs={}
                    cost=self.processing_costs.setdefault(folder,dict(calls=0,cpu_ms=0.))
                    cost['calls']+=1;cost['cpu_ms']+=(time.thread_time()-started)*1000
            except ValueError as exc:
                # Every portfolio must consume the shared subscription sequence,
                # even when another portfolio rejects this market's book.
                ticker=local.get('msg',{}).get('market_ticker') if source=='kalshi' else local.get('ticker')
                if ticker in e.books:e.data_gap(ticker,str(exc))
                errors.append(exc);continue
            # Complete-set markets are not in legacy discovery's settlement gate.
            if source=='kalshi' and payload.get('type')=='market_lifecycle_v2':
                msg=payload.get('msg',{});t=msg.get('market_ticker')
                if t in e.markets and msg.get('event_type')=='settled' and msg.get('result') in ('yes','no'):
                    e.markets[t]['yes_payout_confirmed']='1' if msg['result']=='yes' else '0'
                    e.handle('settlement',dict(ticker=t,yes_payout=e.markets[t]['yes_payout_confirmed']),now)
        if errors:raise errors[0]
    def comparison_snapshot(self,folder,e,f,money,now):
        bots=[b for b in f.bots.values() if isinstance(b,SequentialStrategy)]
        if not bots or not any(b.profile.get('comparison_started_at') for b in bots):return None
        totals={k:sum(float(b.trial.get(k,0)) for b in bots) for k in
            ('attempts','first_fills','completed','net','unmatched_losses','completion_seconds','dollar_hours')}
        active={t:a for b in bots for t,a in b.attempts.items() if b.trial_attempt(a) and not a.get('recorded')}
        realized=totals['net']+sum(float(e.wallet.stat(t).gross-e.wallet.stat(t).realized_fees-D(a['baseline'])) for t,a in active.items())
        positions=[p for p in money['positions'] if p['ticker'] in active]
        unpriced=any(p['value'] is None or p.get('valuation_estimated') for p in positions)
        pnl=None if any(p['value'] is None for p in positions) else realized+sum(float(D(p['value'])-D(p['cost'])) for p in positions)
        draw=self.comparison.setdefault(folder,dict(peak=0.,max_drawdown=0.,coverage_incomplete=False))
        if pnl is None or unpriced:draw['coverage_incomplete']=True
        else:
            draw['peak']=max(draw['peak'],pnl);draw['max_drawdown']=max(draw['max_drawdown'],draw['peak']-pnl)
        return dict(started_at=min(b.trial['started_at'] for b in bots),variant=bots[0].profile.get('variant','baseline'),
            attempts=int(totals['attempts']),first_fills=int(totals['first_fills']),completed=int(totals['completed']),
            completion_rate=totals['completed']/totals['first_fills'] if totals['first_fills'] else None,
            realized_pnl=realized,net_pnl=pnl,unmatched_losses=totals['unmatched_losses'],
            average_completion_seconds=totals['completion_seconds']/totals['completed'] if totals['completed'] else None,
            dollar_hours=totals['dollar_hours'],profit_per_dollar_hour=pnl/totals['dollar_hours'] if pnl is not None and totals['dollar_hours'] else None,
            max_drawdown=draw['max_drawdown'],drawdown_incomplete=draw['coverage_incomplete'],
            open_attempts=len(active),unpriced=unpriced,at=now)
    def data_message(self,e,b,p,now):
        current=[(t,m) for t,m in e.markets.items() if (m.get('bot_id')==p['id'] or t.startswith(p['series']+'-')) and m['close']>now and not m.get('paid') and not m.get('entry_parked')]
        if current and not any(e.book_fresh(t) for t,m in current):
            return 'Active market · waiting for fresh order-book data'
        coverage=getattr(self,'hourly_coverage',{}).get(p['series'])
        if not current and coverage:
            if now-coverage['at']>120:return 'Market scan delayed · last checked more than 2 minutes ago'
            return coverage['reason']
        return getattr(b,'last_reason','Waiting for market data')

    def snapshot(self,now):
        result={}
        for folder,(e,f,ps) in self.portfolios.items():
            money=snapshot(e,ps,now)
            if folder in SCALPER_FOLDERS:
                for order in money['orders']:
                    if order['purpose']=='scalper_maker_profit_exit' and order['action']=='buy':
                        order.update(action='sell',side='no' if order['side']=='yes' else 'yes',price=str(1-D(order['price'])),execution='complementary maker netting')
            bots={}
            for p in ps:
                b=f.bots[p['series']]
                stats=[s for t,s in e.wallet.stats.items() if e.markets.get(t,{}).get('bot_id')==p['id']]
                closed=sum((s.closed for s in stats),ZERO);won=sum((s.won for s in stats),ZERO)
                past=self.summary.get(folder,{}).get(p['id'],{})
                gross=sum((s.gross for s in stats),D(past.get('gross','0')));fees=sum((s.fees_paid for s in stats),D(past.get('fees','0')));net=sum((s.gross-s.realized_fees for s in stats),D(past.get('net','0')))
                closed+=D(past.get('closed','0'));won+=D(past.get('won','0'))
                attempts=list(b.attempts.values())
                calibration=[]
                if folder=='favorites':
                    for band in ('70–79¢','80–89¢','90–95¢'):
                        selected=[(t,a) for t,a in b.attempts.items() if a.get('price_band')==band and e.markets[t].get('paid')]
                        band_past=past.get('bands',{}).get(band,{})
                        quantity=sum((e.wallet.stat(t).closed for t,a in selected),D(band_past.get('closed','0')))
                        winners=sum((e.wallet.stat(t).closed for t,a in selected if e.markets[t].get('yes_payout_confirmed')==('1' if a['side']=='yes' else '0')),D(band_past.get('won','0')))
                        cost=sum((D(a['price'])*e.wallet.stat(t).closed+e.wallet.stat(t).fees_paid for t,a in selected),D(band_past.get('cost','0')))
                        calibration.append(dict(band=band,contracts=str(quantity),win_rate=str(100*winners/quantity) if quantity else None,
                            breakeven=str(100*cost/quantity) if quantity else None,
                            net=str(sum((e.wallet.stat(t).gross-e.wallet.stat(t).realized_fees for t,a in selected),D(band_past.get('net','0'))))))
                bots[p['id']]=dict(gross_profit=str(gross),fees=str(fees),net_realized_pnl=str(net),win_rate=str(won/closed*100) if closed else None,
                    cycles=past.get('cycles',0)+sum(bool(a.get('recorded') or a.get('finished')) for a in attempts),excluded_cycles=past.get('gaps',0)+sum(not s.valid for s in stats),
                    attempts=past.get('attempts',0)+len(attempts),completed=past.get('completed',0)+sum(bool(a.get('completed') or a.get('complete')) for a in attempts),
                    unmatched=sum(1 for a in attempts if not a.get('complete') and not a.get('finished')) if folder=='complete_set' else sum(1 for a in attempts if a.get('first') and not a.get('recorded')),
                    decision=list(b.decisions.values())[-1] if getattr(b,'decisions',{}) else None,
                    message=self.data_message(e,b,p,now),discovery=getattr(self,'hourly_coverage',{}).get(p['series']),
                    scalper=b.research_snapshot() if isinstance(b,VolatilityScalper) else None,
                    scans=getattr(b,'scans',None),calibration=calibration,entry_timing=favorite_timing_rows(b.exit_evidence.cells) if folder=='favorites' else [])
                if isinstance(b,VolatilityScalper):
                    retained=b.research['totals'];bots[p['id']].update(completed=retained['completed'],attempts=max(retained['submitted'],retained['attempted']))
            result[folder]=dict(accounting=money,bots=bots,comparison=self.comparison_snapshot(folder,e,f,money,now),scanner=self.scanner_state if folder=='complete_set' else {k:v for k,v in getattr(self,'maker_discovery',{}).items() if k in ('state','ranked','reads')} if folder in MM_FOLDERS else None,
                assumptions=dict(latency_ms=e.latency*1000,worker_delay_included=bool(e.wall_clock),
                    execution_model='worker-delay-v1' if e.wall_clock else 'fixed-latency-v1',
                    independent_paper_portfolio=True,real_orders_enabled=False))
        return result
    def maintain(self):
        # Reports are durable in PostgreSQL; the hot checkpoint needs only open
        # execution state plus constant-size cumulative totals.
        self.rotate_candidates(max((e.now for e,_,_ in self.portfolios.values()),default=0))
        for folder,(e,f,ps) in self.portfolios.items():
            if folder in ('favorites',*SEQUENTIAL_FOLDERS):
                for t,m in list(e.markets.items()):
                    if not (m.get('weather_category') or m.get('sports') or m.get('hourly_price')) or e.now-m.get('discovered_at',e.now)<(120 if m.get('entry_parked') else 300):continue
                    b=f.owner(t);a=b.attempts.get(t,{})
                    if a.get('first') or any(l.ticker==t for l in e.wallet.lots):continue
                    # Keep the shared view while another strategy owns inventory.
                    # In particular, late-only Favorites must still see a game
                    # that Sequential bought earlier in live play.
                    if any(l.ticker==t for other,_,_ in self.portfolios.values() if other is not e for l in other.wallet.lots):continue
                    if a and not a.get('recorded') and e.now<a.get('entry_deadline',0):continue
                    e.cancel_buys(t)
                    if any(o.ticker==t and o.status in ('pending','resting') for o in e.orders.values()):continue
                    if a and not a.get('recorded') and isinstance(b,SequentialStrategy):b.finish(t)
                    old=b.attempts.pop(t,None)
                    if old:
                        totals=self.summary.setdefault(folder,{}).setdefault(m['bot_id'],{})
                        totals['attempts']=totals.get('attempts',0)+1
                        totals['cycles']=totals.get('cycles',0)+1
                    for mapping in (e.markets,e.books,e.fees,e.wallet.stats,e.gap_reasons):mapping.pop(t,None)
                    e.orders={i:o for i,o in e.orders.items() if o.ticker!=t}
                    for name in ('history','decisions','exit_at'):
                        mapping=getattr(b,name,None)
                        if mapping is not None:mapping.pop(t,None)
                    f.halted.discard(t);self.extra.pop(t,None)
            if folder in MM_FOLDERS:
                # Long-dated, flat probes must not accumulate until settlement.
                # Their orders/events and research remain in the durable journal.
                for t,m in list(e.markets.items()):
                    if not m.get('entry_parked') or e.now-m.get('discovered_at',e.now)<120:continue
                    b=f.owner(t);a=b.attempts.get(t,{}) if b else {}
                    if a.get('first') and not a.get('recorded') or any(l.ticker==t for l in e.wallet.lots):continue
                    if any(o.ticker==t and o.status in ('pending','resting') for o in e.orders.values()):continue
                    s=e.wallet.stat(t);totals=self.summary.setdefault(folder,{}).setdefault(m['bot_id'],{})
                    for key,value in dict(gross=s.gross,fees=s.fees_paid,net=s.gross-s.realized_fees,closed=s.closed,won=s.won).items():
                        totals[key]=str(D(totals.get(key,'0'))+value)
                    if a:
                        for key,value in dict(attempts=1,cycles=bool(a.get('recorded')),completed=bool(a.get('completed'))).items():totals[key]=totals.get(key,0)+value
                    for mapping in (e.markets,e.books,e.fees,e.wallet.stats,e.gap_reasons):mapping.pop(t,None)
                    e.orders={i:o for i,o in e.orders.items() if o.ticker!=t};e.pending=[item for item in e.pending if item[3] in e.orders]
                    f.halted.discard(t)
                    if b:
                        for mapping in (b.attempts,b.history,b.last_eval):mapping.pop(t,None)
                        b.last_signature={key:v for key,v in b.last_signature.items() if key[0]!=t}
            retired=[t for t,m in e.markets.items() if m.get('paid') and not any(l.ticker==t for l in e.wallet.lots)]
            if folder=='complete_set':
                owner=next(iter(f.bots.values()))
                # Rotate untraded candidates so a small fee-verification budget
                # does not trap the scanner on the first few events all day.
                for event,tickers in list(owner.groups.items()):
                    if event not in owner.attempts and all(e.now-e.markets[t].get('discovered_at',e.now)>300 for t in tickers if t in e.markets):
                        owner.groups.pop(event)
                        for t in tickers:
                            if t in e.markets and not any(l.ticker==t for l in e.wallet.lots):
                                for mapping in (e.markets,e.books,e.fees,e.wallet.stats):mapping.pop(t,None)
                                self.extra.pop(t,None)
                retired=[t for t in retired if t in e.markets and all(e.markets.get(other,{}).get('paid') for group in owner.groups.values() if t in group for other in group)]
            for t in retired:
                b=f.owner(t);p=e.markets[t];s=e.wallet.stat(t)
                if b and folder!='complete_set':b.step(t)
                totals=self.summary.setdefault(folder,{}).setdefault(p['bot_id'],{})
                for key,value in dict(gross=s.gross,fees=s.fees_paid,net=s.gross-s.realized_fees,closed=s.closed,won=s.won).items():
                    totals[key]=str(D(totals.get(key,'0'))+value)
                totals['gaps']=totals.get('gaps',0)+(not s.valid)
                a=b.attempts.pop(t,None) if b and folder!='complete_set' else None
                if a:
                    for key,value in dict(attempts=1,cycles=bool(a.get('recorded')),completed=bool(a.get('completed'))).items():totals[key]=totals.get(key,0)+value
                    if folder=='favorites':
                        band=totals.setdefault('bands',{}).setdefault(a['price_band'],{})
                        for key,value in dict(closed=s.closed,won=s.closed if p.get('yes_payout_confirmed')==('1' if a['side']=='yes' else '0') else ZERO,cost=D(a['price'])*s.closed+s.fees_paid,net=s.gross-s.realized_fees).items():band[key]=str(D(band.get(key,'0'))+value)
                for mapping in (e.markets,e.books,e.fees,e.wallet.stats,e.gap_reasons):mapping.pop(t,None)
                e.orders={i:o for i,o in e.orders.items() if o.ticker!=t}
                e.pending=[item for item in e.pending if item[3] in e.orders]
                e.closed_reports.discard(t);e.settled.discard(t);f.halted.discard(t);self.extra.pop(t,None)
                if b:
                    for name in ('phases','emergency','last_exit','history','decisions','exit_at','last_eval'):
                        mapping=getattr(b,name,None)
                        if mapping is not None:mapping.pop(t,None)
                    if isinstance(b,VolatilityScalper):
                        b.last_signature={key:v for key,v in b.last_signature.items() if key[0]!=t}
            if folder=='complete_set':
                b=next(iter(f.bots.values()))
                for event,tickers in list(b.groups.items()):
                    if all(t not in e.markets for t in tickers):
                        b.groups.pop(event);a=b.attempts.pop(event,None)
                        if a:
                            totals=self.summary.setdefault(folder,{}).setdefault(ps[0]['id'],{})
                            for key,value in dict(attempts=1,cycles=1,completed=bool(a.get('complete'))).items():totals[key]=totals.get(key,0)+value
            e.prune_terminal_orders()
        # One ticker may belong to both a basket and a favorite. Retiring one
        # portfolio must not unsubscribe another portfolio's remaining position.
        self.tape.prune({t for e,_,_ in self.portfolios.values() for t,m in e.markets.items() if not m.get('paid')})
        self.extra={t:t for t in self.feed_markets()}
        self.extra.update({t:t for t,m in self.portfolios['complete_set'][0].markets.items() if not m.get('paid')})

    def reset(self,folder):
        e,f,ps=self.portfolios[folder]
        # Clearing synthetic open inventory is a session reset, not a sale or profit.
        self.models[folder].cells={}
        self.summary.pop(folder,None)
        self.comparison.pop(folder,None)
        e.wallet=Wallet(D(1000));e.orders={};e.pending=[];e.closed_reports=set();e.trade_ids=set()
        for b in f.bots.values():
            b.attempts={};b.history={} if hasattr(b,'history') else None
            if hasattr(b,'decisions'):b.decisions={}
            if hasattr(b,'exit_evidence'):b.exit_evidence.cells={}
            if isinstance(b,SequentialStrategy):b.reset_trial()
            if isinstance(b,VolatilityScalper):
                from .scalper import bucket
                b.research=dict(totals=bucket(),cells={},recent=[]);b.history={};b.last_eval={};b.last_signature={}
            if hasattr(b,'scans'):b.scans=0;b.profitable=0
            if hasattr(b,'last_reason'):b.last_reason='Fresh paper session · waiting for eligible markets'
        f.halted.update(t for t,m in e.markets.items() if not m.get('paid'))
        for ticker,m in e.markets.items():
            m.pop('entry_recovery_halt',None)
            e.wallet.stat(ticker)
        e.log('SESSION_RESET',reason='New $1,000 virtual account; previous session archived')
