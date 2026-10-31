"""Atomic bot archive/copy reset; no funding or liquidation prerequisite."""
import json,time
from uuid import UUID,uuid4,uuid5,NAMESPACE_URL
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb

# Legacy states are completed once by the worker after upgrading. New resets
# finish inside their request transaction and never enter this workflow.
ACTIVE={'requested','canceling','closing','verifying','waiting','awaiting_funds','attention'}
class ResetRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    # Accept old cached clients during rollout, without restoring old semantics.
    fresh_bots:bool=True
    target_balance_cents:int|None=Field(default=None,ge=100,le=10000000)

class ResetConflict(ValueError):pass

MESSAGE='Bots archived and fresh paused copies created. Resume them whenever you are ready; no target balance is required.'

def archive_bots(c,params):
    for source in params['sources']:
        row=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('demo/bot/'+source['old'],)).fetchone()
        if row:
            state=dict(row['progress'],desired='paused',archived=True,message='Archived; historical orders and statistics retained. Existing positions remain protected.')
            c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),'demo/bot/'+source['old']))
        config=dict(source['config'],name=(source['config']['name'][:72]+' · fresh'))
        c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
            VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",
            (UUID(source['new']),Jsonb(dict(config=config,revision=1,reset_source=source['old'])),
             Jsonb(dict(desired='paused',archived=False,state='paused',message='Fresh statistics; ready to resume')),'demo/bot/'+source['new']))
        c.execute("""UPDATE research_job SET progress=jsonb_set(progress,'{message}',%s)
            WHERE idempotency_key=%s AND progress->>'desired'='paused'""",
            (Jsonb('Fresh statistics; ready to resume'),'demo/bot/'+source['new']))

def request_reset(store,request):
    identifier=str(request.request_id)
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(723741930)')
        old=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key='demo/reset' FOR UPDATE").fetchone()
        if old and old['parameters']['request_id']==identifier:return dict(old['parameters'],**old['progress'])
        bots=c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz' FOR UPDATE").fetchall()
        sources=[dict(old=b['idempotency_key'].split('/')[-1],new=str(uuid5(NAMESPACE_URL,'demo-reset/'+identifier+'/'+b['idempotency_key'].split('/')[-1])),config=b['parameters']['config']) for b in bots if not b['progress'].get('archived')]
        if len(bots)+len(sources)>100:raise ResetConflict('There is not enough bot capacity for fresh copies; existing bots and history have been kept')
        params=dict(request_id=identifier,mode='archive_copy',fresh_bots=True,target_balance_cents=None,sources=sources,requested_at=time.time())
        archive_bots(c,params)
        state=dict(state='complete',message=MESSAGE,cloned=True,at=time.time(),completed_at=time.time())
        c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
            VALUES(%s,'crypto',%s,%s,'demo/reset','succeeded',clock_timestamp())
            ON CONFLICT(idempotency_key) DO UPDATE SET parameters=excluded.parameters,progress=excluded.progress,finished_at=clock_timestamp()""",(uuid4(),Jsonb(params),Jsonb(state)))
    store.event('reset_complete','Bots archived and copied with fresh statistics; existing orders, positions, and history retained')
    return dict(params,**state)

class ResetController:
    """Retire the prior cleanup workflow without issuing any exchange requests."""
    def __init__(self,store,exchange):self.store=store
    def step(self,row):
        with self.store.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(723741930)')
            current=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key='demo/reset' FOR UPDATE").fetchone()
            if not current or current['progress'].get('state') not in ACTIVE:return
            params=current['parameters']
            # Deterministic copy IDs reuse any copies already prepared by the
            # old workflow. Order records and unresolved sale receipts survive.
            archive_bots(c,params)
            state=dict(current['progress'],state='complete',message=MESSAGE,cloned=True,legacy_cleanup_stopped=True,completed_at=time.time(),at=time.time())
            c.execute("UPDATE research_job SET progress=%s WHERE idempotency_key='demo/reset'",(Jsonb(state),))
            row['progress']=state
        print(json.dumps(dict(event='demo_reset_migrated',state='complete',funding_required=False,copies=len(params['sources']))),flush=True)
        self.store.event('reset_complete','Removed legacy reset funding/cleanup block; existing bot copies reused and historical exposure retained')
