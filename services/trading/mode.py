"""Exclusive worker mode. Switching never silently abandons managed inventory."""
import time
from uuid import uuid4
from psycopg.types.json import Jsonb

KEY='trading/mode'
LOCK=723741941

class ModeConflict(ValueError):pass

def require_demo(connection):
    # Same lock and transaction as a handover: resume cannot race the pause.
    connection.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
    row=connection.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(KEY,)).fetchone()
    if row and row['progress'].get('mode')!='demo':
        raise ModeConflict('Demo bots cannot resume while LIVE is selected or a handover is pending')

def read_mode(pool):
    with pool.connection() as c:
        row=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(KEY,)).fetchone()
    return row['progress'] if row else dict(mode='demo',requested='demo',at=0)

def write_mode(c,state):
    state=dict(state,at=time.time())
    c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
        VALUES(%s,'crypto','{}'::jsonb,%s,%s,'succeeded',clock_timestamp())
        ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,finished_at=clock_timestamp()""",
        (uuid4(),Jsonb(state),KEY))

def request_live(pool,bot,revision,preflight_token=None):
    with pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        current=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(KEY,)).fetchone()
        if current and current['progress'].get('mode')!='demo':raise ModeConflict('A trading-mode handover is already active')
        row=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE",('live/bot/'+bot,)).fetchone()
        if not row or row['parameters']['settings_revision']!=revision:raise ValueError('Live bot settings changed; reload first')
        if preflight_token is not None:
            check=c.execute("SELECT progress FROM research_job WHERE idempotency_key='live/preflight'").fetchone()
            credentials=c.execute("SELECT progress FROM research_job WHERE idempotency_key='live/credentials'").fetchone()
            budget=c.execute("SELECT progress FROM research_job WHERE idempotency_key='live/budget'").fetchone()
            if not check or not credentials or not budget:raise ModeConflict('Verify the live account first')
            check=check['progress']
            if (check.get('token')!=preflight_token or check.get('bot')!=bot or check.get('settings_revision')!=revision
                or time.time()-check.get('at',0)>60 or check.get('binding')!=credentials['progress'].get('binding')
                or budget['progress'].get('trial_cap_cents')!=5000 or budget['progress'].get('loss_limit_cents')!=2500):
                raise ModeConflict('Live preflight expired or settings changed; verify again')
        c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"paused\",\"state\":\"paused\"}'::jsonb WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz'")
        c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"paused\",\"state\":\"paused\"}'::jsonb WHERE idempotency_key>='live/bot/' AND idempotency_key<'live/bot/zzzz'")
        write_mode(c,dict(mode='draining_demo',requested='live',drain_started_at=time.time(),pilot_bot=bot,pilot_contracts=1,message='Demo bots paused; waiting for verified Demo order cancellation and flat active markets.'))

def demo_resume_allowed(pool):
    return read_mode(pool)['mode']=='demo'

def complete_demo_drain(worker):
    """Called only after fresh Demo reconciliation, under the trading fence."""
    state=read_mode(worker.store.pool)
    if state.get('mode')!='draining_demo' or state.get('requested')!='live':return False
    if not worker.recovered or worker.last_reconcile<state.get('drain_started_at',float('inf')):return False
    now=time.time()
    # An expired local intent is still ambiguous until reconciliation resolves it.
    if any(o.get('status') in ('intent','uncertain','cancel_pending') for o in worker.orders):return False
    if any(b.get('desired')=='running' for b in worker.bots):return False
    if getattr(worker,'mode_drain_checked_revision',None)==worker.last_reconcile:return False
    worker.mode_drain_checked_revision=worker.last_reconcile
    worker.guard()
    # Read the exchange directly. Include manual orders and inventory rather than
    # trusting only our ledger or assuming a closed market has settled.
    remote=list(worker.exchange.pages('/portfolio/orders','orders',status='resting'))
    positions=list(worker.exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
    if remote or any(float(p.get('position_fp',p.get('position',0)) or 0)!=0 for p in positions):
        worker.store.put('mode-drain',dict(at=now,message='Waiting for Demo orders and positions to clear before LIVE can run.'))
        return False
    if worker.stream_event_revision!=getattr(worker,'drain_feed_revision',worker.stream_event_revision):return False
    with worker.store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        row=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',(KEY,)).fetchone()
        if not row or row['progress'].get('mode')!='draining_demo' or row['progress'].get('requested')!='live':return False
        write_mode(c,dict(row['progress'],mode='live',demo_drained_at=now,message='Demo order management is drained; LIVE worker may perform preflight.'))
    return True
