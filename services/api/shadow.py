"""Owner-authenticated shadow controls and durable results; virtual money only."""
import csv,io,json,time,hashlib,gzip,base64,math,re
from uuid import uuid4
from decimal import Decimal as D
from fastapi import Request,Response,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,ConfigDict,Field
from services.demo.store import DemoStore
from services.paper_demo.shadow.storage import put
from services.paper_demo.shadow.diagnostic_batches import merge_recent_events
from services.paper_demo.shadow.performance import folder_performance
from services.paper_demo.shadow.bot_performance import bot_performance
from services.trading.mode import require_demo,ModeConflict

from services.paper_demo.shadow.sequential_comparison import BOT_LIMIT,SEQUENTIAL_FOLDERS
from services.paper_demo.shadow.scalper import SCALPER_FOLDERS
from services.paper_demo.shadow.market_maker import MM_FOLDERS,CATEGORIES

PERIODS={'all':None,'1H':3600,'6H':21600,'24H':86400}
ACCOUNTING_LOG_AT=0

LEARNING_PROFILES={
    'sequential':dict(classification='data_learning',state='using_statistics_now',
        decisions='Entry pair selection, completion likelihood and expected net return',
        features=['entry leg prices','time to close','price movement','first-fill outcome','pair completion','net P/L'],
        segments='series × 3-minute time bucket × moving/quiet × YES/NO entry prices',
        minimum='20 matching settled attempts before the 95% lower expected-net estimate can authorize empirical sizing',
        fallback='1-contract least-sampled paper exploration when no supported empirical setup exists'),
    'sequential_flexible':dict(classification='data_learning',state='using_statistics_now',
        decisions='Entry pair selection, completion likelihood and expected net return',
        features=['entry leg prices','time to close','price movement','first-fill outcome','pair completion','net P/L'],
        segments='series × time/movement × entry-price setup',
        minimum='20 matching settled attempts for a confidence-bounded empirical setup',
        fallback='small paper exploration of the least-sampled matching setup'),
    'sequential_adaptive':dict(classification='data_learning',state='using_statistics_now',
        decisions='Adaptive pair selection and expected completion/net-return thresholds',
        features=['entry leg prices','time to close','market movement','first-fill outcome','completion','net P/L'],
        segments='adaptive sequential setup cells',
        minimum='Uses only supported empirical cells; sparse cells remain exploratory',
        fallback='bounded paper exploration rather than inventing a probability'),
    'favorites':dict(classification='data_learning',state='using_statistics_now',
        decisions='Entry value ceiling and evidence-based risk/exit behavior',
        features=['market type','side','entry price','time remaining','maker fill','settled outcome','fees','realized P/L'],
        segments='market series/type × purchased side × 5¢ price tier × time-to-expiration bucket',
        minimum='Sparse cells collect paper data; calibrated/value-qualified entries require settled evidence',
        fallback='paper-data collection with duplicate/risk/capital caps; no missing outcome is treated as a win or loss'),
    'favorites_statistics':dict(classification='data_learning',state='using_statistics_now',
        decisions='Whether to trade a price/time cell, fallback evidence level and targeted exploration',
        features=['market type','price tier','time remaining','distinct resolved events','win rate','ROI','confidence lower bound'],
        segments='market type × 5¢ price tier × time-to-expiration bucket with pooled fallbacks',
        minimum='20 distinct resolved events per preferred evidence cell by default',
        fallback='broader evidence fallback or separately capped 2-contract exploration of sparse cells'),
    'volatility_scalper':dict(classification='future_learning_candidate',state='collecting_only',
        decisions='Current entries remain rule/live-feature driven; research can later tune thresholds and execution',
        features=['spread','depth','volatility','momentum','range','execution type','fill result','holding time','P/L'],
        segments='strategy approach × live microstructure feature cells',
        minimum='No historical sample threshold currently changes live rules',
        fallback='Fixed configured rules with fresh-book and execution checks'),
    'scalper_fixed':dict(classification='future_learning_candidate',state='collecting_only',
        decisions='Future threshold and execution tuning; current rules are fixed/configured',
        features=['spread','depth','volatility','price movement','fill quality','P/L'],
        segments='fixed-scalper research cells',
        minimum='No historical sample threshold currently changes live rules',
        fallback='Fixed configured rules'),
    'scalper_grid':dict(classification='future_learning_candidate',state='collecting_only',
        decisions='Future grid/range and execution tuning; current rules are fixed/configured',
        features=['range','spread','depth','volatility','fill quality','P/L'],
        segments='grid-scalper research cells',
        minimum='No historical sample threshold currently changes live rules',
        fallback='Fixed configured rules'),
    'scalper_momentum':dict(classification='future_learning_candidate',state='collecting_only',
        decisions='Future momentum and execution tuning; current rules are fixed/configured',
        features=['momentum','spread','depth','volatility','fill quality','P/L'],
        segments='momentum-scalper research cells',
        minimum='No historical sample threshold currently changes live rules',
        fallback='Fixed configured rules'),
    'scalper_dislocation':dict(classification='future_learning_candidate',state='collecting_only',
        decisions='Future liquidity-dislocation and execution tuning; current rules are fixed/configured',
        features=['liquidity dislocation','spread','depth','volatility','fill quality','P/L'],
        segments='dislocation-scalper research cells',
        minimum='No historical sample threshold currently changes live rules',
        fallback='Fixed configured rules'),
    'market_maker':dict(classification='future_learning_candidate',state='collecting_only',
        decisions='Future quote placement/market selection tuning; current quoting uses live spread, depth, flow and configured limits',
        features=['spread','depth','recent executable flow','quote lifetime','queue position','maker fill rate','holding time','P/L'],
        segments='market category × microstructure/execution research cells',
        minimum='No retained historical-cell threshold currently changes quoting rules',
        fallback='Live microstructure rules and risk/exposure checks'),
    'maker_competitive':dict(classification='future_learning_candidate',state='collecting_only',
        decisions='Future inside-quote and market-selection tuning; current rules use live microstructure',
        features=['inside quote','spread','depth','recent executable flow','quote lifetime','maker fill rate','P/L'],
        segments='market category × competitive-quote research cells',
        minimum='No retained historical-cell threshold currently changes quoting rules',
        fallback='Live competitive maker configuration'),
    'complete_set':dict(classification='operational_only',state='not_learning',
        decisions='No historical model currently changes set execution',
        features=['executable set cost','fees','coverage','fill/completion','P/L'],
        segments='event/set execution records',
        minimum='Not applicable',
        fallback='Current executable-cost and coverage rules'),
    'convexity':dict(classification='future_learning_candidate',state='paused_history',
        decisions='Historical results are preserved for future analysis; paused bots do not adapt or resume automatically',
        features=['historical entries','exits','P/L','execution results'],
        segments='legacy bot/cycle history',
        minimum='No active learning threshold',
        fallback='Paused; history only')
}

