"""Owner-only controls for forward-running, simulated paper accounts."""
import json,time
from uuid import UUID,uuid4
from typing import Literal
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb
from services.research.reports import SERIES
from services.paper.live import Ledger,initial,public_state
from services.paper.live_store import save


class StartLive(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(default='Live paper account',min_length=1,max_length=80)
    strategy_ids:list[UUID]=Field(min_length=1,max_length=20)
    starting_cash_cents:int=Field(default=10000,strict=True,ge=100,le=100000000)
    fill_model:Literal['estimated','conservative','all_filled']='conservative'
    request_key:UUID


def install_live_paper(app,auth,mutate,pool):
    def envelope(**data):return dict(contract='paper-v1',live_trading_enabled=False,live_paper_enabled=True,**data)
    def no_query(request):
        if request.query_params:raise HTTPException(422,'Query parameters are not accepted')
    def session(c,identifier,lock=False):
        row=c.execute("SELECT * FROM research_job WHERE id=%s AND idempotency_key>='paper-live/' AND idempotency_key<'paper-live/zzzz'"+(' FOR UPDATE' if lock else ''),(identifier,)).fetchone()
        if row is None:raise HTTPException(404,'Live paper session not found')
        return row
    def visible(row):
        state=row['progress'].get('state',{})
        snapshot=public_state(state)
        snapshot['worker_updated_at']=row['lease_expires_at'].timestamp()-30 if row['lease_expires_at'] else None
        return dict(id=str(row['id']),status=row['status'],name=row['parameters']['name'],
            created_at=row['created_at'],started_at=row['started_at'],finished_at=row['finished_at'],
            configuration=row['parameters'],state=snapshot,watched_markets=len(state.get('markets',{})))

    @app.get('/paper/live')
    def workspace(request:Request):
        auth(request);no_query(request)
        with pool.connection() as c:
            rows=c.execute("SELECT * FROM research_job WHERE idempotency_key>='paper-live/' AND idempotency_key<'paper-live/zzzz' ORDER BY created_at DESC LIMIT 10").fetchall()
            strategies=c.execute("SELECT id::text,parameters->'strategy' AS strategy FROM research_job WHERE idempotency_key>='paper-strategy/' AND idempotency_key<'paper-strategy/zzzz' AND parameters->'strategy'->>'bid_offset' IS NULL ORDER BY created_at DESC LIMIT 50").fetchall()
            health=c.execute("SELECT progress FROM research_job WHERE idempotency_key='paper-live-health'").fetchone()
        # List cards are deliberately small; expanded detail loads one account.
        sessions=[]
        for row in rows:
            view=visible(row);view['strategy_names']=[s['name'] for s in view.pop('configuration')['strategies']];view['state']={k:v for k,v in view['state'].items() if k not in ('orders','positions','recent')}
            sessions.append(view)
        return envelope(sessions=sessions,strategies=strategies,worker=health['progress'] if health else None,
            limits=dict(active_accounts=1,watched_markets=100,open_orders=100,positions=200,strategies=20),
            assumptions='Paper only. No real orders. Results before fees. Streaming fills are estimates; disconnections are not backfilled with invented fills.')

    @app.post('/paper/live')
    def start(body:StartLive,request:Request):
        mutate(request);no_query(request)
        if len(set(body.strategy_ids))!=len(body.strategy_ids):raise HTTPException(422,'Duplicate strategy')
        with pool.connection() as c:
            # Serialize starts without introducing a new table or lock service.
            c.execute("SELECT pg_advisory_xact_lock(784241901)")
            existing=c.execute('SELECT * FROM research_job WHERE idempotency_key=%s',('paper-live/'+str(body.request_key),)).fetchone()
            if existing:
                supplied=body.model_dump(mode='json');supplied['strategy_ids']=sorted(supplied['strategy_ids'])
                if existing['parameters'].get('request')!=supplied:raise HTTPException(409,'Request key has different settings')
                return envelope(id=str(existing['id']),status=existing['status'])
            active=c.execute("SELECT 1 FROM research_job WHERE idempotency_key>='paper-live/' AND idempotency_key<'paper-live/zzzz' AND status IN ('queued','running') LIMIT 1").fetchone()
            if active:raise HTTPException(409,'A live paper account is already active')
            rows=c.execute("SELECT parameters->'strategy' AS strategy FROM research_job WHERE id=ANY(%s::uuid[]) AND idempotency_key>='paper-strategy/' AND idempotency_key<'paper-strategy/zzzz' ORDER BY id",(body.strategy_ids,)).fetchall()
            if len(rows)!=len(body.strategy_ids) or any(r['strategy'].get('bid_offset') is not None for r in rows):raise HTTPException(422,'Choose saved table-based strategies')
            strategies=[]
            for row in rows:
                s=dict(row['strategy']);s['series']=sorted(SERIES[s['asset']]);strategies.append(s)
            supplied=body.model_dump(mode='json');supplied['strategy_ids']=sorted(supplied['strategy_ids'])
            parameters=dict(collector='paper-live-v1',name=body.name.strip(),strategies=strategies,
                starting_cash_cents=body.starting_cash_cents,fill_model=body.fill_model,request=supplied)
            if len(json.dumps(parameters).encode())>16384:raise HTTPException(422,'Selected strategy configuration is too large')
            identifier=uuid4()
            c.execute("INSERT INTO research_job(id,asset,parameters,idempotency_key,progress) VALUES(%s,'crypto',%s,%s,%s)",
                (identifier,Jsonb(parameters),'paper-live/'+str(body.request_key),Jsonb(dict(state=initial(body.starting_cash_cents)))))
        return envelope(id=str(identifier),status='queued')

    @app.get('/paper/live/{identifier}')
    def detail(identifier:UUID,request:Request):
        auth(request);no_query(request)
        with pool.connection() as c:row=session(c,identifier)
        return envelope(session=visible(row))

    @app.post('/paper/live/{identifier}/stop')
    def stop(identifier:UUID,request:Request):
        mutate(request);no_query(request)
        with pool.connection() as c:
            row=session(c,identifier,True)
            if row['status'] in ('queued','running'):
                ledger=Ledger(row['progress']['state'],row['parameters']['strategies'],row['parameters']['fill_model'])
                if not ledger.s['stopping']:
                    ledger.stop(time.time());save(c,row,ledger,time.time())
        return envelope(id=str(identifier),message='New bids stopped. Unfilled bids canceled. Existing positions continue through settlement.')

    @app.get('/paper/live/{identifier}/events')
    def events(identifier:UUID,request:Request):
        auth(request)
        entries=list(request.query_params.multi_items())
        if entries and (len(entries)!=1 or entries[0][0]!='before' or not entries[0][1].isascii() or not entries[0][1].isdigit() or not 1<=len(entries[0][1])<=12):raise HTTPException(422,'Invalid event cursor')
        before=int(request.query_params.get('before','999999999999'))
        with pool.connection() as c:
            session(c,identifier)
            rows=c.execute("SELECT parameters->'event' AS event FROM research_job WHERE idempotency_key>=%s AND idempotency_key<%s ORDER BY idempotency_key DESC LIMIT 50",(f'paper-live-event/{identifier}/',f'paper-live-event/{identifier}/{before:012d}')).fetchall()
        return envelope(events=[r['event'] for r in rows],next_before=rows[-1]['event']['sequence'] if len(rows)==50 else None)
