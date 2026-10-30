"""Owner-only Demo controls; browsers read durable snapshots, never poll Kalshi."""
import os,time
from uuid import UUID,uuid4
from fastapi import Request,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .demo_models import BotConfig,Controls,Policy
from services.demo.store import DemoStore

def install_demo(app,auth,mutate,pool):
    store=DemoStore(pool)
    def require_query(request,allowed=()):
        if any(k not in allowed or len(request.query_params.getlist(k))!=1 for k in request.query_params):raise HTTPException(422,'Invalid filters')
    def bot_get(identifier):
        row=store.get('bot/'+str(identifier))
        if not row:raise HTTPException(404,'Bot not found')
        return row
    def verify_config(config):
        config=config.model_dump();verified=[]
        with pool.connection() as c:
            for square in config['squares']:
                square['expected_roi']=None;square['loss_cents']=None
                if not square['report_id']:
                    if config['loss_mode']=='research':raise HTTPException(422,'Select saved research for recommended exits')
                    continue
                row=c.execute('SELECT asset,report FROM research_result WHERE id=%s',(square['report_id'],)).fetchone()
                if not row or row['asset']!=square['asset']:raise HTTPException(422,'Research source not found')
                band=f"{square['min_price']:02d}-{square['max_price']+1:02d}"
                cell=next((x for x in row['report']['historical']['cells'] if x['hold']['minutes_before_close']==square['max_minutes'] and x['hold']['price_band_cents']==band),None)
                from services.research.reports import MINUTES
                lower=max((m for m in MINUTES[square['asset']] if m<square['max_minutes']),default=0)
                if not cell or not cell['hold']['sampled_markets'] or square['min_minutes']!=lower:raise HTTPException(422,'Choose an available research square')
                square['expected_roi']=cell['hold']['hypothetical_roi_percent']
                loss=cell.get('loss_prevention') or cell.get('conditional_loss') or {}
                square['loss_cents']=loss.get('sell_threshold_cents') or loss.get('threshold_cents')
                if config['loss_mode']=='research' and not square['loss_cents']:raise HTTPException(422,'This square has no verified exit recommendation; choose manual or off')
        return config
    @app.get('/demo/workspace')
    def workspace(request:Request):
        auth(request);require_query(request,('period',))
        period=request.query_params.get('period','24H')
        if period not in ('24H','7D','30D'):raise HTTPException(422,'Invalid period')
        bots=[]
        for row in store.rows('bot/',101):
            data=row['parameters'];state=row['progress']
            bots.append(dict(id=row['id'],key=row['idempotency_key'].split('/')[-1],config=data['config'],revision=data['revision'],**state))
        health=store.get('health');account=store.get('account');policy=store.get('policy')
        alerts=[dict(key=r['idempotency_key'].split('/')[-1],**r['progress']) for r in store.rows('alert/',30) if r['progress'].get('active')]
        status=health['progress'] if health else dict(state='waiting',message='Trading worker has not checked in yet')
        if time.time()-status.get('at',0)>90:status=dict(status,state='waiting',message='Trading worker heartbeat is stale; entries require verified recovery')
        values=account['progress'] if account else None
        with pool.connection() as c:
            health_rows=c.execute("SELECT idempotency_key,progress FROM research_job WHERE idempotency_key=ANY(%s)",(['demo/storage-health','demo/backup-health','demo/email-health'],)).fetchall()
        hours={'24H':24,'7D':168,'30D':720}[period]
        with pool.connection() as c:
            first=c.execute("SELECT progress FROM research_job WHERE idempotency_key>='demo/equity/' AND idempotency_key<'demo/equity/zzzz' AND created_at>clock_timestamp()-%s*interval '1 hour' ORDER BY created_at LIMIT 1",(hours,)).fetchone()
            performance=c.execute("SELECT parameters->>'bot' AS bot,coalesce(sum((progress->>'realized_cents')::numeric),0) AS pnl,count(*) AS closed FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz' AND progress ? 'realized_cents' AND (progress->>'closed_at')::numeric>%s GROUP BY parameters->>'bot'",(time.time()-hours*3600,)).fetchall()
        metrics={r['bot']:dict(realized_cents=int(r['pnl']),closed=r['closed']) for r in performance}
        account_change=values['equity_cents']-first['progress']['value'] if values and first else None
        monitoring={r['idempotency_key'].split('/')[-1].split('-')[0]:r['progress'] for r in health_rows}
        return dict(contract='demo-v1',environment='demo',bots=bots[:100],capacity_reached=len(bots)>100,
            health=status,account=values,alerts=alerts,policy=policy['progress'] if policy else Policy().model_dump(),
            connection_configured=bool(store.get('credentials') or os.environ.get('KALSHI_DEMO_API_KEY_ID')),
            vault_ready=bool(os.environ.get('DEMO_VAULT_KEY')),monitoring=monitoring,metrics=metrics,account_change_cents=account_change,period=period)
    @app.post('/demo/bots')
    def create(body:BotConfig,request:Request):
        mutate(request);require_query(request)
        config=verify_config(body);identifier=str(uuid4())
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(723741930)')
            count=c.execute("SELECT count(*) AS n FROM research_job WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'").fetchone()['n']
            if count>=100:raise HTTPException(409,'Bot capacity reached')
            from psycopg.types.json import Jsonb
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                (identifier,Jsonb(dict(config=config,revision=1)),Jsonb(dict(desired='paused',state='paused',message='Ready to review and resume')),'demo/bot/'+identifier))
        store.event('bot_created',config['name']+' saved with '+str(len(config['squares']))+' conditions',bot=identifier)
        return dict(contract='demo-v1',id=identifier)
    @app.post('/demo/bots/{identifier}/configure')
    def configure(identifier:UUID,body:BotConfig,request:Request):
        mutate(request);require_query(request);config=verify_config(body)
        with pool.connection() as c:
            row=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('demo/bot/'+str(identifier),)).fetchone()
            if not row:raise HTTPException(404,'Bot not found')
            if row['progress'].get('desired')=='running':raise HTTPException(409,'Pause the bot before editing')
            if any(o['bot']==str(identifier) for o in store.active_orders()):raise HTTPException(409,'Wait for existing orders and positions to close before changing rules')
            from psycopg.types.json import Jsonb
            c.execute('UPDATE research_job SET parameters=%s WHERE idempotency_key=%s',(Jsonb(dict(config=config,revision=row['parameters']['revision']+1)),'demo/bot/'+str(identifier)))
        store.event('bot_updated',config['name']+' configuration updated',bot=str(identifier))
        return dict(contract='demo-v1',updated=True)
    @app.post('/demo/bots/{identifier}/control')
    def control(identifier:UUID,body:Controls,request:Request):
        mutate(request);require_query(request)
        with pool.connection() as c:
            row=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('demo/bot/'+str(identifier),)).fetchone()
            if not row:raise HTTPException(404,'Bot not found')
            if row['parameters']['revision']!=body.revision:raise HTTPException(409,'Bot changed; refresh before retrying')
            state=row['progress'];state['desired']='running' if body.action=='resume' else 'paused'
            state['archived']=body.action=='archive' if body.action in ('archive','restore') else state.get('archived',False)
            if body.action=='resume':state['archived']=False
            state['message']='Waiting for verified reconciliation' if body.action=='resume' else 'Entry cancellation requested; filled positions remain protected'
            from psycopg.types.json import Jsonb
            c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),'demo/bot/'+str(identifier)))
        store.event('bot_'+body.action,body.action.title()+' requested',bot=str(identifier))
        return dict(contract='demo-v1',accepted=True)
    class BulkItem(BaseModel):
        id:UUID
        revision:int=Field(ge=1)
    class BulkControl(BaseModel):
        model_config=ConfigDict(extra='forbid')
        action:str
        bots:list[BulkItem]=Field(min_length=1,max_length=100)
    @app.post('/demo/bulk')
    def bulk(body:BulkControl,request:Request):
        mutate(request);require_query(request)
        if body.action not in ('pause','resume') or len({b.id for b in body.bots})!=len(body.bots):raise HTTPException(422,'Invalid bulk control')
        keys=['demo/bot/'+str(b.id) for b in body.bots];expected={str(b.id):b.revision for b in body.bots}
        from psycopg.types.json import Jsonb
        with pool.connection() as c:
            rows=c.execute('SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key=ANY(%s) FOR UPDATE',(keys,)).fetchall()
            if len(rows)!=len(keys) or any(r['parameters']['revision']!=expected[r['idempotency_key'].split('/')[-1]] for r in rows):raise HTTPException(409,'Bots changed; refresh before retrying')
            for row in rows:
                state=dict(row['progress'],desired='running' if body.action=='resume' else 'paused')
                c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),row['idempotency_key']))
        store.event('bulk_'+body.action,f'{body.action.title()} requested for {len(rows)} bots')
        return dict(contract='demo-v1',accepted=True,count=len(rows))
    @app.get('/demo/activity')
    def activity(request:Request):
        auth(request);require_query(request,('before','bot','ticker','kind'))
        before=request.query_params.get('before');bot=request.query_params.get('bot');ticker=request.query_params.get('ticker');kind=request.query_params.get('kind')
        try:
            if before:UUID(before)
            if bot:UUID(bot)
        except ValueError:raise HTTPException(422,'Invalid identifier') from None
        if ticker and len(ticker)>256 or kind and len(kind)>40:raise HTTPException(422,'Invalid filter')
        with pool.connection() as c:
            rows=c.execute("""SELECT id::text,parameters,progress FROM research_job
                WHERE status='succeeded' AND idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'
                AND (%s::uuid IS NULL OR (created_at,id)<(SELECT created_at,id FROM research_job WHERE id=%s::uuid))
                AND (%s::text IS NULL OR parameters->>'bot'=%s)
                AND (%s::text IS NULL OR parameters->>'ticker'=%s)
                AND (%s::text IS NULL OR parameters->>'kind'=%s)
                ORDER BY created_at DESC,id DESC LIMIT 51""",(before,before,bot,bot,ticker,ticker,kind,kind)).fetchall()
        return dict(contract='demo-v1',items=[{'id':r['id'],**r['parameters'],**r['progress']} for r in rows[:50]],next_before=rows[49]['id'] if len(rows)>50 else None)
    @app.get('/demo/orders')
    def orders(request:Request):
        auth(request);require_query(request)
        return dict(contract='demo-v1',items=store.active_orders())
    @app.get('/demo/chart')
    def chart(request:Request):
        auth(request);require_query(request,('period',))
        period=request.query_params.get('period','24H');hours={'24H':24,'7D':168,'30D':720}.get(period)
        if hours is None:raise HTTPException(422,'Invalid period')
        with pool.connection() as c:
            rows=c.execute("""SELECT progress FROM research_job WHERE idempotency_key>='demo/equity/'
                AND idempotency_key<'demo/equity/zzzz' AND created_at>clock_timestamp()-%s*interval '1 hour'
                ORDER BY created_at DESC LIMIT 2880""",(hours,)).fetchall()
        # At most 192 points on mobile, independent of underlying snapshot count.
        points=[r['progress'] for r in reversed(rows)];step=max(1,(len(points)+191)//192)
        return dict(contract='demo-v1',points=points[::step],period=period)
    @app.get('/demo/research')
    def research(request:Request):
        auth(request);require_query(request,('asset','bot','start','end'))
        from datetime import date,timedelta
        from services.research.reports import SERIES
        asset=request.query_params.get('asset');bot=request.query_params.get('bot') or None
        if asset not in SERIES:raise HTTPException(422,'Choose a category')
        try:
            start=date.fromisoformat(request.query_params.get('start',''));end=date.fromisoformat(request.query_params.get('end',''))
            if bot:UUID(bot)
            if end<start or end-start>timedelta(days=3660):raise ValueError()
        except ValueError:raise HTTPException(422,'Choose a valid date range') from None
        from datetime import datetime,timezone
        begin=datetime.combine(start,datetime.min.time(),timezone.utc);through=datetime.combine(end+timedelta(days=1),datetime.min.time(),timezone.utc)
        with pool.connection() as c:
            rows=c.execute("""SELECT parameters->'condition' AS condition,parameters->>'side' AS side,
                count(*) AS orders,coalesce(sum((progress->>'filled')::numeric),0) AS contracts,
                coalesce(sum((progress->>'realized_cents')::numeric),0) AS realized_cents
                FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
                AND parameters->>'kind'='entry' AND parameters->'condition'->>'asset'=%s
                AND created_at >= %s AND created_at < %s AND (%s::text IS NULL OR parameters->>'bot'=%s)
                GROUP BY parameters->'condition',parameters->>'side' LIMIT 101""",(asset,begin,through,bot,bot)).fetchall()
        return dict(contract='demo-v1',source='kalshi-demo',items=rows[:100],limited=len(rows)>100)
    @app.post('/demo/policy')
    def policy(body:Policy,request:Request):
        mutate(request);require_query(request);store.put('policy',body.model_dump())
        store.event('policy_updated','Storage, archiving and alert settings updated')
        return dict(contract='demo-v1',saved=True)
    class Connection(BaseModel):
        model_config=ConfigDict(extra='forbid')
        key_id:str=Field(min_length=1,max_length=128)
        private_key:str=Field(min_length=100,max_length=12000)
    @app.post('/demo/connection')
    def connect(body:Connection,request:Request):
        mutate(request);require_query(request)
        key=os.environ.get('DEMO_VAULT_KEY')
        if not key:raise HTTPException(503,'Secure account connection is not configured yet')
        from services.demo.exchange import encrypt_credentials
        try:encrypted=encrypt_credentials(key,body.key_id,body.private_key)
        except Exception:raise HTTPException(422,'Enter a valid Demo API key and RSA private key') from None
        store.put('credentials',dict(encrypted=encrypted,changed_at=time.time()))
        store.event('connection_updated','Demo account credentials updated; verification pending')
        return dict(contract='demo-v1',saved=True)
    @app.post('/demo/refresh')
    def refresh(request:Request):
        mutate(request);require_query(request);store.put('refresh',dict(requested_at=time.time()))
        return dict(contract='demo-v1',accepted=True)
    @app.post('/demo/restore/{identifier}')
    def restore(identifier:UUID,request:Request):
        mutate(request);require_query(request)
        with pool.connection() as c:
            row=c.execute("SELECT progress FROM research_job WHERE id=%s AND idempotency_key>='demo/event/' AND idempotency_key<'demo/event/zzzz'",(identifier,)).fetchone()
        if not row or not row['progress'].get('archive'):raise HTTPException(404,'Archived event not found')
        store.put('restore/'+str(identifier),dict(event_id=str(identifier),requested_at=time.time()))
        return dict(contract='demo-v1',accepted=True)