def learning_diagnostics(folder_id,experiment):
    profile=dict(LEARNING_PROFILES.get(folder_id,dict(classification='operational_only',state='not_learning',
        decisions='No historical learning logic is currently registered',features=[],segments='—',minimum='Not applicable',fallback='Current configured rules')))
    bots=(experiment or {}).get('bots',{}) if isinstance(experiment,dict) else {}
    attempts=sum(int((b or {}).get('attempts') or 0) for b in bots.values())
    settled=sum(int((b or {}).get('completed') or 0) for b in bots.values())
    profile.update(observations=attempts,settled_observations=settled,
        open_observations=max(0,attempts-settled),bot_count=len(bots))
    if folder_id in SCALPER_FOLDERS or folder_id in MM_FOLDERS:
        totals=[(b or {}).get('scalper',{}).get('totals',{}) for b in bots.values()]
        profile.update(observations=sum(int(t.get('observations') or 0) for t in totals),
            settled_observations=sum(int(t.get('completed') or 0) for t in totals),
            open_observations=sum(max(0,int(t.get('submitted') or 0)-int(t.get('completed') or 0)) for t in totals),
            research_cells=sum(len((b or {}).get('scalper',{}).get('cells',{})) for b in bots.values()))
    if folder_id=='favorites_statistics':
        stats=(experiment or {}).get('statistics') or {}
        profile['last_refreshed_at']=stats.get('evidence_refreshed_at')
        profile['sample_threshold']=stats.get('min_samples',20)
        profile['decision_counts']=stats.get('decision_counts',{})
    return profile


