"""Independent paper portfolios over one read-only feed, durably checkpointed together."""
import json,time
from decimal import Decimal as D
from dataclasses import asdict
from .core import Engine,StrategyFleet,FeePolicy,Wallet,ZERO
from .state import encode,restore
from .accounting import snapshot
from .sequential import SequentialStrategy,PairModel
from .complete_set import CompleteSetStrategy
from .favorites import FavoritesStrategy

class ExperimentAudit:
    def __init__(self,parent,folder):self.parent,self.folder=parent,folder;self.path=parent.path
    def log(self,now,kind,wallet,**fields):
        self.parent.log(now,'EXPERIMENT',wallet,folder_id=self.folder,experiment_kind=kind,**fields)

class ExperimentFleet(StrategyFleet):
    def __init__(self,engine,profiles,model,complete=False):
        self.e=engine;self.halted=set();self.bots={};self.complete=complete
        for p in profiles:
            b=CompleteSetStrategy(engine,p) if complete else FavoritesStrategy(engine,p) if p.get('strategy')=='favorites' else SequentialStrategy(engine,p,model)
            b.halted=self.halted;self.bots[p['series']]=b
        engine.fill_callback=self.on_fill;engine.strategy=self
    def owner(self,ticker):return next(iter(self.bots.values()),None) if self.complete else super().owner(ticker)
    def step(self,changed_ticker=None):
        if self.complete:
            for b in self.bots.values():b.step(changed_ticker)
        else:super().step(changed_ticker)

