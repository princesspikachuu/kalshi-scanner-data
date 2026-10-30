"""Owner-only paper replay controls, with immutable strategy snapshots."""
from uuid import UUID,uuid4
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from psycopg.types.json import Jsonb
from services.research.reports import MINUTES,SERIES


class Strategy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=80)
    asset:str
    minutes:list[int]=Field(min_length=1,max_length=20)
    min_price:int=Field(ge=50,le=99)
    max_price:int=Field(ge=50,le=99)
    bid_offset:int|None=Field(default=None,ge=-2,le=1) # Existing immutable v1 strategies only.
    report_id:int|None=Field(default=None,ge=1)
    entry_minute_min:int=Field(default=0,ge=0,le=359)
    entry_minute_max:int=Field(default=1,ge=1,le=360)
    # Existing snapshots use below_ask_cents and do not contain the new fields.
    below_ask_cents:int=Field(default=1,ge=1,le=99)
    bid_reference:Literal['ask','best_bid']='ask'
    bid_adjustment_cents:int|None=Field(default=None,ge=-99,le=99)
    maximum_bid_cents:int|None=Field(default=None,ge=1,le=99)
    balance_percent:int=Field(default=10,ge=1,le=10)
    loss_trigger_cents:int|None=Field(default=None,ge=0,le=99)
    contracts:int=Field(ge=1,le=100)
    starting_cash_cents:int=Field(ge=100,le=100000000)

class ReplayBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    strategy_id:UUID|None=None
    dataset_id:int|None=Field(default=None,strict=True,ge=1)
    strategy_ids:list[UUID]=Field(default_factory=list,max_length=50)
    dataset_ids:list[int]=Field(default_factory=list,max_length=24)
    starting_cash_cents:int=Field(default=10000,strict=True,ge=100,le=100000000)
    fill_model:Literal['estimated','conservative','all_filled']='estimated'
    request_key:UUID
    name:str=Field(default='',max_length=80)


