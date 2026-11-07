"""One-time scope update: preserve wallets, retire favorite 15m entries."""
import json,time
from uuid import uuid4
from .storage import put
from .weather import weather_profiles
from .sports import sports_profiles

HOURLY=(('KXBTCD','Bitcoin'),('KXETHD','Ethereum'),('KXSOLD','Solana'),('KXXRPD','XRP'),
 ('KXDOGED','Dogecoin'),('KXBNBD','BNB'),('KXHYPED','HYPE'),('KXZECD','Zcash'),('KXNEARD','NEAR'),
 ('KXGOLDH','Gold'),('KXSILVERH','Silver'),('KXPLATINUMH','Platinum'),('KXPALLADIUMH','Palladium'),('KXWTIH','WTI oil'),
 ('KXUSDCADAH','USD/CAD'),('KXAUDUSDH','AUD/USD'),('KXUSDJPYH','USD/JPY'),('KXGBPUSDH','GBP/USD'),('KXEURUSDH','EUR/USD'),
 ('KX2YRRATEH','2Y Treasury'),('KX5YRRATEH','5Y Treasury'),('KX10YRRATEH','10Y Treasury'),('KX30YRRATEH','30Y Treasury'),
 ('KXINXU','S&P 500'),('KXNASDAQ100U','Nasdaq 100'))

def hourly_profiles():
    return [dict(id='fav_hour_'+s.lower(),series=s,name='1 hour · '+name,asset='hourly',contracts=10,
        folder_id='favorites',strategy='favorites',version='favorites-hourly-1') for s,name in HOURLY]

def sequential_profiles():
    return [dict(p,id='seq_'+p['series'].lower(),folder_id='sequential',strategy='sequential',
                 version='sequential-expanded-1',sports_window='whole_live_game') for p in weather_profiles()+sports_profiles()]

def initialize_scope(store,guard):
    if store.get('shadow/scope-hourly-v1'):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/scope-hourly-v1'").fetchone():return
        # Keep their identifiers, closed results and owned inventory for exits.
        c.execute("""UPDATE research_job SET parameters=parameters||'{"retired":true}'::jsonb,
            progress=progress||'{"desired":"paused"}'::jsonb
            WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz' AND starts_with(idempotency_key,'demo/shadow/bot/')
            AND parameters->>'folder_id'='favorites' AND parameters->>'series' LIKE '%15M'""")
        for p in hourly_profiles()+sequential_profiles():
            key='demo/shadow/bot/'+p['id']
            if c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',(key,)).fetchone():continue
            # Expanded experiments are explicitly enabled by this requested test.
            put(c,key,dict(p,key=str(uuid4()),revision=1,changed_at=now),dict(desired='running'))
        for folder,description in (
            ('favorites','Tests 70–95¢ favorites in one-hour price markets, hourly/daily weather and late live sports. Previous 15-minute entries are retired; history and exits are preserved.'),
            ('sequential','Collects complementary sides in 15-minute markets, hourly/daily weather and throughout verified live sports. Learns completion probabilities and includes unmatched losses.')):
            c.execute("UPDATE research_job SET parameters=jsonb_set(parameters,'{description}',to_jsonb(%s::text)) WHERE idempotency_key=%s",(description,'demo/shadow/folder/'+folder))
        put(c,'demo/shadow/scope-hourly-v1',{},dict(at=now,hourly=len(HOURLY),sequential_added=len(sequential_profiles())))
    print(json.dumps(dict(event='paper_scope_updated',favorite_15m_retired=28,favorite_hourly_bots=len(HOURLY),sequential_weather_sports_bots=len(sequential_profiles()),real_orders_enabled=False)),flush=True)


def initialize_restored_favorites(store,guard):
    """Restore the original 15m paper bots once; retain IDs, settings and history."""
    marker='shadow/favorites-15m-restored-v1'
    if store.get(marker):return
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820193,))
        if c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',('demo/'+marker,)).fetchone():return
        # A folder-wide pause made during rollout still takes precedence. The
        # retirement itself paused these rows, so look at the active cohort.
        running=bool(c.execute("""SELECT 1 FROM research_job WHERE idempotency_key>='demo/shadow/bot/'
            AND idempotency_key<'demo/shadow/bot/zzzz' AND starts_with(idempotency_key,'demo/shadow/bot/') AND parameters->>'folder_id'='favorites'
            AND parameters->>'retired' IS DISTINCT FROM 'true' AND progress->>'desired'='running' LIMIT 1""").fetchone())
        rows=c.execute("""SELECT idempotency_key,parameters,progress FROM research_job
            WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz'
            AND parameters->>'folder_id'='favorites' AND parameters->>'series' LIKE '%15M'
            AND parameters->>'retired'='true' FOR UPDATE""").fetchall()
        for row in rows:
            p=dict(row['parameters'],retired=False,paper_exploration=True,restored_at=now,version='favorites-paper-data-v3')
            put(c,row['idempotency_key'],p,dict(row['progress'],desired='running' if running else 'paused'))
        description='Collects 70–95¢ maker data in 15-minute and hourly price markets, hourly/daily weather and late live sports. Configured-size paper exploration; previous history is preserved.'
        c.execute("UPDATE research_job SET parameters=jsonb_set(parameters,'{description}',to_jsonb(%s::text)) WHERE idempotency_key='demo/shadow/folder/favorites'",(description,))
        put(c,'demo/'+marker,{},dict(at=now,restored=len(rows),running=running,real_orders_enabled=False))
    print(json.dumps(dict(event='paper_favorites_15m_restored',restored=len(rows),running=running,real_orders_enabled=False)),flush=True)
