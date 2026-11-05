"""One-contract LIVE pilot on the same exclusive fence as Demo."""
import os,time,json
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from services.demo.runtime import Worker,LOCK
from services.demo.exchange import DemoSigner,ExchangeFailure
from services.trading.mode import read_mode,LOCK as MODE_LOCK
from .exchange import LiveExchange,load_connection,LiveConnectionError
from .store import LiveStore
from .risk import PilotGuard,RiskBlocked,initialize_trial,value,loss_state
from .fees import zero_maker_fees

class TrialFunding:
    waits={}
    def __init__(self,worker):self.worker=worker
    def ensure(self,shard,amount,target,reservations):
        # No transfers. Funding is a separate, user-controlled setup step.
        # The configured full-size amount is clamped to one 3c contract by
        # the pilot. Verify cash on this market's actual exchange index; an
        # aggregate $50 balance does not prove this shard can fund the bid.
        if self.worker.account.get('cash_cents',0)<3:return False
        balance=self.worker.exchange.call('GET','/portfolio/balance',params=dict(exchange_index=shard))
        if balance.get('balance',0)<3:
            self.worker.funding_message=f'The pilot market uses exchange index {shard}, where its isolated subaccount needs at least 3 cents. Move existing trial cash there through Kalshi setup; the worker cannot transfer funds.'
            self.worker.store.alert('funding',self.worker.funding_message,True)
            return False
        self.worker.funding_message=None;self.worker.store.clear_alert('funding');return True
    def poll(self):pass

class LiveWorker(Worker):
    namespace='live'
    def __init__(self,store,exchange,stop,guard,binding):
        super().__init__(store,exchange,stop,guard)
        self.binding=binding;self.funding=TrialFunding(self);self.fee_verified={};self.trial=None;self.backup_verified=False;self.funding_message=None
        self.exchange.order_guard=PilotGuard(store,exchange,binding,guard)
    def record(self,kind,order,message,**detail):
        return super().record(kind,order,message.replace('Kalshi Demo','Kalshi LIVE'),**detail)
    def load_bots(self):
        super().load_bots()
        mode=read_mode(self.store.pool)
        # Never include an accidentally resumed second bot in the execution set.
        for bot in self.bots:
            if bot['id']!=mode.get('pilot_bot'):bot['desired']='paused'
    def retry_cycle_rejection(self,order):
        if order['kind']=='entry':return False # A pilot cannot change its 3c entry or re-enter.
        return super().retry_cycle_rejection(order)
    def submit(self,intent,confirmation=None,prepared=False):
        if intent['kind']=='entry':
            if value(self.store,'trial',{}).get('entry_claimed') or read_mode(self.store.pool).get('pilot_paused'):return False
            if intent['side']!='yes':return False
            intent=dict(intent,quantity=1)
            q=self.quotes.get(intent['ticker'],{})
            if not q.get('open',float('inf'))<=time.time()<q.get('open',0)+300:return False
            key=intent['ticker']
            if time.time()-self.fee_verified.get(key,0)>30:
                zero_maker_fees(self.exchange,q['series'],key.rsplit('-',1)[0],q['close'])
                self.fee_verified[key]=time.time()
        return super().submit(intent,confirmation,prepared)
    def reconcile(self):
        super().reconcile()
        rows=[dict(r['parameters'],**r['progress']) for r in self.store.rows('order/',500)]
        trial=value(self.store,'trial')
        if not trial:raise RiskBlocked('Live trial has not been initialized')
        limits=loss_state(trial['initial_cash_cents'],trial['loss_limit_cents'],rows)
        self.store.put('risk',dict(limits,at=time.time(),loss_limit_cents=2500,trial_cap_cents=5000,reserve_cents=800))
        self.account['exchange_equity_cents']=self.account['equity_cents']
        self.account['equity_cents']=5000
        self.account['cash_cents']=max(0,min(self.account['cash_cents'],limits['available_cents']-800))
        self.store.put('account',self.account)
        if limits['stopped']:
            self.pause('The $25 loss cutoff stopped new buys; existing exits remain managed')
        if trial.get('entry_claimed') and rows and all(o.get('status') in ('closed','rejected') for o in rows):
            self.pause('Execution check finished. Review its orders and fills before expanding the trial.')
            self.store.put('pilot-result',dict(at=time.time(),complete=True,message='One-contract check finished; all LIVE bots remain paused.'))
    def pause(self,message):
        with self.store.pool.connection() as c:
            c.execute("UPDATE research_job SET progress=progress||%s WHERE idempotency_key>='live/bot/' AND idempotency_key<'live/bot/zzzz'",(Jsonb(dict(desired='paused',message=message)),))
        for b in self.bots:b['desired']='paused'
    def loop(self):
        self.restore_market_activity();controls_at=0;discovery_at=0;backup_at=0
        try:
            self.trial=initialize_trial(self.store,self.exchange,self.binding)
            # Authority comes from the manual Start pilot request stored before
            # the Demo drain. Restart preserves its one-entry durable limit.
            mode=read_mode(self.store.pool)
            if not self.trial.get('entry_claimed') and not mode.get('pilot_paused'):
                with self.store.pool.connection() as c:
                    c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
                    current=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode'").fetchone()
                    if current and current['progress'].get('mode')=='live' and not current['progress'].get('pilot_paused'):
                        c.execute("UPDATE research_job SET progress=progress||'{\"desired\":\"running\"}'::jsonb WHERE idempotency_key=%s",('live/bot/'+current['progress']['pilot_bot'],))
            self.load_bots();self.reconcile()
            while not self.stop.is_set():
                try:
                    self.guard();now=time.time()
                    mode=read_mode(self.store.pool)
                    if mode.get('mode')!='live':return
                    if value(self.store,'pilot-result',{}).get('complete'):
                        self.close_stream();self.health('paused','One-contract execution check finished; review before expansion')
                        self.stop.wait(2);continue
                    if now>=controls_at:
                        self.load_bots();controls_at=now+2
                    if now>=backup_at:
                        from services.demo.maintenance import backup,object_store
                        try:
                            backup(self.store,object_store(os.environ));backup_at=now+300;self.backup_verified=True
                        except Exception as error:
                            self.backup_verified=False;backup_at=now+30
                            self.store.alert('backup','Live control backup could not be verified; new entries remain paused',True)
                            print(json.dumps(dict(event='live_backup_failed',error_type=type(error).__name__)),flush=True)
                    self.probe_market_activity(now)
                    if now>=discovery_at:
                        self.discover();discovery_at=now+2
                    self.stream(wait=False)
                    self.refresh_market_activity(time.time())
                    if not self.recovered or now-self.last_reconcile>=10:self.reconcile()
                    self.service_urgent_exits()
                    trial=value(self.store,'trial',{})
                    self.trade(allow_entries=not trial.get('entry_claimed') and self.backup_verified)
                    if not self.backup_verified:self.health('attention','Live control backup is not verified; new buys remain paused')
                    elif self.funding_message:self.health('attention',self.funding_message)
                    elif self.market_inactive and any(b['desired']=='running' for b in self.bots):self.health('attention','The selected market is inactive; checking again in 15 minutes. Existing positions remain managed.')
                    else:self.health('ready' if self.recovered else 'reconciling','LIVE one-contract check · Demo is paused')
                    self.stop.wait(.1)
                except (ExchangeFailure,RiskBlocked,LiveConnectionError) as error:
                    self.recovered=False
                    message=str(error) if isinstance(error,(RiskBlocked,LiveConnectionError)) else 'LIVE exchange verification failed; entries wait for recovery'
                    self.store.alert('execution',message,True);self.health('attention',message)
                    # Keep recovering existing positions. A failed backup or
                    # unclear exchange write never authorizes an extra entry.
                    self.stop.wait(2)
        finally:self.close_stream()

