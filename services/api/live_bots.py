"""Owner-only LIVE setup, read-only preflight, and manual single-contract pilot."""
import os,time
from decimal import Decimal,ROUND_DOWN
from uuid import UUID,uuid4
from pydantic import BaseModel,ConfigDict,Field,StrictInt,model_validator
from fastapi import Request,HTTPException
from psycopg.types.json import Jsonb
from .demo_models import BotConfig

class TrialBudget(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    trial_cap_cents:StrictInt=Field(ge=1,le=100000000000)
    portfolio_reference_cents:StrictInt|None=Field(default=None,ge=1,le=100000000000)
    loss_limit_cents:StrictInt|None=Field(default=None,ge=1,le=100000000000)
    @model_validator(mode='after')
    def within_portfolio(self):
        if self.portfolio_reference_cents is not None and self.trial_cap_cents>self.portfolio_reference_cents:
            raise ValueError('Trial amount must fit within the portfolio value entered')
        if self.loss_limit_cents is None:self.loss_limit_cents=max(1,self.trial_cap_cents//2)
        if self.loss_limit_cents>self.trial_cap_cents:raise ValueError('Loss cutoff exceeds trial amount')
        return self

class LiveSizing(BaseModel):
    model_config=ConfigDict(extra='forbid')
    expected_settings_revision:StrictInt=Field(ge=1)
    bid_percent:float=Field(ge=.1,le=100,allow_inf_nan=False)
    market_percent:float=Field(ge=.1,le=100,allow_inf_nan=False)
    bot_percent:float=Field(ge=.1,le=100,allow_inf_nan=False)

def sizing(config,budget):
    if not budget:return None
    cap=budget['trial_cap_cents'];portfolio=budget.get('portfolio_reference_cents')
    result={key.replace('_percent','_cents'):int((Decimal(cap)*Decimal(str(config[key]))/100).to_integral_value(rounding=ROUND_DOWN))
        for key in ('bid_percent','market_percent','bot_percent')}
    price=config.get('cycle_buy_cents',3)
    from services.trading.allocation import contracts
    result['contracts_per_bid']=contracts(config,price,cap)
    result['portfolio_equivalent_bid_percent']=float(Decimal(result['bid_cents'])*100/portfolio) if portfolio else None
    return result

def install_live_bots(app,auth,mutate,pool):
    from services.live.store import LiveStore
    from services.live.risk import value
    from services.trading.mode import read_mode,require_demo,LOCK,ModeConflict
    store=LiveStore(pool)
    def query(request):
        if request.query_params:raise HTTPException(422,'Invalid filters')
        if pool is None:raise HTTPException(503,'Live workspace unavailable')
    @app.get('/live/workspace')
    def workspace(request:Request):
        auth(request);query(request)
        with pool.connection() as c:
            rows=c.execute("""SELECT id::text,idempotency_key,parameters,progress FROM research_job
                WHERE idempotency_key>='live/bot/' AND idempotency_key<'live/bot/zzzz' ORDER BY parameters#>>'{config,name}' LIMIT 100""").fetchall()
            row=c.execute("SELECT progress FROM research_job WHERE idempotency_key='live/budget'").fetchone()
        budget=row['progress'] if row else None
        bots=[dict(key=r['idempotency_key'].split('/')[-1],**r['parameters'],desired=r['progress'].get('desired','paused'),state=r['progress'].get('state','paused'),sizing=sizing(r['parameters']['config'],budget)) for r in rows]
        connection=value(store,'credentials',{});health=value(store,'health',{});mode=read_mode(pool)
        orders=[dict(r['parameters'],**r['progress']) for r in store.rows('order/',100)]
        return dict(contract='live-bots-v2',environment='live',execution_enabled=mode.get('mode')=='live',connection_configured=bool(connection),
            connection=dict(subaccount=connection.get('subaccount'),verified_at=connection.get('verified_at')),worker_mode=mode,health=health,
            vault_ready=bool(os.environ.get('DEMO_VAULT_KEY')),pilot_contracts=1,budget=budget,bots=bots,orders=orders,
            risk=value(store,'risk'),account=value(store,'account'),pilot_result=value(store,'pilot-result'),
            message='One bot, one YES contract at 3¢. No automatic repeat or expansion. Demo must drain before LIVE runs.')
    @app.post('/live/budget')
    def budget(body:TrialBudget,request:Request):
        mutate(request);query(request)
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='live/trial'").fetchone():raise HTTPException(409,'Trial budget is locked once execution checks begin')
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto','{}'::jsonb,%s,'live/budget','succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,finished_at=clock_timestamp()""",
                (uuid4(),Jsonb(body.model_dump())))
        return dict(contract='live-bots-v2',environment='live',execution_enabled=False,saved=True)
    @app.post('/live/bots/{identifier}/sizing')
    def configure(identifier:UUID,body:LiveSizing,request:Request):
        mutate(request);query(request)
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            if read_mode(pool).get('mode')!='demo':raise HTTPException(409,'Switch back to Demo before editing LIVE settings')
            row=c.execute('SELECT parameters FROM research_job WHERE idempotency_key=%s FOR UPDATE',('live/bot/'+str(identifier),)).fetchone()
            if not row:raise HTTPException(404,'Live bot not found')
            saved=row['parameters'];revision=saved.get('settings_revision',1)
            if body.expected_settings_revision!=revision:raise HTTPException(409,'Live settings changed. Reload before saving.')
            config=BotConfig.model_validate(dict(saved['config'],**body.model_dump(exclude={'expected_settings_revision'}))).model_dump()
            saved=dict(saved,config=config,settings_revision=revision+1)
            c.execute("UPDATE research_job SET parameters=%s,progress=progress||'{\"desired\":\"paused\",\"state\":\"paused\"}'::jsonb,finished_at=clock_timestamp() WHERE idempotency_key=%s",
                (Jsonb(saved),'live/bot/'+str(identifier)))
        return dict(contract='live-bots-v2',environment='live',execution_enabled=False,saved=True)

    class Connection(BaseModel):
        model_config=ConfigDict(extra='forbid')
        key_id:str=Field(min_length=1,max_length=128,repr=False)
        private_key:str=Field(min_length=100,max_length=12000,repr=False)
        subaccount:StrictInt=Field(ge=1,le=63)
    @app.post('/live/connection')
    def connect(body:Connection,request:Request):
        mutate(request);query(request)
        vault=os.environ.get('DEMO_VAULT_KEY')
        if not vault:raise HTTPException(503,'Secure connection storage is not configured')
        from services.live.exchange import save_connection,LiveConnectionError
        from services.demo.exchange import CredentialInputError
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='live/trial'").fetchone():raise HTTPException(409,'Connection is locked to the active trial')
            mode=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode'").fetchone()
            if mode and mode['progress'].get('mode')!='demo':raise HTTPException(409,'Return the worker to Demo before replacing live credentials')
            try:save_connection(store,body.key_id,body.private_key,body.subaccount,vault)
            except (LiveConnectionError,CredentialInputError) as error:raise HTTPException(422,str(error)) from None
            except Exception:raise HTTPException(503,'Could not verify and securely save the live connection. No orders were placed.') from None
        return dict(contract='live-bots-v2',environment='live',execution_enabled=False,saved=True)
    class Preflight(BaseModel):
        model_config=ConfigDict(extra='forbid')
        bot:UUID
        expected_settings_revision:StrictInt=Field(ge=1)
    def connected_exchange():
        from services.live.exchange import load_connection,LiveExchange
        from services.demo.exchange import DemoSigner
        data=load_connection(store,os.environ.get('DEMO_VAULT_KEY'))
        if not data:raise HTTPException(409,'Connect the restricted live API key first')
        return data,LiveExchange(DemoSigner(data['key_id'],data['pem']),data['subaccount'])
    @app.post('/live/preflight')
    def preflight(body:Preflight,request:Request):
        mutate(request);query(request)
        from services.live.risk import settings,RiskBlocked
        from decimal import Decimal
        try:
            settings(store);row=store.get('bot/'+str(body.bot))
            if not row or row['parameters']['settings_revision']!=body.expected_settings_revision:raise RiskBlocked('Live bot settings changed; reload first')
            config=row['parameters']['config']
            if config.get('strategy')!='buy_low_sell_high' or config.get('cycle_exit_mode')!='late_threshold' or config.get('cycle_buy_cents')!=3 or config.get('cycle_entry_minutes')!=5 or config.get('cycle_repeat') is not False:
                raise RiskBlocked('Pilot requires the approved 3¢ / five-minute / conditional hold strategy')
            if value(store,'trial'):raise RiskBlocked('The single-contract execution check has already been started')
            data,exchange=connected_exchange()
            try:
                exchange.verify_scope()
                balance=exchange.call('GET','/portfolio/balance')
                orders=list(exchange.pages('/portfolio/orders','orders',status='resting'))
                positions=list(exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
                if balance.get('balance')!=5000 or balance.get('portfolio_value')!=0 or orders or any(Decimal(str(p.get('position_fp',p.get('position',0)))) for p in positions):
                    raise RiskBlocked('The isolated subaccount must contain exactly $50 cash, with no orders or positions')
                from services.research.reports import SERIES
                from services.demo.runtime import quote
                allowed={series for square in config['squares'] for series in SERIES[square['asset']]}
                if len(allowed)!=1:raise RiskBlocked('Choose a bot covering one 15-minute series for the initial check')
                page=exchange.call('GET','/markets',params=dict(series_ticker=next(iter(allowed)),status='open',min_close_ts=int(time.time()),max_close_ts=int(time.time()+900),limit=200))
                current=[]
                if not isinstance(page.get('markets'),list) or page.get('cursor'):raise RiskBlocked('Current pilot market could not be fully verified')
                for raw in page['markets']:
                    parsed=quote(raw,time.time())
                    if parsed and parsed[1]['series'] in allowed and parsed[1].get('status')=='active' and parsed[1].get('open',float('inf'))<=time.time()<parsed[1]['close']:current.append(parsed[1])
                if not current:raise RiskBlocked('No currently running market was found for this pilot bot. Check again when its market is active.')
                index=min(current,key=lambda q:q['close'])['exchange_index']
                available=exchange.call('GET','/portfolio/balance',params=dict(exchange_index=index))
                if available.get('balance',0)<3:raise RiskBlocked(f'This market uses exchange index {index}. Its isolated subaccount needs at least 3 cents there from your existing $50 trial. The worker cannot transfer funds.')
            finally:exchange.close()
            token=str(uuid4());store.put('preflight',dict(at=time.time(),token=token,bot=str(body.bot),settings_revision=body.expected_settings_revision,binding=data['binding']))
            return dict(contract='live-bots-v2',environment='live',execution_enabled=False,ready=True,token=token,message='Account verified. The worker will verify venue, market, fees and backup before its one-contract bid.')
        except RiskBlocked as error:raise HTTPException(409,str(error)) from None
        except HTTPException:raise
        except Exception:raise HTTPException(503,'Live preflight could not be verified. No orders placed.') from None
    class StartPilot(Preflight):
        token:UUID
        confirmation:str=Field(max_length=64)
    @app.post('/live/pilot')
    def pilot(body:StartPilot,request:Request):
        mutate(request);query(request)
        if body.confirmation!='START ONE LIVE CONTRACT':raise HTTPException(422,'Type START ONE LIVE CONTRACT to request the real-money check')
        from services.trading.mode import request_live
        try:request_live(pool,str(body.bot),body.expected_settings_revision,str(body.token))
        except (ModeConflict,ValueError) as error:raise HTTPException(409,str(error)) from None
        return dict(contract='live-bots-v2',environment='live',execution_enabled=False,accepted=True,message='Demo bots paused. LIVE waits for their verified drain.')
    @app.post('/live/pause')
    def pause(request:Request):
        mutate(request);query(request)
        from services.trading.mode import write_mode
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            row=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode' FOR UPDATE").fetchone()
            if row:write_mode(c,dict(row['progress'],pilot_paused=True))
            c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"paused\"}'::jsonb WHERE idempotency_key>='live/bot/' AND idempotency_key<'live/bot/zzzz'")
        return dict(contract='live-bots-v2',environment='live',execution_enabled=False,saved=True,message='New buys paused; existing contracts remain managed.')
    @app.post('/live/return-demo')
    def return_demo(request:Request):
        mutate(request);query(request)
        from services.trading.mode import write_mode
        with pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            active=c.execute("SELECT 1 FROM research_job WHERE idempotency_key>='live/order/' AND idempotency_key<'live/order/zzzz' AND progress->>'status' NOT IN ('closed','rejected') LIMIT 1").fetchone()
            if active:raise HTTPException(409,'LIVE orders or inventory still need management; keep the worker in LIVE')
            if value(store,'trial'):
                data,exchange=connected_exchange()
                try:
                    exchange.verify_scope()
                    if list(exchange.pages('/portfolio/orders','orders',status='resting')) or list(exchange.pages('/portfolio/positions','market_positions',count_filter='position')):
                        raise HTTPException(409,'LIVE account is not flat yet')
                finally:exchange.close()
            c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"paused\"}'::jsonb WHERE idempotency_key>='live/bot/' AND idempotency_key<'live/bot/zzzz'")
            write_mode(c,dict(mode='demo',requested='demo',message='Worker returned to Demo. Resume desired Demo bots explicitly.'))
        return dict(contract='live-bots-v2',environment='live',execution_enabled=False,saved=True)
