"""Versioned default quote-lifetime upgrade; wallets and custom settings survive."""
import time
from .storage import put

def initialize_quote_policy(store,guard):
    marker='shadow/maker-quote-policy-v2'
    if store.get(marker):return
    guard();now=time.time();changed=0
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(73820194,))
        if c.execute('SELECT id FROM research_job WHERE idempotency_key=%s',('demo/'+marker,)).fetchone():return
        rows=c.execute("""SELECT parameters,progress FROM research_job
            WHERE idempotency_key>='demo/shadow/bot/' AND idempotency_key<'demo/shadow/bot/zzzz'
            AND parameters->>'strategy'='market_maker' FOR UPDATE""").fetchall()
        for row in rows:
            old=row['parameters'];config=dict(old.get('config',{}));updates={}
            if config.get('order_ttl',300)==300:updates['order_ttl']=1800
            if config.get('exit_ttl',120)==120:updates['exit_ttl']=900
            if not updates:continue
            ident=old['id'];revision=old.get('revision',1)
            put(c,'demo/shadow/version/'+ident+'/'+str(revision),{},old)
            p=dict(old,config=dict(config,**updates),version='maker-2',revision=revision+1,changed_at=now)
            put(c,'demo/shadow/bot/'+ident,p,row['progress']);changed+=1
        put(c,'demo/'+marker,{},dict(at=now,changed=changed,real_orders_enabled=False))
