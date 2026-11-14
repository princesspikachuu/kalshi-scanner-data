"""Idempotent paper experiment organization; existing money/history is never rewritten."""
import time
from uuid import uuid4
from .storage import put
from .migrate import profiles

FOLDERS=(
    dict(id='convexity',name='Convexity · Paused',strategy='convexity',description='Previous 10¢ / 3¢ bots and their preserved results.',order=4),
    dict(id='complete_set',name='Complete-Set Arbitrage',strategy='complete_set',description='Scans same-day mutually exclusive outcome sets for a minimum payout above executable cost and fees.',order=1),
    dict(id='favorites',name='High-Probability Favorites',strategy='favorites',description='Tests 70–95¢ maker purchases in 15-minute markets with evidence-based exits. Historical favorite bias is a hypothesis here.',order=3),
    dict(id='sequential',name='Sequential Spread Trading',strategy='sequential',description='Collects complementary sides over time; learns completion probabilities and includes unmatched losses.',order=2),
)

def initialize_folders(store,guard):
    if store.get('shadow/strategy-layout'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/strategy-layout'").fetchone():return
        for f in FOLDERS:
            put(c,'demo/shadow/folder/'+f['id'],dict(f),dict(session=str(uuid4()),created_at=now))
        rows=c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz' AND starts_with(idempotency_key,'demo/shadow/bot/') FOR UPDATE").fetchall()
        for r in rows:
            put(c,r['idempotency_key'],dict(r['parameters'],folder_id='convexity',strategy='convexity'),dict(r['progress'],desired='paused'))
        for p in profiles():
            ident='seq_'+p['id']
            put(c,'demo/shadow/bot/'+ident,dict(p,id=ident,key=str(uuid4()),revision=1,changed_at=now,
                contracts=10,folder_id='sequential',strategy='sequential',version='sequential-1'),dict(desired='running'))
        for p in profiles():
            ident='fav_'+p['id']
            put(c,'demo/shadow/bot/'+ident,dict(p,id=ident,key=str(uuid4()),revision=1,changed_at=now,
                contracts=10,folder_id='favorites',strategy='favorites',version='favorites-1'),dict(desired='running'))
        put(c,'demo/shadow/bot/set_scanner',dict(id='set_scanner',key=str(uuid4()),name='Complete-set scanner',
            series='ALL_SAME_DAY',asset='all',contracts=10,revision=1,changed_at=now,
            folder_id='complete_set',strategy='complete_set',version='complete-set-1'),dict(desired='running'))
        put(c,'demo/shadow/strategy-layout',{},dict(at=now,real_orders_enabled=False))

    print(__import__('json').dumps(dict(event='paper_strategy_folders_initialized',folders=[f['name'] for f in FOLDERS],
        paused_convexity_bots=28,sequential_bots=28,favorite_bots=28,complete_set_scanners=1,real_orders_enabled=False)),flush=True)
