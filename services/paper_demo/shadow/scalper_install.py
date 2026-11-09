"""Additive, idempotent paper-only installation. Never updates an existing row."""
import time
from uuid import uuid4
from psycopg.types.json import Jsonb
from .storage import entry
from .migrate import profiles
from .scope import HOURLY
from .scalper import SCALPER_FOLDERS,CONFIGS

COMMODITIES=('GOLD','SILVER','PLATINUM','PALLADIUM','COPPER','WTI','NATGAS','BRENT')
CRYPTO=('BTC','ETH','SOL','XRP','DOGE','BNB','HYPE','ZEC','NEAR')

def scalper_profiles():
    rows=[dict(p,asset='scalper_15m') for p in profiles()]
    rows.extend(dict(series=s,name='1 hour · '+name,asset='hourly') for s,name in HOURLY)
    for p in rows:
        s=p['series'].removeprefix('KX')
        p['market_category']='commodities' if s.startswith(COMMODITIES) else 'crypto' if s.startswith(CRYPTO) else 'finance'
        p['underlying']=p['name'].removeprefix('1 hour · ')
    return rows


def initialize_scalper(store,guard):
    marker='shadow/volatility-scalper-v1'
    if store.get(marker):return
    guard();now=time.time()
    labels=('Volatility Scalper','Volatility Scalper · Fixed / maker entries','Volatility Scalper · Adaptive Range / Grid')
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',('demo/'+marker,)).fetchone():return
        def add(key,params,data):
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())
                ON CONFLICT(idempotency_key) DO NOTHING""",entry(key,params,data))
        for index,(folder,label) in enumerate(zip(SCALPER_FOLDERS,labels)):
            add('demo/shadow/folder/'+folder,dict(id=folder,name=label,strategy='volatility_scalper',order=5+index/10,
                description='Experimental short-duration paper scalps. Causal price windows, explicit timed liquidation, no automatic parameter promotion.',
                config=CONFIGS[folder]),dict(session=str(uuid4()),created_at=now))
            for source in scalper_profiles():
                ident=folder+'_'+source['series'].lower()
                add('demo/shadow/bot/'+ident,dict(source,id=ident,key=str(uuid4()),contracts=5,revision=1,changed_at=now,
                    folder_id=folder,strategy='volatility_scalper',version='scalper-1',live_enabled=False,config=CONFIGS[folder]),dict(desired='running'))
        add('demo/'+marker,{},dict(at=now,real_orders_enabled=False))


def apply_requested_volatility_pause(store,guard):
    """One-time staging state correction: the user requested every volatility variant paused."""
    marker='shadow/volatility-family-pause-20261109'
    if store.get(marker):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',('demo/'+marker,)).fetchone():return
        c.execute("""UPDATE research_job SET progress=jsonb_set(progress,'{desired}',to_jsonb('paused'::text))
            WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz'
            AND parameters->>'folder_id' IN ('volatility_scalper','scalper_fixed','scalper_grid','scalper_momentum','scalper_dislocation')""")
        c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
            VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",
            entry('demo/'+marker,{},dict(at=now,real_orders_enabled=False)))

def initialize_scalper_upgrade(store,guard):
    marker='shadow/scalper-execution-v2'
    if store.get(marker):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        def add(key,p,s):
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",entry(key,p,s))
        for i,folder in enumerate(('scalper_momentum','scalper_dislocation')):
            add('demo/shadow/folder/'+folder,dict(id=folder,name='Volatility Scalper · '+('Momentum' if i==0 else 'Liquidity Dislocation'),strategy='volatility_scalper',order=5.3+i/10,description='Independent paper experiment over shared causal observations.',config=CONFIGS[folder]),dict(session=str(uuid4()),created_at=now))
            for source in scalper_profiles():
                add('demo/shadow/bot/'+folder+'_'+source['series'].lower(),dict(source,id=folder+'_'+source['series'].lower(),key=str(uuid4()),contracts=5,revision=1,changed_at=now,folder_id=folder,strategy='volatility_scalper',version='scalper-2',live_enabled=False,config=CONFIGS[folder]),dict(desired='running'))
        add('demo/'+marker,{},dict(at=now,real_orders_enabled=False))