def run(stop):
    with ConnectionPool(os.environ['DATABASE_URL'],min_size=1,max_size=3,kwargs=dict(row_factory=dict_row,connect_timeout=5,options='-c statement_timeout=5000')) as pool:
        store=LiveStore(pool)
        with pool.connection() as lock:
            while not stop.is_set():
                owned=lock.execute('SELECT pg_try_advisory_lock(%s) AS owned',(LOCK,)).fetchone()['owned'];lock.commit()
                if owned:break
                stop.wait(2)
            if stop.is_set():return
            def fence():
                if lock.closed:raise RuntimeError('Trading fence lost')
                row=lock.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND objid=%s) AS owned",(LOCK,)).fetchone();lock.commit()
                if not row['owned'] or read_mode(pool).get('mode')!='live':raise RuntimeError('LIVE trading fence lost')
            try:
                data=load_connection(store,os.environ.get('DEMO_VAULT_KEY'))
                if not data:raise RiskBlocked('Connect the LIVE subaccount before execution checks')
                exchange=LiveExchange(DemoSigner(data['key_id'],data['pem']),data['subaccount'],guard=fence)
                try:
                    exchange.verify_scope()
                    LiveWorker(store,exchange,stop,fence,data['binding']).loop()
                finally:exchange.close()
            except (RiskBlocked,LiveConnectionError,ExchangeFailure):
                store.put('health',dict(at=time.time(),state='attention',message='LIVE setup needs verification. No new orders submitted.'))
                stop.wait(5)
            finally:
                if not lock.closed:lock.execute('SELECT pg_advisory_unlock(%s)',(LOCK,));lock.commit()
