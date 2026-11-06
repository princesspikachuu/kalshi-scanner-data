"""One atomic ledger boundary; retain original Kalshi Demo records unchanged."""
import time
from uuid import uuid4
from psycopg.types.json import Jsonb
from services.demo.exchange import credentials,Exchange,ExchangeFailure
from services.trading.mode import LOCK as MODE_LOCK

FEATURES=['square_bid_caps_v1','square_loss_prevention_v1','editable_rules_v1','buy_low_sell_high_v1','current_time_loss_v1']

def migrate(store,env,guard):
    if store.get('engine'):return
    guard();old=store.active_orders();owned={o['client_id'] for o in old}
    signer=credentials(store,env)
    if signer:
        exchange=Exchange(signer,guard=guard)
        try:
            resting=list(exchange.pages('/portfolio/orders','orders',status='resting'))
            for order in resting:
                if order.get('client_order_id') in owned:exchange.cancel(order['order_id'],order['ticker'])
            if any(o.get('client_order_id') in owned for o in exchange.pages('/portfolio/orders','orders',status='resting')):
                raise ExchangeFailure('paper_transition_waiting_for_demo_cancels')
        finally:exchange.close()
    elif any(o.get('remaining',0) for o in old):raise ExchangeFailure('paper_transition_demo_key_required')
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,));guard()
        mode=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode' FOR UPDATE").fetchone()
        if mode and mode['progress'].get('mode')!='demo':raise ExchangeFailure('paper_transition_waiting_for_demo_mode')
        if c.execute("SELECT 1 FROM research_job WHERE idempotency_key='demo/engine'").fetchone():return
        bots=c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz' FOR UPDATE").fetchall()
        account=c.execute("SELECT progress FROM research_job WHERE idempotency_key='demo/account'").fetchone()
        starting=max(1,int(account['progress']['equity_cents'])) if account and account['progress'].get('equity_cents') is not None else 10000
        policy=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key='demo/policy'").fetchone()
        # Keep production read credentials saved while a deploy was handing over.
        c.execute("""UPDATE research_job SET idempotency_key='kalshi-demo/'||substring(idempotency_key from 6)
          WHERE idempotency_key>='demo/' AND idempotency_key<'demo/zzzz'
          AND idempotency_key<>'demo/paper-credentials'""")
        for row in bots:
            params=dict(row['parameters']);params.update(revision=params['revision']+1,settings_revision=params.get('settings_revision',params['revision'])+1,paper_source_revision=params['revision'])
            previous=row['progress'];state=dict(desired=previous.get('desired','paused'),state='waiting',message='Production-data paper simulation; waiting for verified market data',archived=previous.get('archived',False))
            c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",(uuid4(),Jsonb(params),Jsonb(state),row['idempotency_key']))
        if policy:
            c.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at) VALUES(%s,'crypto',%s,%s,'demo/policy','succeeded',clock_timestamp())",(uuid4(),Jsonb(policy['parameters']),Jsonb(policy['progress'])))
        marker=dict(source='production_paper',environment='local_paper',changed_at=time.time(),starting_cents=starting,fill_model='conservative_queue_v1',latency_ms=250,real_orders_enabled=False,legacy_namespace='kalshi-demo',message='Production prices; simulated orders and funds. Old Kalshi Demo history is separate.')
        c.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at) VALUES(%s,'crypto','{}'::jsonb,%s,'demo/engine','succeeded',clock_timestamp())",(uuid4(),Jsonb(marker)))
    from .ledger import Ledger
    Ledger(store,guard).initialize(starting)
    store.put('account',dict(cash_cents=starting,equity_cents=starting,position_value_cents=0,held_markets=0,at=time.time(),simulated=True))
    store.put('equity/'+str(int(time.time()//900)),dict(at=time.time(),value=starting))
    for row in bots:
        key=row['idempotency_key'].split('/')[-1]
        store.event('bot_updated','Fresh version for production-data paper trading',bot=key,details=dict(revision=row['parameters']['revision']+1,rule_revision_changed=True,execution_engine_changed=True))
    store.event('engine_changed','Kalshi Demo history archived separately; production-data paper simulation selected',details=marker)
