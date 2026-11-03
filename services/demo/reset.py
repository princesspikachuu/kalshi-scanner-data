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
    confirmation:str|None=None
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
    if request.confirmation!='RESET BOTS':raise ResetConflict('Type RESET BOTS and acknowledge the reset before continuing')
    identifier=str(request.request_id)
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(723741930)')
        old=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key='demo/reset' FOR UPDATE").fetchone()
        if old and old['parameters']['request_id']==identifier:return dict(old['parameters'],**old['progress'])
        bots=c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz' FOR UPDATE").fetchall()
        sources=[dict(old=b['idempotency_key'].split('/')[-1],new=str(uuid5(NAMESPACE_URL,'demo-reset/'+identifier+'/'+b['idempotency_key'].split('/')[-1])),config=b['parameters']['config'],prior_desired=b['progress'].get('desired','paused'),
            prior_archived=bool(b['progress'].get('archived',False))) for b in bots if not b['progress'].get('archived')]
        if len(bots)+len(sources)>100:raise ResetConflict('There is not enough bot capacity for fresh copies; existing bots and history have been kept')
        params=dict(request_id=identifier,mode='archive_copy',fresh_bots=True,target_balance_cents=None,sources=sources,requested_at=time.time())
        archive_bots(c,params)
        state=dict(state='complete',message=MESSAGE,cloned=True,at=time.time(),completed_at=time.time())
        c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
            VALUES(%s,'crypto',%s,%s,'demo/reset','succeeded',clock_timestamp())
            ON CONFLICT(idempotency_key) DO UPDATE SET parameters=excluded.parameters,progress=excluded.progress,finished_at=clock_timestamp()""",(uuid4(),Jsonb(params),Jsonb(state)))
    store.event('reset_complete','Bots archived and copied with fresh statistics; existing orders, positions, and history retained')
    return dict(params,**state)


class UndoResetRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID

# The 28 individually selected 15-minute bots were observed running in the
# worker immediately before the accidental 2026-11-03 reset attempt.
ACCIDENT_RUNNING_CATEGORIES=frozenset((
    'btc','eth','sol','xrp','doge','bnb','hype','zec','near',
    'gold_15m','silver_15m','platinum_15m','palladium_15m',
    'copper_15m','wti_15m','natgas_15m','brent_15m',
    'usdcad_15m','audusd_15m','usdjpy_15m','gbpusd_15m',
    'eurusd_15m','rate2y_15m','rate5y_15m','rate10y_15m',
    'rate30y_15m','sp500_15m','nasdaq100_15m'))

def undo_reset(store,identifier,*,incident=False):
    """Undo only the latest archive/copy transaction; never touch exchange orders.

    A reset copy must still be paused, unmodified and unused. If an exchange
    order or event is attributed to a copy, require manual investigation rather
    than deleting it or accidentally double-trading the same market.
    """
    identifier=str(UUID(str(identifier)))
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(723741930)')
        row=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key='demo/reset' FOR UPDATE").fetchone()
        if not row or row['parameters'].get('request_id')!=identifier:raise ResetConflict('This is not the latest reset; no bots were changed')
        params=row['parameters'];state=row['progress']
        if state.get('state')=='undone':return dict(params,**state)
        if params.get('mode')!='archive_copy' or state.get('state')!='complete':
            raise ResetConflict('This reset is not an eligible completed archive/copy reset')
        if not 0<=time.time()-params.get('requested_at',0)<=5400:
            raise ResetConflict('This reset is too old for automatic undo; no bots were changed')
        sources=params.get('sources') or []
        if not sources or len(sources)>100:raise ResetConflict('Cannot verify the original bot list')
        originals=[s['old'] for s in sources];copies=[s['new'] for s in sources]
        if len(set(originals))!=len(originals) or len(set(copies))!=len(copies):
            raise ResetConflict('Reset bot IDs are inconsistent')
        keys=['demo/bot/'+x for x in originals+copies]
        rows=c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key=ANY(%s) FOR UPDATE",(keys,)).fetchall()
        by_key={r['idempotency_key']:r for r in rows}
        if len(rows)!=len(keys):raise ResetConflict('A reset bot was removed; manual recovery required')
        for source in sources:
            old=by_key['demo/bot/'+source['old']];new=by_key['demo/bot/'+source['new']]
            if (not old['progress'].get('archived') or old['progress'].get('desired')!='paused'
                or old['parameters'].get('config')!=source['config']
                or new['parameters'].get('reset_source')!=source['old']
                or new['parameters'].get('revision')!=1
                or new['parameters'].get('config',{}).get('name')!=source['config']['name'][:72]+' · fresh'
                or new['progress'].get('desired')!='paused' or new['progress'].get('archived')):
                raise ResetConflict('Some bots were edited after reset; no bots were changed')
        # Copies are untouched by trades, even if a caller resumed and paused
        # a copy between requests. If any order/event exists, never delete it.
        for prefix in ('demo/order/','demo/event/'):
            used=c.execute("""SELECT 1 FROM research_job WHERE idempotency_key>=%s AND idempotency_key<%s
                AND parameters->>'bot'=ANY(%s) LIMIT 1""",(prefix,prefix+'zzzz',copies)).fetchone()
            if used:raise ResetConflict('A fresh copy has trading history; preserving every bot for manual recovery')
        categories=[s['config']['squares'][0]['asset'] for s in sources
            if len(s['config'].get('squares',[]))==1]
        exact_incident=bool(incident and len(sources)==28 and len(categories)==28
            and set(categories)==ACCIDENT_RUNNING_CATEGORIES)
        running=0
        for source in sources:
            row=by_key['demo/bot/'+source['old']]
            state=dict(row['progress'])
            desired=source.get('prior_desired') or ('running' if exact_incident else 'paused')
            if desired not in ('running','paused'):desired='paused'
            if desired=='running':running+=1
            state.update(archived=False,desired=desired,
                message='Original bot restored after reset; verify current exchange orders before entry' if desired=='running'
                else 'Original bot restored after reset; paused until resumed')
            c.execute("UPDATE research_job SET progress=%s WHERE idempotency_key=%s",
                (Jsonb(state),'demo/bot/'+source['old']))
        c.execute("DELETE FROM research_job WHERE idempotency_key=ANY(%s)",
            (['demo/bot/'+x for x in copies],))
        result=dict(state='undone',undone_at=time.time(),restored=len(sources),
            resumed=running,message='Original bots restored; unused reset copies removed. Existing orders and positions were not modified.')
        c.execute("UPDATE research_job SET progress=%s WHERE idempotency_key='demo/reset'",(Jsonb(result),))
    print(json.dumps(dict(event='demo_reset_undone',restored=len(sources),resumed=running,
        incident=incident,exchange_orders_modified=False)),flush=True)
    store.event('reset_undone','Accidental bot archive/copy reset undone; original bots restored; exchange positions preserved')
    return dict(params,**result)

def undo_recent_incident(store):
    """One-time, time-window-scoped undo of the reported Nov 3 accidental reset.

    Never replays or cancels an exchange trade. If no matching completed reset
    exists, or any copy was used, this leaves every record unchanged.
    """
    row=store.get('reset')
    if not row:return False
    params=row['parameters'];time_at=params.get('requested_at',0)
    # Exactly the reported incident window; cannot undo an earlier reset.
    start=1793737800  # Nov 3, 2026 at 20:30 UTC
    end=1793738400    # Nov 3, 2026 at 20:40 UTC
    if not start<=time_at<=end or row['progress'].get('state')!='complete':return False
    try:undo_reset(store,params['request_id'],incident=True)
    except ResetConflict as error:
        print(json.dumps(dict(event='demo_reset_undo_guarded',reason=str(error))),flush=True)
        return False
    return True


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
