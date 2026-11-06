"""Owner-authenticated shadow controls and durable results; virtual money only."""
import csv,io,json,time
from uuid import uuid4
from decimal import Decimal as D
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from services.demo.store import DemoStore
from services.paper_demo.shadow.storage import put
from services.trading.mode import require_demo,ModeConflict

PERIODS={'all':None,'1H':3600,'6H':21600,'24H':86400}
ACCOUNTING_LOG_AT=0


def aggregate(reports):
    excluded=sum(not r.get('data_valid',False) for r in reports)
    reports=[r for r in reports if r.get('data_valid',False)]
    closed=sum((D(r.get('closed_contracts','0')) for r in reports),D(0))
    won=sum((D(r.get('winning_contracts','0')) for r in reports),D(0))
    return dict(gross_profit=str(sum((D(r['gross_profit']) for r in reports),D(0))),
        fees=str(sum((D(r['total_fees_paid']) for r in reports),D(0))),
        net_realized_pnl=str(sum((D(r['net_realized_pnl']) for r in reports),D(0))),
        win_rate=str(won/closed*100) if closed else None,
        cycles=len(reports),excluded_cycles=excluded)


def install_shadow(app,auth,mutate,pool):
    store=DemoStore(pool)
    def query(request,allowed=()):
        if any(k not in allowed or len(request.query_params.getlist(k))!=1 for k in request.query_params):
            raise HTTPException(422,'Invalid filters')
    @app.get('/demo/shadow/workspace')
    def workspace(request:Request):
        global ACCOUNTING_LOG_AT
        auth(request);query(request,('version',))
        latest=request.query_params.get('version','latest')
        if latest not in ('latest','full'):raise HTTPException(422,'Invalid version')
        marker=store.get('shadow/installed')
        if not marker:return dict(contract='demo-v1',installed=False,bots=[],real_orders_enabled=False)
        health=store.get('health');status=store.get('shadow/status')
        status=status['progress'] if status else dict(virtual_cash='1000',available_cash='1000',positions=[],orders=[],market_states={})
        money=status.get('accounting')
        status=dict(status);status.pop('accounting',None)
        current=money.get('current_cycles',{}) if money else {}
        snapshot_at=money['at'] if money else status.get('at',time.time())
        from psycopg.types.json import Jsonb
        profiles=sorted(store.rows('shadow/bot/',100),key=lambda r:r['parameters']['name'])
        revisions={r['parameters']['id']:r['parameters']['revision'] for r in profiles}
        now=time.time()
        scope="(%s OR (progress->>'bot_revision')::integer=coalesce((%s::jsonb->>(progress->>'bot_id'))::integer,-1))"
        with pool.connection() as c:
            latest_rows=c.execute("SELECT DISTINCT ON (progress->>'bot_id') progress FROM research_job WHERE idempotency_key>='demo/shadow/report/' AND idempotency_key<'demo/shadow/report/zzzz' AND "+scope+" ORDER BY progress->>'bot_id',(progress->>'at')::numeric DESC",(latest=='full',Jsonb(revisions))).fetchall()
            metrics=c.execute("""WITH r AS (
                SELECT progress AS p FROM research_job WHERE idempotency_key>='demo/shadow/report/'
                AND idempotency_key<'demo/shadow/report/zzzz' AND """+scope+"""),
                windows(period,seconds) AS (VALUES ('all',NULL::integer),('1H',3600),('6H',21600),('24H',86400))
                SELECT p->>'bot_id' AS bot,period,
                count(*) FILTER(WHERE (p->>'data_valid')::boolean) AS cycles,
                count(*) FILTER(WHERE NOT (p->>'data_valid')::boolean) AS excluded_cycles,
                coalesce(sum((p->>'gross_profit')::numeric) FILTER(WHERE (p->>'data_valid')::boolean),0)::text AS gross_profit,
                coalesce(sum((p->>'total_fees_paid')::numeric) FILTER(WHERE (p->>'data_valid')::boolean),0)::text AS fees,
                coalesce(sum((p->>'net_realized_pnl')::numeric) FILTER(WHERE (p->>'data_valid')::boolean),0)::text AS net_realized_pnl,
                (100*sum((p->>'winning_contracts')::numeric) FILTER(WHERE (p->>'data_valid')::boolean)/
                nullif(sum((p->>'closed_contracts')::numeric) FILTER(WHERE (p->>'data_valid')::boolean),0))::text AS win_rate
                FROM r CROSS JOIN windows WHERE seconds IS NULL OR (p->>'at')::numeric>=%s-seconds
                GROUP BY p->>'bot_id',period""",(latest=='full',Jsonb(revisions),now)).fetchall()
            # Financial results include every paper trade. Data quality is a
            # separate count; it must never make a real simulated loss disappear.
            financial=c.execute("""WITH history AS (
                SELECT progress AS p,true AS reported FROM research_job
                WHERE idempotency_key>='demo/shadow/report/' AND idempotency_key<'demo/shadow/report/zzzz'
                AND NOT ((progress->>'ticker')=ANY(%s::text[]))
                AND (progress->>'at')::numeric<=%s),
                r AS (SELECT * FROM history UNION ALL SELECT value,false FROM jsonb_each(%s::jsonb)),
                windows(period,seconds,full_history) AS (VALUES ('account',NULL::integer,true),
                    ('all',NULL::integer,false),('1H',3600,false),('6H',21600,false),('24H',86400,false))
                SELECT p->>'bot_id' AS bot,period,
                count(*) FILTER(WHERE reported AND (p->>'data_valid')::boolean) AS cycles,
                count(*) FILTER(WHERE reported AND NOT (p->>'data_valid')::boolean) AS excluded_cycles,
                coalesce(sum((p->>'gross_profit')::numeric),0)::text AS gross_profit,
                coalesce(sum((p->>'total_fees_paid')::numeric),0)::text AS fees,
                coalesce(sum((p->>'net_realized_pnl')::numeric),0)::text AS net_realized_pnl,
                (100*sum((p->>'winning_contracts')::numeric)/nullif(sum((p->>'closed_contracts')::numeric),0))::text AS win_rate
                FROM r CROSS JOIN windows
                WHERE (full_history OR %s OR (p->>'bot_revision')::integer=coalesce((%s::jsonb->>(p->>'bot_id'))::integer,-1))
                AND (seconds IS NULL OR (p->>'at')::numeric>=%s-seconds)
                GROUP BY p->>'bot_id',period""",(list(current),snapshot_at,Jsonb(current),latest=='full',Jsonb(revisions),snapshot_at)).fetchall()
        mapped={(m['bot'],m['period']):{k:v for k,v in m.items() if k not in ('bot','period')} for m in metrics}
        actual={(m['bot'],m['period']):{k:v for k,v in m.items() if k not in ('bot','period')} for m in financial}
        reports={r['progress'].get('bot_id'):r['progress'] for r in latest_rows}
        bots=[]
        for row in profiles:
            profile=row['parameters']
            account=dict(money['bots'].get(profile['id'],{})) if money else None
            lifetime=actual.get((profile['id'],'account'),aggregate([]))
            if account is not None:
                account['realized_pnl']=lifetime['net_realized_pnl']
                account['total_pnl']=str(D(account['realized_pnl'])+D(account['unrealized_pnl'])) if account.get('unrealized_pnl') is not None else None
            bots.append(dict(profile,desired=row['progress']['desired'],
                metrics={period:mapped.get((profile['id'],period),aggregate([])) for period in PERIODS},
                financial_metrics={period:actual.get((profile['id'],period),aggregate([])) for period in PERIODS},
                account=account,
                latest_report=reports.get(profile['id'])))
        if money:
            money['quality']=dict(verified_cycles=sum(m['cycles'] for m in financial if m['period']=='account'),
                gap_cycles=sum(m['excluded_cycles'] for m in financial if m['period']=='account'))
            key='total_pnl' if money['portfolio']['total_pnl'] is not None else 'realized_pnl'
            money['portfolio']['reconciliation_difference']=str(D(money['portfolio'][key])-
                sum((D(b['account'].get(key) or '0') for b in bots),D(0)))
            if time.monotonic()>=ACCOUNTING_LOG_AT:
                ACCOUNTING_LOG_AT=time.monotonic()+30
                print(json.dumps(dict(event='shadow_accounting_reconciled',at=snapshot_at,
                    realized_pnl=money['portfolio']['realized_pnl'],total_pnl=money['portfolio']['total_pnl'],
                    difference=money['portfolio']['reconciliation_difference'],
                    **money['quality'],real_orders_enabled=False)),flush=True)
        commands=store.rows('shadow/command/',100)
        return dict(contract='demo-v1',environment='demo',installed=True,real_orders_enabled=False,
            engine=marker['progress'],bots=bots,status=status,
            accounting={k:money[k] for k in ('schema','at','portfolio','quality')} if money else None,version=latest,
            connection_configured=bool(store.get('paper-credentials')),
            health=health['progress'] if health else dict(state='waiting',message='Waiting for worker'),
            pending_refills=sum(r['parameters'].get('amount_cents',0) for r in commands if not r['progress'].get('done')))

    class Change(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)
        revision:int=Field(ge=1)
        contracts:int|None=Field(default=None,ge=1,le=10000)
        desired:str|None=Field(default=None,pattern='^(running|paused)$')
    @app.post('/demo/shadow/bots/{identifier}')
    def change(identifier:str,body:Change,request:Request):
        mutate(request);query(request)
        with pool.connection() as c:
            if body.desired=='running':
                try:require_demo(c)
                except ModeConflict as exc:raise HTTPException(409,str(exc)) from None
            row=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('demo/shadow/bot/'+identifier,)).fetchone()
            if not row:raise HTTPException(404,'Shadow bot not found')
            p,state=row['parameters'],row['progress']
            if p['revision']!=body.revision:raise HTTPException(409,'Bot changed elsewhere; reload first')
            if body.contracts is not None and body.contracts!=p['contracts']:
                put(c,'demo/shadow/version/'+identifier+'/'+str(p['revision']),{},p)
                p=dict(p,contracts=body.contracts,revision=p['revision']+1,changed_at=time.time())
            if body.desired is not None:state=dict(state,desired=body.desired)
            put(c,'demo/shadow/bot/'+identifier,p,state)
        return dict(contract='demo-v1',saved=True,revision=p['revision'],real_orders_enabled=False)

    class Funds(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)
        amount_cents:int=Field(ge=1,le=100000000)
        request_id:str=Field(min_length=16,max_length=80,pattern='^[A-Za-z0-9-]+$')
    @app.post('/demo/shadow/funds')
    def funds(body:Funds,request:Request):
        mutate(request);query(request)
        if not store.get('shadow/installed'):raise HTTPException(409,'Shadow engine is initializing')
        with pool.connection() as c:
            key='demo/shadow/command/'+body.request_id
            from psycopg.types.json import Jsonb
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
              VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",
              (uuid4(),Jsonb(dict(amount_cents=body.amount_cents)),Jsonb(dict(done=False)),key))
            previous=c.execute('SELECT parameters FROM research_job WHERE idempotency_key=%s',(key,)).fetchone()
            if previous['parameters']['amount_cents']!=body.amount_cents:raise HTTPException(409,'Refill request ID already used')
        return dict(contract='demo-v1',queued=True,real_orders_enabled=False)

    class Bulk(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)
        action:str=Field(pattern='^(pause|resume)$')
    @app.post('/demo/shadow/bulk')
    def bulk(body:Bulk,request:Request):
        mutate(request);query(request)
        with pool.connection() as c:
            if body.action=='resume':
                try:require_demo(c)
                except ModeConflict as exc:raise HTTPException(409,str(exc)) from None
            desired='paused' if body.action=='pause' else 'running'
            c.execute("UPDATE research_job SET progress=jsonb_set(progress,'{desired}',to_jsonb(%s::text)) WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz'",(desired,))
        return dict(contract='demo-v1',saved=True,real_orders_enabled=False)

    @app.get('/demo/shadow/events')
    def events(request:Request):
        auth(request);query(request)
        with pool.connection() as c:
            rows=c.execute("SELECT progress FROM research_job WHERE idempotency_key>='demo/shadow/event/' AND idempotency_key<'demo/shadow/event/zzzz' ORDER BY created_at DESC,id DESC LIMIT 100").fetchall()
        return dict(contract='demo-v1',items=[r['progress'] for r in rows],real_orders_enabled=False)
