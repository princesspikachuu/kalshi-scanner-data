"""Idempotent, independently funded sequential paper comparison."""
import time,json
from uuid import uuid4
from .storage import put

SEQUENTIAL_FOLDERS=('sequential','sequential_flexible','sequential_adaptive')
from .scalper import SCALPER_FOLDERS
from .market_maker import MM_FOLDERS
EXPERIMENT_FOLDERS=(*SEQUENTIAL_FOLDERS,'complete_set','favorites',*SCALPER_FOLDERS,*MM_FOLDERS)
BOT_LIMIT=800

def initialize_comparison(store,guard):
    if store.get('shadow/sequential-comparison-v1'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/sequential-comparison-v1'").fetchone():return
        rows=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz' AND starts_with(idempotency_key,'demo/shadow/bot/') AND parameters->>'folder_id'='sequential'").fetchall()
        # Baseline identifiers, wallet, desired states and historical attempts survive.
        c.execute("UPDATE research_job SET parameters=parameters||%s::jsonb WHERE idempotency_key='demo/shadow/folder/sequential'",
            (json.dumps(dict(name='Sequential Spread · Baseline',comparison_started_at=now,variant='baseline')),))
        for r in rows:
            p=r['parameters']
            put(c,'demo/shadow/bot/'+p['id'],dict(p,variant='baseline',comparison_started_at=now),r['progress'])
        for variant,label,order in (('flexible','Flexible Completion',2.1),('adaptive','Adaptive',2.2)):
            folder='sequential_'+variant
            put(c,'demo/shadow/folder/'+folder,dict(id=folder,name='Sequential Spread · '+label,strategy='sequential',
                description=('Original entries with fee-aware profitable taker completion.' if variant=='flexible' else
                'Market-relative entries, pooled learning and conditional continuation estimates. Unproven states use one-contract exploration.'),
                variant=variant,comparison_started_at=now,order=order),dict(session=str(uuid4()),created_at=now))
            for r in rows:
                p=r['parameters'];ident=variant+'_'+p['id']
                put(c,'demo/shadow/bot/'+ident,dict(p,id=ident,key=str(uuid4()),revision=1,changed_at=now,
                    folder_id=folder,variant=variant,comparison_started_at=now,version='sequential-'+variant+'-1'),
                    dict(desired=r['progress'].get('desired','paused')))
        put(c,'demo/shadow/sequential-comparison-v1',{},dict(at=now,profiles=len(rows),real_orders_enabled=False))
    print(json.dumps(dict(event='sequential_comparison_initialized',profiles=len(rows),variants=3,real_orders_enabled=False)),flush=True)
