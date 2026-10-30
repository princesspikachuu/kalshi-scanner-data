"""Owner-only paper replay controls, with immutable strategy snapshots."""
from uuid import UUID,uuid4
from datetime import date,timedelta
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from services.paper.rules import entry_rules
from psycopg.types.json import Jsonb
from services.research.reports import MINUTES,SERIES


class SquareRule(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    report_id:int=Field(ge=1)
    entry_minute_min:int=Field(ge=0,le=359)
    entry_minute_max:int=Field(ge=1,le=360)
    min_price:int=Field(ge=50,le=99)
    max_price:int=Field(ge=50,le=99)


class Strategy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=80)
    asset:str
    rules:list[SquareRule]|None=Field(default=None,max_length=30)
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
    @app.get('/paper/datasets')
    def list_datasets(request:Request):
        """Find the newest usable saved version per UTC date and category.

        The workspace's 800-item preview must not limit historical range searches.
        This only lists existing immutable datasets; missing dates are not invented.
        """
        auth(request)
        query=request.query_params
        if set(query.keys())!={'start','end','mode','asset'} or any(len(query.getlist(k))!=1 for k in query):
            raise HTTPException(422,'Choose an explicit date range, category and fill model')
        try:
            begin=date.fromisoformat(query['start'])
            end=date.fromisoformat(query['end'])
        except (ValueError,TypeError):
            raise HTTPException(422,'Use ISO dates') from None
        if begin.isoformat()!=query['start'] or end.isoformat()!=query['end'] or end<begin or end-begin>timedelta(days=365):
            raise HTTPException(422,'Choose up to 366 consecutive UTC dates')
        mode=query['mode']
        asset=query['asset']
        if mode not in ('all_filled','estimated','conservative') or asset not in ('all',*SERIES.keys()):
            raise HTTPException(422,'Invalid model or category')
        with pool.connection() as c:
            rows=c.execute("""SELECT DISTINCT ON (ds.day,coalesce(r.asset,substring(ds.stream_key from 10)))
                    ds.id,ds.day,s.summary->>'candidate_count' AS markets,
                    (s.summary->'resources' ? 'trades') AS has_trade_evidence,
                    coalesce(r.asset,substring(ds.stream_key from 10)) AS asset
                FROM research_dataset ds
                JOIN research_summary s ON s.dataset_id=ds.id
                LEFT JOIN research_campaign r ON ds.stream_key='campaign-'||replace(r.id::text,'-','')
                WHERE ds.day BETWEEN %s AND %s
                    AND (r.id IS NOT NULL OR ds.stream_key IN
                        ('analysis-btc','analysis-eth','analysis-crypto','analysis-weather','analysis-weather_daily','analysis-sports'))
                    AND s.summary->'resources' ? 'candles'
                    AND (%s='all_filled' OR s.summary->'resources' ? 'trades')
                    AND (%s='all' OR coalesce(r.asset,substring(ds.stream_key from 10))=%s)
                    AND coalesce((s.summary->>'candidate_count')::integer,0)>0
                ORDER BY ds.day,coalesce(r.asset,substring(ds.stream_key from 10)),ds.id DESC""",
                (begin,end,mode,asset,asset)).fetchall()
        datasets=sorted(rows,key=lambda d:(d['day'],d['asset']),reverse=True)
        return dict(contract='paper-v1',live_trading_enabled=False,datasets=datasets,
            days_requested=(end-begin).days+1,days_available=len({r['day'] for r in rows}),
            start=begin.isoformat(),end=end.isoformat(),asset=asset,mode=mode)

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
            rules=body.rules or [SquareRule(report_id=body.report_id,entry_minute_min=body.entry_minute_min,
                entry_minute_max=body.entry_minute_max,min_price=body.min_price,max_price=body.max_price)]
            if not rules or len({(r.report_id,r.entry_minute_min,r.entry_minute_max,r.min_price,r.max_price) for r in rules})!=len(rules):
                raise HTTPException(422,'Duplicate or missing squares')
            if any(r.min_price>r.max_price or r.entry_minute_max not in MINUTES[body.asset] or
                   r.entry_minute_min!=max((m for m in MINUTES[body.asset] if m<r.entry_minute_max),default=0)
                   for r in rules):
                raise HTTPException(422,'Invalid price range or time window')
            ids=sorted({r.report_id for r in rules})
            with pool.connection() as c:
                saved_rows=c.execute('SELECT id,asset,report FROM research_result WHERE id=ANY(%s::bigint[])',(ids,)).fetchall()
            saved={row['id']:row for row in saved_rows}
            if len(saved)!=len(ids) or any(row['asset']!=body.asset for row in saved.values()):
                raise HTTPException(422,'Saved statistics not found')
            compiled=[]
            for rule in rules:
                band=f'{rule.min_price:02d}-{rule.max_price+1:02d}'
                report=saved[rule.report_id]['report']
                cell=next((cell for cell in report['historical']['cells'] if
                    cell['hold']['minutes_before_close']==rule.entry_minute_max and
                    cell['hold']['price_band_cents']==band),None)
                if not cell or not cell['hold']['sampled_markets']:
                    raise HTTPException(422,'Invalid statistics square')
                compiled.append(dict(**rule.model_dump(),
                    statistical_yield_percent=cell['hold']['hypothetical_roi_percent'],
                    sampled_markets=cell['hold']['sampled_markets']))
            snapshot['rules']=compiled
            snapshot['statistical_yield_percent']=max(r['statistical_yield_percent'] for r in compiled)
            snapshot['sampled_markets']=sum(r['sampled_markets'] for r in compiled)
            snapshot['statistics_basis']='Maximum saved reference BID-grid ROI is priority only; independent squares may overlap'
            snapshot['report_id']=compiled[0]['report_id']
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
