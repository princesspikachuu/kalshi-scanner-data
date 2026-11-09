"""Idempotent installation of the concurrent Statistics-Backed Favorites portfolio."""
import json,time
from uuid import uuid4
from .storage import put

FOLDER='favorites_statistics'

def initialize_statistics_favorites(store,guard):
    if store.get('shadow/favorite-statistics-v1'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/favorite-statistics-v1'").fetchone():return
        rows=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz' AND starts_with(idempotency_key,'demo/shadow/bot/') AND parameters->>'folder_id'='favorites'").fetchall()
        put(c,'demo/shadow/folder/'+FOLDER,dict(id=FOLDER,name='Favorites · Statistics-Backed',strategy='favorites_statistics',
            description='Selective paper trading from settled Favorites evidence using hierarchical sample-size fallbacks and confidence bounds.',
            order=3.1),dict(session=str(uuid4()),created_at=now))
        for r in rows:
            p=r['parameters'];ident='stats_'+p['id']
            put(c,'demo/shadow/bot/'+ident,dict(p,id=ident,key=str(uuid4()),revision=1,changed_at=now,
                name=p.get('name',p['series'])+' · Statistics',folder_id=FOLDER,strategy='favorites_statistics',
                paper_exploration=False,statistics_min_samples=20,statistics_min_probability_edge='.01',
                statistics_min_expected_roi='.01',statistics_slippage_buffer='.005',
                statistics_max_capital_fraction='.05',version='favorites-statistics-1'),dict(desired=r['progress'].get('desired','running')))
        put(c,'demo/shadow/favorite-statistics-v1',{},dict(at=now,profiles=len(rows),real_orders_enabled=False))
    print(json.dumps(dict(event='statistics_favorites_initialized',profiles=len(rows),real_orders_enabled=False)),flush=True)
