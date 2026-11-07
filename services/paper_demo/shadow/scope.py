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
            WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz'
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
