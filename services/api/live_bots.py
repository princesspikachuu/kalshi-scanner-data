"""Owner-only LIVE configuration and budget planning. No order or resume routes."""
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
    @model_validator(mode='after')
    def within_portfolio(self):
        if self.portfolio_reference_cents is not None and self.trial_cap_cents>self.portfolio_reference_cents:
            raise ValueError('Trial amount must fit within the portfolio value entered')
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
    result['contracts_per_bid']=min(result['bid_cents'],result['market_cents'],result['bot_cents'])//price
    result['portfolio_equivalent_bid_percent']=float(Decimal(result['bid_cents'])*100/portfolio) if portfolio else None
    return result

def install_live_bots(app,auth,mutate,pool):
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
        bots=[dict(key=r['idempotency_key'].split('/')[-1],**r['parameters'],desired='paused',state='paused',sizing=sizing(r['parameters']['config'],budget)) for r in rows]
        return dict(contract='live-bots-v1',environment='live',execution_enabled=False,connection_configured=False,
            budget=budget,bots=bots,message='All live bots are paused. Choose your trial budget before live account setup.')
    @app.post('/live/budget')
    def budget(body:TrialBudget,request:Request):
        mutate(request);query(request)
        with pool.connection() as c:
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto','{}'::jsonb,%s,'live/budget','succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,finished_at=clock_timestamp()""",
                (uuid4(),Jsonb(body.model_dump())))
        return dict(contract='live-bots-v1',environment='live',execution_enabled=False,saved=True)
    @app.post('/live/bots/{identifier}/sizing')
    def configure(identifier:UUID,body:LiveSizing,request:Request):
        mutate(request);query(request)
        with pool.connection() as c:
            row=c.execute('SELECT parameters FROM research_job WHERE idempotency_key=%s FOR UPDATE',('live/bot/'+str(identifier),)).fetchone()
            if not row:raise HTTPException(404,'Live bot not found')
            saved=row['parameters'];revision=saved.get('settings_revision',1)
            if body.expected_settings_revision!=revision:raise HTTPException(409,'Live settings changed. Reload before saving.')
            config=BotConfig.model_validate(dict(saved['config'],**body.model_dump(exclude={'expected_settings_revision'}))).model_dump()
            saved=dict(saved,config=config,settings_revision=revision+1)
            c.execute("UPDATE research_job SET parameters=%s,progress=progress||'{\"desired\":\"paused\",\"state\":\"paused\"}'::jsonb,finished_at=clock_timestamp() WHERE idempotency_key=%s",
                (Jsonb(saved),'live/bot/'+str(identifier)))
        return dict(contract='live-bots-v1',environment='live',execution_enabled=False,saved=True)