def install_paper(app,auth,mutate,pool):
    from .paper_live import install_live_paper
    install_live_paper(app,auth,mutate,pool)
    def no_query(request):
        if request.query_params:raise HTTPException(422,'Query parameters are not accepted')
    @app.get('/paper/workspace')
    def workspace(request:Request):
        auth(request);no_query(request)
        with pool.connection() as c:
            strategies=c.execute("SELECT id::text,asset,parameters->'strategy' AS strategy FROM research_job WHERE idempotency_key>='paper-strategy/' AND idempotency_key<'paper-strategy/zzzz' ORDER BY created_at DESC LIMIT 50").fetchall()
            runs=c.execute("SELECT id::text,parameters->>'name' AS name,asset,status,error_code,created_at,started_at,finished_at,coalesce(lease_expires_at>clock_timestamp(),false) AS lease_active,CASE WHEN status IN ('queued','running','cancelled') THEN progress->'activity' ELSE (progress->'activity')-'recent_activity'-'open_orders' END AS activity,parameters->'dataset_ids' AS dataset_ids,parameters->>'dataset_id' AS dataset_id,jsonb_path_query_array(parameters,'$.strategies[*].name') AS strategy_names,(progress->'result')-'trades' AS result FROM research_job WHERE idempotency_key>='paper-replay/' AND idempotency_key<'paper-replay/zzzz' ORDER BY created_at DESC LIMIT 20").fetchall()
            datasets=c.execute("""SELECT ds.id,ds.day,s.summary->>'candidate_count' AS markets,
                (s.summary->'resources' ? 'trades') AS has_trade_evidence,
                coalesce(r.asset,substring(ds.stream_key from 10)) AS asset FROM research_dataset ds
                JOIN research_summary s ON s.dataset_id=ds.id
                LEFT JOIN research_campaign r ON ds.stream_key='campaign-'||replace(r.id::text,'-','')
                WHERE (r.id IS NOT NULL OR ds.stream_key IN ('analysis-btc','analysis-eth','analysis-crypto','analysis-weather','analysis-weather_daily','analysis-sports'))
                AND s.summary->'resources' ? 'candles' AND coalesce((s.summary->>'candidate_count')::integer,0)>0 ORDER BY ds.day DESC,ds.id DESC LIMIT 800""").fetchall()
        return dict(contract='paper-v1',live_trading_enabled=False,strategies=strategies,runs=runs,datasets=datasets,entry_minutes=MINUTES)
    @app.post('/paper/strategies')
    def create(body:Strategy,request:Request):
        mutate(request);no_query(request)
        if body.asset not in SERIES or body.min_price>body.max_price or len(set(body.minutes))!=len(body.minutes) or not set(body.minutes).issubset(MINUTES[body.asset]):raise HTTPException(422,'Invalid strategy')
        # A resting maker bid must be strictly below the observed ask.
        # Best-bid modes may improve the bid but runtime checks prevent
        # accidental taker or crossed orders at each snapshot.
        if body.bid_reference=='ask' and body.bid_adjustment_cents is not None and body.bid_adjustment_cents>=0:
            raise HTTPException(422,'Ask-based maker bids must be below the ask')
        if body.bid_reference=='best_bid' and body.bid_adjustment_cents is None:
            raise HTTPException(422,'Best-bid adjustment is required')
        identifier=uuid4();snapshot=body.model_dump()
        if body.bid_offset is None:
            if body.report_id is None or body.entry_minute_max not in body.minutes or body.minutes!=[body.entry_minute_max]:raise HTTPException(422,'Select a saved statistics square')
            with pool.connection() as c:
                saved=c.execute('SELECT asset,report FROM research_result WHERE id=%s',(body.report_id,)).fetchone()
            if not saved or saved['asset']!=body.asset:raise HTTPException(422,'Saved statistics not found')
            band=f'{body.min_price:02d}-{body.max_price+1:02d}'
            cell=next((cell for cell in saved['report']['historical']['cells'] if cell['hold']['minutes_before_close']==body.entry_minute_max and cell['hold']['price_band_cents']==band),None)
            lower=max((m for m in MINUTES[body.asset] if m<body.entry_minute_max),default=0)
            if not cell or body.entry_minute_min!=lower or not cell['hold']['sampled_markets']:raise HTTPException(422,'Invalid statistics square or time window')
            snapshot['statistical_yield_percent']=cell['hold']['hypothetical_roi_percent']
            snapshot['sampled_markets']=cell['hold']['sampled_markets']
            snapshot['statistics_basis']='Saved hold ROI; historical bid-band statistics, ask-band entry rule'
        with pool.connection() as c:
            c.execute("""INSERT INTO research_job(id,asset,parameters,idempotency_key,status,finished_at)
                VALUES(%s,%s,%s,%s,'succeeded',clock_timestamp())""",(identifier,body.asset,Jsonb(dict(collector='paper-strategy-v1',strategy=snapshot)),'paper-strategy/'+str(identifier)))
        return dict(contract='paper-v1',id=str(identifier),live_trading_enabled=False)
    @app.post('/paper/replays')
    def start(body:ReplayBody,request:Request):
        mutate(request);no_query(request)
        portfolio=bool(body.strategy_ids or body.dataset_ids)
        if portfolio:
            if body.strategy_id is not None or body.dataset_id is not None or not body.strategy_ids or not body.dataset_ids or any(type(d) is not int or d<1 for d in body.dataset_ids):raise HTTPException(422,'Select strategies and saved days')
            if len(set(body.strategy_ids))!=len(body.strategy_ids) or len(set(body.dataset_ids))!=len(body.dataset_ids):raise HTTPException(422,'Duplicate replay selection')
            with pool.connection() as c:
                rows=c.execute("SELECT parameters->'strategy' AS strategy FROM research_job WHERE id=ANY(%s::uuid[]) AND idempotency_key>='paper-strategy/' AND idempotency_key<'paper-strategy/zzzz' ORDER BY id",(body.strategy_ids,)).fetchall()
                datasets=c.execute("SELECT ds.id,s.summary FROM research_dataset ds JOIN research_summary s ON s.dataset_id=ds.id WHERE ds.id=ANY(%s::bigint[])",(body.dataset_ids,)).fetchall()
            if len(rows)!=len(body.strategy_ids) or any(r['strategy'].get('bid_offset') is not None for r in rows):raise HTTPException(422,'Select table-based strategies')
            required='candles' if body.fill_model=='all_filled' else 'trades'
            if len(datasets)!=len(body.dataset_ids) or any(required not in d['summary'].get('resources',[]) for d in datasets):raise HTTPException(422,'Selected days lack the required evidence for this fill model')
            parameters=dict(collector='paper-replay-v1',dataset_ids=sorted(body.dataset_ids),strategies=[r['strategy'] for r in rows],starting_cash_cents=body.starting_cash_cents,fill_model=body.fill_model)
            asset='crypto' # Operational queue label; strategies retain their own categories.
        else:
            if body.strategy_id is None or body.dataset_id is None:raise HTTPException(422,'Select strategies and saved days')
            with pool.connection() as c:
                strategy=c.execute("SELECT parameters->'strategy' AS strategy,asset FROM research_job WHERE id=%s AND idempotency_key=%s",(body.strategy_id,'paper-strategy/'+str(body.strategy_id))).fetchone()
                source=c.execute("SELECT ds.stream_key,s.summary FROM research_dataset ds JOIN research_summary s ON s.dataset_id=ds.id WHERE ds.id=%s",(body.dataset_id,)).fetchone()
                if not strategy or not source or 'trades' not in source['summary'].get('resources',[]):raise HTTPException(422,'Choose saved trade evidence and a strategy')
                if source['stream_key']!='analysis-'+strategy['asset']:
                    linked=c.execute("SELECT 1 FROM research_campaign WHERE asset=%s AND 'campaign-'||replace(id::text,'-','')=%s",(strategy['asset'],source['stream_key'])).fetchone()
                    if not linked:raise HTTPException(422,'Dataset category does not match strategy')
            asset=strategy['asset'];parameters=dict(collector='paper-replay-v1',dataset_id=body.dataset_id,strategy=strategy['strategy'])
            if strategy['strategy'].get('bid_offset') is None:
                parameters=dict(collector='paper-replay-v1',dataset_ids=[body.dataset_id],strategies=[strategy['strategy']],starting_cash_cents=body.starting_cash_cents,fill_model=body.fill_model)
        parameters['name']=body.name.strip()
        from services.research.queue import ResearchQueue,EvidenceConflict
        try:job=ResearchQueue(pool).enqueue(asset,parameters,'paper-replay/'+str(body.request_key))
        except EvidenceConflict:raise HTTPException(409,'Request key already used') from None
        return dict(contract='paper-v1',id=str(job['id']),live_trading_enabled=False)

    @app.get('/paper/replays/{identifier}')
    def detail(identifier:UUID,request:Request):
        auth(request);no_query(request)
        with pool.connection() as c:
            run=c.execute("SELECT id::text,status,created_at,started_at,finished_at,parameters AS configuration FROM research_job WHERE id=%s AND parameters->>'collector'='paper-replay-v1' AND idempotency_key>='paper-replay/' AND idempotency_key<'paper-replay/zzzz'",(identifier,)).fetchone()
            if not run:raise HTTPException(404,'Paper run not found')
            ids=run['configuration'].get('dataset_ids') or [run['configuration']['dataset_id']]
            run['source_days']=c.execute("SELECT ds.id,ds.day,coalesce(r.asset,substring(ds.stream_key from 10)) AS asset FROM research_dataset ds LEFT JOIN research_campaign r ON ds.stream_key='campaign-'||replace(r.id::text,'-','') WHERE ds.id=ANY(%s::bigint[]) ORDER BY ds.day,ds.id",(ids,)).fetchall()
        return dict(contract='paper-v1',live_trading_enabled=False,run=run)

    @app.post('/paper/replays/{identifier}/cancel')
    def cancel(identifier:UUID,request:Request):
        mutate(request);no_query(request)
        with pool.connection() as c:
            run=c.execute("SELECT status FROM research_job WHERE id=%s AND parameters->>'collector'='paper-replay-v1' AND idempotency_key>='paper-replay/' AND idempotency_key<'paper-replay/zzzz'",(identifier,)).fetchone()
            if not run:raise HTTPException(404,'Paper run not found')
        from services.research.queue import ResearchQueue
        ResearchQueue(pool).cancel(identifier)
        with pool.connection() as c:status=c.execute('SELECT status FROM research_job WHERE id=%s',(identifier,)).fetchone()['status']
        return dict(contract='paper-v1',live_trading_enabled=False,id=str(identifier),status=status)
