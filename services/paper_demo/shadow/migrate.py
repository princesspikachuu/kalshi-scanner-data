"""One-time, reversible 28-bot cohort; preserve every preceding ledger and history."""
import json,time
from pathlib import Path
from uuid import uuid5,NAMESPACE_URL
from psycopg.types.json import Jsonb
from services.paper_demo.ledger import Ledger
from services.trading.mode import LOCK as MODE_LOCK
from .storage import put


def profiles():return json.loads(Path(__file__).with_name('market_profiles.json').read_text())


def initialize(store,guard):
    if store.get('shadow/installed'):return True
    guard()
    # A previous paper position must still receive its existing exit/settlement
    # handling. Never retire an executor while it holds unmanaged inventory.
    ledger=Ledger(store,guard)
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
        mode=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode'").fetchone()
        if mode and mode['progress'].get('mode')!='demo':return False
        c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"paused\"}'::jsonb WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'")
    for order in ledger.orders('resting'):ledger.cancel(order['id'],time.time())
    if ledger.orders('resting'):
        time.sleep(.3);ledger.expire(time.time())
    if ledger.positions():
        store.alert('shadow-handover','New strategy is waiting for previous paper positions to close or settle. Existing protection remains active.',False)
        return False
    guard();now=time.time()
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/shadow/installed'").fetchone():return True
        c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"paused\",\"archived\":true}'::jsonb WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'")
        c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"paused\",\"state\":\"paused\"}'::jsonb WHERE idempotency_key>='live/bot/' AND idempotency_key<'live/bot/zzzz'")
        for p in profiles():
            p=dict(p,key=str(uuid5(NAMESPACE_URL,'moneytree/convexity/'+p['id'])),revision=1,changed_at=now)
            put(c,'demo/shadow/bot/'+p['id'],p,dict(desired='running'))
        old=c.execute("SELECT progress FROM research_job WHERE idempotency_key='demo/engine'").fetchone()
        if old:put(c,'demo/shadow/previous-engine',{},old['progress'])
        marker=dict(source='production_shadow',real_orders_enabled=False,starting_cents=100000,
            latency_ms=150,fill_model='shadow_queue_v1',changed_at=now,bots=28,
            message='Production data · 28 independent strategies · virtual funds only')
        put(c,'demo/engine',{},marker);put(c,'demo/shadow/installed',{},marker)
    store.clear_alert('shadow-handover')
    print(json.dumps(dict(event='shadow_cohort_initialized',bots=28,real_orders_enabled=False)),flush=True)
    return True