class ExperimentSuite:
    def __init__(self,host,rows,previous=None):
        self.summary=(previous or {}).get('_summary',{})
        self.host=host;self.rows=rows;self.portfolios={};self.models={};self.extra={};self.scanner_cursor='';self.scanner_state={}
        for folder in ('sequential','complete_set','favorites'):
            ps=[r['parameters'] for r in rows if r['parameters'].get('folder_id')==folder]
            model=PairModel((previous or {}).get(folder,{}).get('model'))
            e=Engine(ExperimentAudit(host.audit,folder),cash='1000',latency_ms=150,seed=17,toxic_fill_probability=0)
            f=ExperimentFleet(e,ps,model,folder=='complete_set')
            state=(previous or {}).get(folder)
            if state:
                restore(e,f,state['engine'])
                for series,info in state.get('strategies',{}).items():
                    if series not in f.bots:continue
                    b=f.bots[series]
                    b.attempts=info.get('attempts',{})
                    if hasattr(b,'exit_evidence'):b.exit_evidence.cells=info.get('exit_evidence',{})
                    if folder=='complete_set':b.groups=info.get('groups',{})
            for p in ps:
                r=next(r for r in rows if r['parameters']['id']==p['id']);f.bots[p['series']].enabled=r['progress'].get('desired')=='running'
            self.portfolios[folder]=(e,f,ps);self.models[folder]=model
        self.control(rows)
    def state(self):
        return dict(_summary=self.summary,**{folder:dict(engine=encode(e,f),model=self.models[folder].cells,
            strategies={s:dict(attempts=b.attempts,groups=getattr(b,'groups',{}),exit_evidence=b.exit_evidence.cells if hasattr(b,'exit_evidence') else {}) for s,b in f.bots.items()})
            for folder,(e,f,ps) in self.portfolios.items()})
    def control(self,rows,mode='demo'):
        for folder,(e,f,ps) in self.portfolios.items():
            for p in ps:
                row=next((r for r in rows if r['parameters']['id']==p['id']),None)
                if not row:continue
                b=f.bots[p['series']];enabled=row['progress'].get('desired')=='running' and mode=='demo'
                if not enabled and b.enabled:
                    for t in e.markets:e.cancel_buys(t)
                b.enabled=enabled;b.contracts=D(row['parameters']['contracts'])
    def add_set(self,payload,now):
        e,f,ps=self.portfolios['complete_set'];profile=ps[0]
        for p in payload['markets']:
            market=dict(p['market'],bot_id=profile['id'],bot_name=profile['name'],strategy_version='complete-set-1',bot_revision=profile['revision'])
            if market['ticker'] not in e.markets:e.handle('market',dict(p,market=market),now)
            self.extra[market['ticker']]=market['ticker']
        f.bots[profile['series']].register(payload['event'],[p['market'] for p in payload['markets']])
    def prepare(self,e,source,payload,now):
        for ticker in list(e.books):
            if ticker in e.settled:continue
            try:
                kind,m=self.host.verified_fees.schedule(ticker,now)
                e.fees[ticker]=FeePolicy(D(str(m)),D(str(m)) if kind=='quadratic_with_maker_fees' else ZERO)
            except Exception:
                if e.books[ticker].valid:e.data_gap(ticker,'current fee schedule unverified')
                if source=='kalshi' and payload.get('msg',{}).get('market_ticker')==ticker:return dict(payload,type='fee_blocked')
        return payload
    def handle(self,source,payload,now):
        if source=='set_markets':self.add_set(payload,now);return
        for folder,(e,f,ps) in self.portfolios.items():
            local=payload
            if source=='market':
                if folder not in ('sequential','favorites'):continue
                profile=next((p for p in ps if p['series']==payload['market']['ticker'].split('-')[0]),None)
                if not profile:continue
                local=dict(payload,market=dict(payload['market'],bot_id=profile['id'],bot_name=profile['name'],strategy_version=folder+'-1',bot_revision=profile['revision']))
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
            e.handle(source,self.prepare(e,source,local,now),now)
            # Complete-set markets are not in legacy discovery's settlement gate.
            if source=='kalshi' and payload.get('type')=='market_lifecycle_v2':
                msg=payload.get('msg',{});t=msg.get('market_ticker')
                if t in e.markets and msg.get('event_type')=='settled' and msg.get('result') in ('yes','no'):
                    e.markets[t]['yes_payout_confirmed']='1' if msg['result']=='yes' else '0'
                    e.handle('settlement',dict(ticker=t,yes_payout=e.markets[t]['yes_payout_confirmed']),now)
    def snapshot(self,now):
        result={}
        for folder,(e,f,ps) in self.portfolios.items():
            money=snapshot(e,ps,now)
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
                    message=getattr(b,'last_reason','Learning completion probabilities · 1-contract paper exploration'),
                    scans=getattr(b,'scans',None),calibration=calibration)
            result[folder]=dict(accounting=money,bots=bots,scanner=self.scanner_state if folder=='complete_set' else None,
                assumptions=dict(latency_ms=150,independent_paper_portfolio=True,real_orders_enabled=False))
        return result
    def maintain(self):
        # Reports are durable in PostgreSQL; the hot checkpoint needs only open
        # execution state plus constant-size cumulative totals.
        for folder,(e,f,ps) in self.portfolios.items():
            retired=[t for t,m in e.markets.items() if m.get('paid') and not any(l.ticker==t for l in e.wallet.lots)]
            if folder=='complete_set':
                owner=next(iter(f.bots.values()))
                retired=[t for t in retired if all(e.markets.get(other,{}).get('paid') for group in owner.groups.values() if t in group for other in group)]
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
                    for name in ('phases','emergency','last_exit','history','decisions','exit_at'):
                        mapping=getattr(b,name,None)
                        if mapping is not None:mapping.pop(t,None)
            if folder=='complete_set':
                b=next(iter(f.bots.values()))
                for event,tickers in list(b.groups.items()):
                    if all(t not in e.markets for t in tickers):
                        b.groups.pop(event);a=b.attempts.pop(event,None)
                        if a:
                            totals=self.summary.setdefault(folder,{}).setdefault(ps[0]['id'],{})
                            for key,value in dict(attempts=1,cycles=1,completed=bool(a.get('complete'))).items():totals[key]=totals.get(key,0)+value
            e.prune_terminal_orders()

    def reset(self,folder):
        e,f,ps=self.portfolios[folder]
        # Clearing synthetic open inventory is a session reset, not a sale or profit.
        self.models[folder].cells={}
        self.summary.pop(folder,None)
        e.wallet=Wallet(D(1000));e.orders={};e.pending=[];e.closed_reports=set();e.trade_ids=set()
        for b in f.bots.values():
            b.attempts={};b.history={} if hasattr(b,'history') else None
            if hasattr(b,'decisions'):b.decisions={}
            if hasattr(b,'exit_evidence'):b.exit_evidence.cells={}
            if hasattr(b,'scans'):b.scans=0;b.profitable=0
            if hasattr(b,'last_reason'):b.last_reason='Fresh paper session · waiting for eligible markets'
        f.halted.update(t for t,m in e.markets.items() if not m.get('paid'))
        for ticker,m in e.markets.items():e.wallet.stat(ticker)
        e.log('SESSION_RESET',reason='New $1,000 virtual account; previous session archived')
