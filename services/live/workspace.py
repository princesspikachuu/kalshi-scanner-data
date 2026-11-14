"""Isolated live configuration copies; never copies credentials, orders or P&L."""
import json,time
from uuid import uuid5,NAMESPACE_URL
from psycopg.types.json import Jsonb
from services.api.demo_models import BotConfig

MARKER='live/rollout/initial-demo-copies-20261105'
LOCK=723741940

def seed_live_bots(pool):
    with pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        if c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',(MARKER,)).fetchone():return 0
        rows=c.execute("""SELECT idempotency_key,parameters FROM research_job
            WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'
            AND progress->>'desired'='running' AND coalesce((progress->>'archived')::boolean,false)=false
            ORDER BY idempotency_key FOR SHARE""").fetchall()
        copied=0
        for row in rows:
            source=row['idempotency_key'].split('/')[-1];parameters=row['parameters']
            config=BotConfig.model_validate(parameters['config']).model_dump()
            identifier=str(uuid5(NAMESPACE_URL,'money-tree/live-copy/'+source))
            saved=dict(config=config,revision=1,settings_revision=1,budget_basis='trial_budget',
                source_demo_bot=source,source_demo_revision=parameters['revision'],copied_at=time.time())
            state=dict(desired='paused',state='paused',archived=False,message='Copied from Demo. Paused for live setup.')
            result=c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING RETURNING id""",
                (identifier,Jsonb(saved),Jsonb(state),'live/bot/'+identifier)).fetchone()
            copied+=bool(result)
        if not rows:return 0 # Retry at the next startup if Demo is not configured yet.
        c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
            VALUES(%s,'crypto','{}'::jsonb,%s,%s,'succeeded',clock_timestamp())""",
            (str(uuid5(NAMESPACE_URL,MARKER)),Jsonb(dict(copied=copied,at=time.time())),MARKER))
    print(json.dumps(dict(event='live_bots_copied',count=copied,desired='paused',execution_enabled=False,credentials_copied=False)),flush=True)
    return copied

def configure_approved_pilot(pool):
    """Apply the user's $50 / 50% / one-contract plan once; never start bots."""
    from services.trading.mode import LOCK
    key='live/rollout/approved-pilot-20261105'
    with pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        if c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',(key,)).fetchone():return
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='live/trial'").fetchone():return
        c.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at) VALUES(%s,'crypto','{}'::jsonb,%s,'live/budget','succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress",(str(uuid5(NAMESPACE_URL,'approved-live-budget')),Jsonb(dict(trial_cap_cents=5000,loss_limit_cents=2500,portfolio_reference_cents=None,pilot_contracts=1))))
        c.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at) VALUES(%s,'crypto','{}'::jsonb,%s,%s,'succeeded',clock_timestamp())",(str(uuid5(NAMESPACE_URL,key)),Jsonb(dict(at=time.time(),approved=True)),key))
