"""Idempotent installation of the concurrent Statistics-Backed Favorites portfolio."""
import json,time
from uuid import uuid4
from .storage import put
from psycopg.types.json import Jsonb

FOLDER='favorites_statistics'

def _initialize_base(store,guard):
    if store.get('shadow/favorite-statistics-v1'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/favorite-statistics-v1'").fetchone():return
        rows=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz' AND starts_with(idempotency_key,'demo/shadow/bot/') AND parameters->>'folder_id'='favorites'").fetchall()
        put(c,'demo/shadow/folder/'+FOLDER,dict(id=FOLDER,name='Favorites · Statistics-Backed',strategy='favorites_statistics',
            description='Evidence-backed paper bids plus small targeted exploration to improve sparse price/time outcome data.',
            order=3.1),dict(session=str(uuid4()),created_at=now))
        for r in rows:
            p=r['parameters'];ident='stats_'+p['id']
            put(c,'demo/shadow/bot/'+ident,dict(p,id=ident,key=str(uuid4()),revision=1,changed_at=now,
                name=p.get('name',p['series'])+' · Statistics',folder_id=FOLDER,strategy='favorites_statistics',
                paper_exploration=False,statistics_active_learning=True,statistics_exploration_contracts=2,
                statistics_exploration_target_samples=20,statistics_exploration_order_fraction='.01',
                statistics_exploration_portfolio_fraction='.10',statistics_exploration_max_open_markets=12,
                statistics_min_samples=20,statistics_min_probability_edge='.01',
                statistics_min_expected_roi='.01',statistics_slippage_buffer='.005',
                statistics_max_capital_fraction='.05',statistics_refresh_seconds=30,version='favorites-statistics-1'),dict(desired=r['progress'].get('desired','running')))
        put(c,'demo/shadow/favorite-statistics-v1',{},dict(at=now,profiles=len(rows),real_orders_enabled=False))
    print(json.dumps(dict(event='statistics_favorites_initialized',profiles=len(rows),real_orders_enabled=False)),flush=True)

def initialize_statistics_favorites(store,guard):
    """Enable learning and widen default exploration without resetting history."""
    _initialize_base(store,guard)
    if not store.get('shadow/favorite-statistics-learning-v2'):
        guard();now=time.time()
        config=dict(statistics_active_learning=True,statistics_exploration_contracts=2,
            statistics_exploration_target_samples=20,
            statistics_exploration_order_fraction='.01',
            statistics_exploration_portfolio_fraction='.10',
            statistics_exploration_max_open_markets=6)
        with store.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(%s)',(73820194,))
            if not c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/favorite-statistics-learning-v2'").fetchone():
                updated=c.execute("""UPDATE research_job SET parameters=parameters || %s
                    WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz'
                      AND parameters->>'folder_id'='favorites_statistics'
                      AND parameters->>'statistics_active_learning' IS DISTINCT FROM 'true'
                    RETURNING id""",(Jsonb(config),)).fetchall()
                put(c,'demo/shadow/favorite-statistics-learning-v2',
                    dict(mode='active_learning',policy='favorites-statistics-learn-v2'),
                    dict(at=now,profiles_enabled=len(updated),real_orders_enabled=False))
                print(json.dumps(dict(event='statistics_favorites_learning_enabled',
                    profiles_enabled=len(updated),preserved_history=True,real_orders_enabled=False)),flush=True)
    widen_statistics_exploration(store,guard)

def widen_statistics_exploration(store,guard):
    """Double the default active-learning breadth without overriding custom profiles."""
    if store.get('shadow/favorite-statistics-learning-v3'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820195,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/favorite-statistics-learning-v3'").fetchone():return
        updated=c.execute("""UPDATE research_job
            SET parameters=jsonb_set(parameters,'{statistics_exploration_max_open_markets}','12'::jsonb,true)
            WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz'
              AND parameters->>'folder_id'='favorites_statistics'
              AND (parameters->>'statistics_exploration_max_open_markets' IS NULL
                   OR parameters->>'statistics_exploration_max_open_markets'='6')
            RETURNING id""").fetchall()
        put(c,'demo/shadow/favorite-statistics-learning-v3',
            dict(mode='active_learning_breadth',max_open_markets=12),
            dict(at=now,profiles_updated=len(updated),preserved_history=True,real_orders_enabled=False))
    print(json.dumps(dict(event='statistics_favorites_exploration_widened',
        profiles_updated=len(updated),max_open_markets=12,preserved_history=True,real_orders_enabled=False)),flush=True)