def workspace_response(payload,*,compressed=False,request_started=None):
    started=time.monotonic()
    # These copies are used to build the bot cards but are not read by the UI.
    # Keep the durable worker snapshot intact and send each accounting view once.
    status=dict(payload['status']);status.pop('experiments',None)
    folders=[]
    for folder in payload['folders']:
        folder=dict(folder)
        account=folder.get('accounting')
        if account:
            folder['accounting']={k:v for k,v in account.items() if k not in ('current_cycles','bots')}
        folder.pop('bots',None)
        folders.append(folder)
    # Experimental metrics reference the same research object for every period.
    # Transmit that evidence once in bot.experiment, rather than expanding it
    # eight more times into the financial summary cards.
    metric_fields=('gross_profit','fees','net_realized_pnl','win_rate','cycles','excluded_cycles')
    cell_fields={'dimensions','completed','win_rate','net','average_net','entry_quantity','closed_quantity',
        'winning_quantity','entry_cost','holding_seconds'}
    bots=[]
    for source in payload.get('bots',[]):
        bot=dict(source)
        # latest_report is a durable worker/report artifact used to derive the
        # compact fields above, but the dashboard never reads it. Shipping one
        # full report per bot made the initial workspace payload grow with
        # report detail and could trip the 8 MiB transport guard.
        bot.pop('latest_report',None)
        if bot.get('experiment') is not None:
            experiment=bot['experiment']
            # Large research histories belong behind the existing per-bot
            # research endpoint. The initial workspace only needs compact
            # counters/decision summaries to render cards and folder totals.
            compact_experiment={k:v for k,v in experiment.items()
                if k not in ('entry_timing','calibration')}
            # Keep tiny research summaries actually visible on normal bot cards.
            # Bulk series belong in the per-bot research view; never let them
            # multiply initial workspace size across dozens of bots.
            if experiment.get('scalper') is None:
                for key in ('entry_timing','calibration'):
                    rows=experiment.get(key)
                    if isinstance(rows,list) and len(rows)<=8:
                        try:
                            encoded=json.dumps(rows,default=str,separators=(',',':'),
                                ensure_ascii=False,allow_nan=False).encode('utf-8')
                            if len(encoded)<=2048:compact_experiment[key]=rows
                        except (TypeError,ValueError):
                            # The normal JSON response still validates retained
                            # fields. Never leak a non-serializable research blob.
                            pass
            if experiment.get('scalper') is not None:
                research=experiment['scalper']
                compact_experiment['scalper']={k:v for k,v in research.items()
                    if k not in ('cells',)}
            bot['experiment']=compact_experiment
            for field in ('metrics','financial_metrics'):
                if field in bot:
                    bot[field]={period:{k:v for k,v in metric.items() if k in metric_fields}
                        for period,metric in bot[field].items()}
        # Keep the initial card payload bounded even if a strategy later adds
        # another large research field we did not know about yet. The full
        # experiment remains durable and is available through detail endpoints.
        try:bot_bytes=len(json.dumps(bot,default=str,separators=(',',':')).encode('utf-8'))
        except Exception:bot_bytes=0
        if bot_bytes>12000 and bot.get('experiment') is not None:
            experiment=bot['experiment']
            keep=('message','attempts','completed','unmatched','decision','scanner','state','mode')
            slim={k:experiment[k] for k in keep if k in experiment}
            if isinstance(experiment.get('scalper'),dict):
                research=experiment['scalper']
                slim['scalper']={k:research[k] for k in ('totals','config','periods') if k in research}
            bot['experiment']=slim
        bots.append(bot)
    response_payload=dict(payload,status=status,folders=folders,bots=bots)
    result=JSONResponse(response_payload)
    raw=result.body
    digest=hashlib.sha256(raw).hexdigest()
    if compressed:
        if len(raw)>8388608:
            # Log approximate section weights before rejecting the transport so
            # future growth has an actionable source instead of a generic size
            # failure. Durable records remain untouched.
            section_bytes={}
            for key,value in response_payload.items():
                try:section_bytes[key]=len(json.dumps(value,default=str,separators=(',',':')).encode('utf-8'))
                except Exception:section_bytes[key]=-1
            print(json.dumps(dict(event='dashboard_snapshot_oversize',decoded_bytes=len(raw),
                limit_bytes=8388608,section_bytes=section_bytes,
                bots=len(bots),folders=len(folders))),flush=True)
            raise HTTPException(503,'Dashboard snapshot exceeds its supported size')
        # Self-contained ASCII envelope: compressed data is far smaller and its
        # checksum describes the decoded JSON, independent of HTTP transforms.
        result=JSONResponse(dict(transport='workspace-gzip-v1',sha256=digest,bytes=len(raw),
            data=base64.b64encode(gzip.compress(raw,compresslevel=3,mtime=0)).decode('ascii')))
        result.headers['x-pocket-workspace-encoding']='gzip-base64-v1'
        print(json.dumps(dict(event='dashboard_transport',encoding='gzip-base64-v1',
            decoded_bytes=len(raw),wire_bytes=len(result.body),serialization_ms=(time.monotonic()-started)*1000,
            request_ms=(time.monotonic()-request_started)*1000 if request_started is not None else None)),flush=True)
    result.headers['x-pocket-workspace-contract']='demo-v1'
    result.headers['x-pocket-workspace-sha256']=digest
    result.headers['x-pocket-workspace-bytes']=str(len(raw))
    result.headers['cache-control']='no-store, no-transform'
    return result


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
    def workspace(request:Request,response:Response):
        global ACCOUNTING_LOG_AT
        request_started=time.monotonic()
        auth(request);query(request,('version',))
        latest=request.query_params.get('version','latest')
        if latest not in ('latest','full'):raise HTTPException(422,'Invalid version')
        response.headers['x-pocket-workspace-contract']='demo-v1'
        marker=store.get('shadow/installed')
        if not marker:return dict(contract='demo-v1',installed=False,bots=[],real_orders_enabled=False)
        health=store.get('health');status=store.get('shadow/status')
        status=status['progress'] if status else dict(virtual_cash='1000',available_cash='1000',positions=[],orders=[],market_states={})
        money=status.get('accounting')
        status=dict(status);status.pop('accounting',None)
        current=money.get('current_cycles',{}) if money else {}
        snapshot_at=money['at'] if money else status.get('at',time.time())
        from psycopg.types.json import Jsonb
        all_profiles=store.rows('shadow/bot/',BOT_LIMIT)
        for row in all_profiles:
            p=row['parameters'];row['parameters']=dict(p,name=p.get('name') or p.get('series') or p.get('id') or 'Unnamed bot')
        all_profiles.sort(key=lambda r:r['parameters']['name'])
        profiles=[r for r in all_profiles if r['parameters'].get('strategy','convexity')=='convexity']
        folder_rows=store.rows('shadow/folder/',24)
        reset_at=next((r['progress'].get('reset_at',0) for r in folder_rows if r['parameters']['id']=='convexity'),0)
        revisions={r['parameters']['id']:r['parameters']['revision'] for r in profiles}
        now=time.time()
        scope="(progress->>'at')::numeric>=%s AND (%s OR (progress->>'bot_revision')::integer=coalesce((%s::jsonb->>(progress->>'bot_id'))::integer,-1))"
        with pool.connection() as c:
            latest_rows=c.execute("SELECT DISTINCT ON (progress->>'bot_id') progress FROM research_job WHERE idempotency_key>='demo/shadow/report/' AND idempotency_key<'demo/shadow/report/zzzz' AND "+scope+" ORDER BY progress->>'bot_id',(progress->>'at')::numeric DESC",(reset_at,latest=='full',Jsonb(revisions))).fetchall()
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
                GROUP BY p->>'bot_id',period""",(reset_at,latest=='full',Jsonb(revisions),now)).fetchall()
            # Financial results include every paper trade. Data quality is a
            # separate count; it must never make a real simulated loss disappear.
            financial=c.execute("""WITH history AS (
                SELECT progress AS p,true AS reported FROM research_job
                WHERE idempotency_key>='demo/shadow/report/' AND idempotency_key<'demo/shadow/report/zzzz'
                AND NOT ((progress->>'ticker')=ANY(%s::text[]))
                AND (progress->>'at')::numeric<=%s AND (progress->>'at')::numeric>=%s),
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
                GROUP BY p->>'bot_id',period""",(list(current),snapshot_at,reset_at,Jsonb(current),latest=='full',Jsonb(revisions),snapshot_at)).fetchall()
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
                execution=next((r.get('execution') for r in sorted(current.values(),key=lambda r:r.get('at',0),reverse=True)
                    if r.get('bot_id')==profile['id'] and r.get('execution')),
                    (reports.get(profile['id']) or {}).get('execution')),
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
        experiments=status.get('experiments',{})
        for row in all_profiles:
            profile=row['parameters'];folder=profile.get('folder_id','convexity')
            if folder=='convexity':continue
            exp=experiments.get(folder,{})
            metric=exp.get('bots',{}).get(profile['id'],aggregate([]))
            account=exp.get('accounting',{}).get('bots',{}).get(profile['id'])
            if account is not None:
                account=dict(account,realized_pnl=metric['net_realized_pnl'])
                account['total_pnl']=str(D(account['realized_pnl'])+D(account['unrealized_pnl'])) if account.get('unrealized_pnl') is not None else None
            bots.append(dict(profile,desired=row['progress']['desired'],account=account,
                metrics={period:metric for period in PERIODS},financial_metrics={period:metric for period in PERIODS},
                experiment=metric,metrics_scope='current_session',latest_report=None))
        folders=[]
        for row in sorted(folder_rows,key=lambda r:r['parameters']['order']):
            f=dict(row['parameters'],**row['progress'])
            exp=experiments.get(f['id'],{})
            if f['id'] in experiments:f.update(exp)
            elif f['id']=='convexity':f['accounting']=money
            f['learning']=learning_diagnostics(f['id'],exp)
            folders.append(f)
        folder_performance(pool,folders,snapshot_at)
        bot_performance(pool,bots,folders,snapshot_at,status.get('positions',[]))
        commands=store.rows('shadow/command/',100)
        return workspace_response(dict(contract='demo-v1',environment='demo',installed=True,real_orders_enabled=False,
            engine=marker['progress'],bots=bots,status=status,folders=folders,
            accounting={k:money[k] for k in ('schema','at','portfolio','quality')} if money else None,version=latest,
            connection_configured=bool(store.get('paper-credentials')),
            health=health['progress'] if health else dict(state='waiting',message='Waiting for worker'),
            pending_refills=sum(r['parameters'].get('amount_cents',0) for r in commands if not r['progress'].get('done'))),
            compressed=request.headers.get('x-pocket-workspace-encoding')=='gzip-base64-v1',request_started=request_started)

    @app.get('/demo/shadow/research-folder/{identifier}')
    def research_folder_details(identifier:str,request:Request):
        auth(request);query(request)
        if identifier not in ('favorites','favorites_statistics'):raise HTTPException(422,'Invalid research folder')
        row=store.get('shadow/status');status=row['progress'] if row else {}
        folder=status.get('experiments',{}).get(identifier,{})
        out={}
        for bot_id,metric in folder.get('bots',{}).items():
            if not re.fullmatch('[a-z0-9_]{1,40}',str(bot_id)):continue
            research={}
            for key in ('entry_timing','calibration'):
                rows=metric.get(key)
                if isinstance(rows,list):research[key]=rows
            if research:out[bot_id]=research
        return dict(contract='demo-v1',folder_id=identifier,at=status.get('at'),bots=out,real_orders_enabled=False)

    @app.get('/demo/shadow/research/{identifier}')
    def research_details(identifier:str,request:Request):
        auth(request);query(request)
        if not re.fullmatch('[a-z0-9_]{1,40}',identifier):raise HTTPException(422,'Invalid bot')
        row=store.get('shadow/status');status=row['progress'] if row else {}
        for folder in status.get('experiments',{}).values():
            research=folder.get('bots',{}).get(identifier,{}).get('scalper')
            if research is not None:
                return dict(contract='demo-v1',bot_id=identifier,at=status.get('at'),research=research,real_orders_enabled=False)
        raise HTTPException(404,'Research not available')

    class Change(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)
        revision:int=Field(ge=1)
        contracts:int|None=Field(default=None,ge=1,le=10000)
        desired:str|None=Field(default=None,pattern='^(running|paused)$')
        config:dict[str,int|float]|None=Field(default=None,max_length=30)
        market_ticker:str|None=Field(default=None,pattern='^[A-Za-z0-9][A-Za-z0-9.-]{0,127}$')
        market_desired:str|None=Field(default=None,pattern='^(running|paused)$')
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
            if p.get('retired') and body.desired=='running':raise HTTPException(409,'This 15-minute Favorites bot is retired; use its one-hour replacements')
            if p['revision']!=body.revision:raise HTTPException(409,'Bot changed elsewhere; reload first')
            if body.contracts is not None and body.contracts!=p['contracts']:
                put(c,'demo/shadow/version/'+identifier+'/'+str(p['revision']),{},p)
                p=dict(p,contracts=body.contracts,revision=p['revision']+1,changed_at=time.time())
            if body.config is not None:
                if p.get('strategy') not in ('market_maker','volatility_scalper'):raise HTTPException(422,'This strategy has no scalping configuration')
                allowed={'min_price':(.01,.99),'max_price':(.01,.99),'min_remaining':(21600,31536000),'max_sigma':(.001,.25),'min_spread':(.01,.25),'min_trades_24h':(1,100),'max_hold':(1,86400),'order_ttl':(1,3600),'reprice_ticks':(1,10),'reprice_seconds':(1,300),'min_net':(0,10),'depth_fraction':(.01,1),'market_exposure':(.001,1),'event_exposure':(.001,1),'category_exposure':(.001,1),'portfolio_exposure':(.001,1),'reduce_hold':(1,86400),'restrict_entries':(1,604800),'liquidate':(1,86400),'pre_event':(0,86400),'post_event':(0,86400)}
                if any(k not in allowed or isinstance(v,bool) or not math.isfinite(v) or not allowed[k][0]<=v<=allowed[k][1] for k,v in body.config.items()):raise HTTPException(422,'Invalid experimental parameter')
                put(c,'demo/shadow/version/'+identifier+'/'+str(p['revision']),{},p)
                p=dict(p,config=dict(p.get('config',{}),**body.config),revision=p['revision']+1,changed_at=time.time())
            if (body.market_ticker is None)!=(body.market_desired is None):raise HTTPException(422,'Market and requested state are both required')
            if body.market_ticker is not None:
                if p.get('strategy')!='market_maker':raise HTTPException(422,'Per-market control is only available for Market Maker')
                if body.market_desired=='running':
                    try:require_demo(c)
                    except ModeConflict as exc:raise HTTPException(409,str(exc)) from None
                paused=set(p.get('paused_markets',[]))
                if body.market_desired=='paused':paused.add(body.market_ticker)
                else:paused.discard(body.market_ticker)
                if len(paused)>100:raise HTTPException(422,'Too many market overrides')
                p=dict(p,paused_markets=sorted(paused))
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
        category:str|None=Field(default=None,pattern='^(politics|economics|sports_futures|entertainment)$')
        folder_id:str|None=Field(default=None,pattern='^(convexity|complete_set|sequential|sequential_flexible|sequential_adaptive|favorites|favorites_statistics|volatility_scalper|scalper_fixed|scalper_grid|scalper_momentum|scalper_dislocation|market_maker|maker_competitive|volatility_all)$')
    @app.post('/demo/shadow/bulk')
    def bulk(body:Bulk,request:Request):
        mutate(request);query(request)
        with pool.connection() as c:
            if body.action=='resume':
                try:require_demo(c)
                except ModeConflict as exc:raise HTTPException(409,str(exc)) from None
            if body.category and body.folder_id not in MM_FOLDERS:raise HTTPException(422,'Choose a Market Maker strategy for category controls')
            desired='paused' if body.action=='pause' else 'running'
            family=body.folder_id=='volatility_all'
            folder=None if family else body.folder_id
            c.execute("UPDATE research_job SET progress=jsonb_set(progress,'{desired}',to_jsonb(%s::text)) WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz' AND starts_with(idempotency_key,'demo/shadow/bot/') AND (%s::text IS NULL OR coalesce(parameters->>'folder_id','convexity')=%s) AND (%s IS NOT TRUE OR parameters->>'folder_id' IN ('volatility_scalper','scalper_fixed','scalper_grid','scalper_momentum','scalper_dislocation')) AND (%s='paused' OR parameters->>'retired' IS DISTINCT FROM 'true') AND (%s::text IS NULL OR parameters->>'market_category'=%s)",(desired,folder,folder,family,desired,body.category,body.category))
        return dict(contract='demo-v1',saved=True,real_orders_enabled=False)

    class Reset(BaseModel):
        model_config=ConfigDict(extra='forbid',strict=True)
        request_id:str=Field(min_length=16,max_length=80,pattern='^[A-Za-z0-9-]+$')
    @app.post('/demo/shadow/folders/{folder}/reset')
    def reset_folder(folder:str,body:Reset,request:Request):
        mutate(request);query(request)
        if folder not in ('convexity','complete_set','favorites','favorites_statistics',*SEQUENTIAL_FOLDERS,*SCALPER_FOLDERS,*MM_FOLDERS) or not store.get('shadow/folder/'+folder):
            raise HTTPException(404,'Bot folder not found')
        with pool.connection() as c:
            key='demo/shadow/command/'+body.request_id
            previous=c.execute('SELECT parameters FROM research_job WHERE idempotency_key=%s FOR UPDATE',(key,)).fetchone()
            command=dict(action='reset',folder_id=folder)
            if previous and previous['parameters']!=command:raise HTTPException(409,'Request ID already used')
            if not previous:
                from psycopg.types.json import Jsonb
                c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                    VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())
                    ON CONFLICT(idempotency_key) DO NOTHING""",(uuid4(),Jsonb(command),Jsonb(dict(done=False)),key))
                existing=c.execute('SELECT parameters FROM research_job WHERE idempotency_key=%s',(key,)).fetchone()
                if existing['parameters']!=command:raise HTTPException(409,'Request ID already used')
        return dict(contract='demo-v1',queued=True,real_orders_enabled=False)

    @app.get('/demo/shadow/sessions')
    def sessions(request:Request):
        auth(request);query(request)
        rows=store.rows('shadow/session/',100)
        return dict(contract='demo-v1',items=[dict(r['parameters'],key=r['id']) for r in rows],real_orders_enabled=False)

    @app.get('/demo/shadow/sessions/{identifier}')
    def session(identifier:str,request:Request):
        auth(request);query(request)
        from uuid import UUID
        try:UUID(identifier)
        except ValueError:raise HTTPException(422,'Invalid session') from None
        with pool.connection() as c:
            row=c.execute("SELECT progress FROM research_job WHERE id=%s AND idempotency_key>='demo/shadow/session/' AND idempotency_key<'demo/shadow/session/zzzz'",(identifier,)).fetchone()
        if not row:raise HTTPException(404,'Session not found')
        return dict(contract='demo-v1',session=row['progress'],real_orders_enabled=False)

    # Metadata listing stays PostgreSQL-only; full restored events require
    # separate read-only Cloudflare R2 credentials and explicit API opt-in.
    @app.get('/demo/shadow/archives')
    def archives(request:Request):
        from services.demo.shadow_archive_reader import list_manifests
        auth(request);query(request,('limit','cursor'))
        raw=request.query_params.get('limit','10')
        if not raw.isascii() or not raw.isdecimal():
            raise HTTPException(422,'Invalid archive page limit')
        try:
            return list_manifests(pool,limit=int(raw),cursor=request.query_params.get('cursor'))
        except ValueError:
            raise HTTPException(422,'Invalid archive pagination') from None

    @app.get('/demo/shadow/archives/{identifier}')
    def archive_events(identifier:str,request:Request):
        from services.demo.shadow_archive_reader import (
            ArchiveReaderUnavailable,read_manifest_events
        )
        auth(request);query(request,('limit','offset'))
        raw_limit=request.query_params.get('limit','25')
        raw_offset=request.query_params.get('offset','0')
        if not (raw_limit.isascii() and raw_limit.isdecimal()
                and raw_offset.isascii() and raw_offset.isdecimal()):
            raise HTTPException(422,'Invalid archive event pagination')
        try:
            result=read_manifest_events(pool,identifier,
                limit=int(raw_limit),offset=int(raw_offset))
        except ValueError:
            raise HTTPException(422,'Invalid archive request') from None
        except ArchiveReaderUnavailable:
            raise HTTPException(503,'Cold history reader is not yet configured') from None
        except Exception as error:
            print(json.dumps(dict(event='cold_archive_verify_failed',
                error_type=type(error).__name__)),flush=True)
            raise HTTPException(503,'Archived history could not be verified') from None
        if result is None:raise HTTPException(404,'Archive manifest not found')
        return result

    @app.get('/demo/shadow/history/reclaimed/{identifier}')
    def reclaimed_history_page(identifier:str,request:Request):
        # This endpoint is deliberately source-specific, not an all-time
        # merged view. The existing R2 reader remains separately opt-in.
        from services.demo.shadow_archive_reader import (
            ArchiveReaderUnavailable, read_manifest_events
        )
        from services.demo.shadow_reclaimed_history import normalize_reclaimed_manifest_page
        auth(request);query(request,('limit','offset'))
        limit_string=request.query_params.get('limit','25')
        offset_string=request.query_params.get('offset','0')
        if not (limit_string.isascii() and limit_string.isdecimal()
                and offset_string.isascii() and offset_string.isdecimal()):
            raise HTTPException(422,'Invalid reclaimed pagination')
        from uuid import UUID
        try:
            if str(UUID(identifier))!=identifier:
                raise ValueError('Noncanonical id')
        except ValueError:
            raise HTTPException(422,'Invalid archive manifest identifier') from None
        limit,offset=int(limit_string),int(offset_string)
        if not (1 <= limit <= 50 and 0 <= offset <= 10000):
            raise HTTPException(422,'Invalid reclaimed pagination')
        try:
            result=read_manifest_events(pool,identifier,offset=offset,limit=limit)
            if result is None:raise HTTPException(404,'Archive manifest not found')
            normalized=normalize_reclaimed_manifest_page(result,offset=offset)
            if normalized['manifest_id']!=identifier:
                raise ValueError('Requested manifest differs from verified receipt')
            return normalized
        except HTTPException:
            raise
        except ArchiveReaderUnavailable:
            raise HTTPException(503,'Cold history reader is not yet configured') from None
        except Exception as error:
            print(json.dumps(dict(event='reclaimed_archive_page_unavailable',
                                  error_type=type(error).__name__)),flush=True)
            raise HTTPException(503,'Archived history could not be verified') from None

    @app.get('/demo/shadow/events')
    def events(request:Request):
        auth(request);query(request)
        with pool.connection() as c:
            rows=c.execute("SELECT id::text,idempotency_key,parameters,progress,created_at FROM research_job WHERE idempotency_key>='demo/shadow/event/' AND idempotency_key<'demo/shadow/event/zzzz' ORDER BY created_at DESC,id DESC LIMIT 100").fetchall()
            batches=c.execute("SELECT progress,created_at FROM research_job WHERE idempotency_key>='demo/shadow/event-batch/' AND idempotency_key<'demo/shadow/event-batch/zzzz' ORDER BY created_at DESC,id DESC LIMIT 100").fetchall()
        # An archive pointer is not a decision or an outcome. Resolve it via
        # verified R2 read-only receipts before showing recent history; fail
        # closed, never silently truncate archived Favorites learning evidence.
        from services.demo.shadow_pointer_history import rehydrate_event_rows
        from services.demo.shadow_archive_reader import ArchiveReaderUnavailable
        try:
            rows,cold_rows,verified_objects=rehydrate_event_rows(rows)
            items=merge_recent_events(rows,batches)
        except ArchiveReaderUnavailable:
            raise HTTPException(503,'Archived diagnostic history is not yet readable') from None
        except Exception as error:
            print(json.dumps(dict(event='shadow_pointer_history_unavailable',
                                  error_type=type(error).__name__)),flush=True)
            raise HTTPException(503,'Archived diagnostic history could not be verified') from None
        return dict(contract='demo-v1',items=items,real_orders_enabled=False,
                    recent_history_complete=True,
                    archived_rows_rehydrated=cold_rows,
                    archive_objects_verified=verified_objects)
    
    @app.get('/demo/shadow/history/{source}')
    def historical_event_page(source:str,request:Request):
        # Explicit source selector and indexed cursor, never a full-table scan
        # or an unbounded cold R2 listing. All-time archive manifest histories
        # are intentionally NOT included in this source-specific endpoint.
        auth(request);query(request,('cursor',))
        from services.demo.shadow_history_pages import (
            page_history,validate_cursor
        )
        from services.demo.shadow_archive_reader import ArchiveReaderUnavailable
        cursor=request.query_params.get('cursor')
        try:
            validate_cursor(source,cursor)
        except ValueError:
            raise HTTPException(422,'Invalid history source or cursor') from None
        try:
            return page_history(pool,source,cursor=cursor)
        except ArchiveReaderUnavailable:
            raise HTTPException(503,'Archived diagnostic history is not yet readable') from None
        except Exception as error:
            print(json.dumps(dict(event='shadow_paginated_history_unavailable',
                                  error_type=type(error).__name__)),flush=True)
            raise HTTPException(503,'Diagnostic history could not be verified') from None
