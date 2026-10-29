"""Owner-only paper replay controls, with immutable strategy snapshots."""
from uuid import UUID,uuid4
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb
from services.research.reports import MINUTES,SERIES


class Strategy(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(min_length=1,max_length=80)
    asset:str
    minutes:list[int]=Field(min_length=1,max_length=20)
    min_price:int=Field(ge=50,le=99)
    max_price:int=Field(ge=50,le=99)
    bid_offset:int=Field(ge=-2,le=1)
    contracts:int=Field(ge=1,le=100)
    starting_cash_cents:int=Field(ge=100,le=100000000)

class ReplayBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    strategy_id:UUID
    dataset_id:int=Field(strict=True,ge=1)
    request_key:UUID


def install_paper(app,auth,mutate,pool):
    def no_query(request):
        if request.query_params:raise HTTPException(422,'Query parameters are not accepted')
    @app.get('/paper/workspace')
    def workspace(request:Request):
        auth(request);no_query(request)
        with pool.connection() as c:
            strategies=c.execute("SELECT id::text,asset,parameters->'strategy' AS strategy FROM research_job WHERE idempotency_key>='paper-strategy/' AND idempotency_key<'paper-strategy0' ORDER BY created_at DESC LIMIT 50").fetchall()
            runs=c.execute("SELECT id::text,asset,status,error_code,parameters->>'dataset_id' AS dataset_id,(progress->'result')-'trades' AS result FROM research_job WHERE idempotency_key>='paper-replay/' AND idempotency_key<'paper-replay0' ORDER BY created_at DESC LIMIT 20").fetchall()
            datasets=c.execute("""SELECT ds.id,ds.day,s.summary->>'candidate_count' AS markets,
                coalesce(r.asset,substring(ds.stream_key from 10)) AS asset FROM research_dataset ds
                JOIN research_summary s ON s.dataset_id=ds.id
                LEFT JOIN research_campaign r ON ds.stream_key='campaign-'||replace(r.id::text,'-','')
                WHERE (r.id IS NOT NULL OR ds.stream_key IN ('analysis-btc','analysis-eth','analysis-crypto','analysis-weather','analysis-weather_daily','analysis-sports'))
                AND s.summary->'resources' ? 'trades' ORDER BY ds.id DESC LIMIT 100""").fetchall()
        return dict(contract='paper-v1',live_trading_enabled=False,strategies=strategies,runs=runs,datasets=datasets,entry_minutes=MINUTES)
    @app.post('/paper/strategies')
    def create(body:Strategy,request:Request):
        mutate(request);no_query(request)
        if body.asset not in SERIES or body.min_price>body.max_price or len(set(body.minutes))!=len(body.minutes) or not set(body.minutes).issubset(MINUTES[body.asset]):raise HTTPException(422,'Invalid strategy')
        identifier=uuid4()
        with pool.connection() as c:
            c.execute("""INSERT INTO research_job(id,asset,parameters,idempotency_key,status,finished_at)
                VALUES(%s,%s,%s,%s,'succeeded',clock_timestamp())""",(identifier,body.asset,Jsonb(dict(collector='paper-strategy-v1',strategy=body.model_dump())),'paper-strategy/'+str(identifier)))
        return dict(contract='paper-v1',id=str(identifier),live_trading_enabled=False)
    @app.post('/paper/replays')
    def start(body:ReplayBody,request:Request):
        mutate(request);no_query(request)
        with pool.connection() as c:
            strategy=c.execute("SELECT parameters->'strategy' AS strategy,asset FROM research_job WHERE id=%s AND idempotency_key=%s",(body.strategy_id,'paper-strategy/'+str(body.strategy_id))).fetchone()
            source=c.execute("""SELECT ds.stream_key,s.summary FROM research_dataset ds JOIN research_summary s ON s.dataset_id=ds.id
                WHERE ds.id=%s""",(body.dataset_id,)).fetchone()
            if not strategy or not source or 'trades' not in source['summary'].get('resources',[]):raise HTTPException(422,'Choose saved trade evidence and a strategy')
            if source['stream_key']!='analysis-'+strategy['asset']:
                linked=c.execute("SELECT 1 FROM research_campaign WHERE asset=%s AND 'campaign-'||replace(id::text,'-','')=%s",(strategy['asset'],source['stream_key'])).fetchone()
                if not linked:raise HTTPException(422,'Dataset category does not match strategy')
        from services.research.queue import ResearchQueue,EvidenceConflict
        try:job=ResearchQueue(pool).enqueue(strategy['asset'],dict(collector='paper-replay-v1',dataset_id=body.dataset_id,strategy=strategy['strategy']),
            'paper-replay/'+str(body.request_key))
        except EvidenceConflict:raise HTTPException(409,'Request key already used') from None
        return dict(contract='paper-v1',id=str(job['id']),live_trading_enabled=False)
