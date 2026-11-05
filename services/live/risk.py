"""Durable, single-contract LIVE pilot. No automatic expansion or top-ups."""
import time
from decimal import Decimal
from uuid import uuid4
from psycopg.types.json import Jsonb
from services.trading.mode import LOCK as MODE_LOCK,read_mode
from services.demo.exchange import ExchangeFailure

RISK_LOCK=723741942
class RiskBlocked(ValueError):pass

def value(store,key,default=None):
    row=store.get(key);return row['progress'] if row else default

def settings(store):
    result=value(store,'budget')
    if not result or result.get('trial_cap_cents')!=5000 or result.get('loss_limit_cents')!=2500:
        raise RiskBlocked('This pilot requires the approved $50 budget and $25 loss cutoff')
    return result

def initialize_trial(store,exchange,connection_binding):
    settings(store)
    prior=value(store,'trial')
    if prior:
        if prior.get('binding')!=connection_binding:raise RiskBlocked('The trial is bound to a different live account')
        return prior
    orders=list(exchange.pages('/portfolio/orders','orders',status='resting'))
    positions=list(exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
    balance=exchange.call('GET','/portfolio/balance')
    if orders or any(Decimal(str(p.get('position_fp',p.get('position',0)))) for p in positions):
        raise RiskBlocked('Use an empty isolated subaccount without existing orders or positions')
    if balance.get('portfolio_value')!=0 or type(balance.get('balance')) is not int or balance['balance']!=5000:
        raise RiskBlocked('Fund only the isolated subaccount with exactly $50 before the initial check')
    result=dict(binding=connection_binding,initial_cash_cents=5000,reserve_cents=800,loss_limit_cents=2500,
        started_at=time.time(),pilot_contracts=1,entry_claimed=False)
    # Connection and budget edits use the same lock. No key can change halfway
    # through preparing a trial, and restart can never initialize a new trial.
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
        budget=c.execute("SELECT progress FROM research_job WHERE idempotency_key='live/budget'").fetchone()
        connection=c.execute("SELECT progress FROM research_job WHERE idempotency_key='live/credentials'").fetchone()
        if not budget or budget['progress'].get('trial_cap_cents')!=5000 or budget['progress'].get('loss_limit_cents')!=2500 or not connection or connection['progress'].get('binding')!=connection_binding:
            raise RiskBlocked('Live settings changed while preparing the trial')
        c.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at) VALUES(%s,'crypto','{}'::jsonb,%s,'live/trial','succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING",(uuid4(),Jsonb(result)))
    return value(store,'trial')

def loss_state(initial_cash,loss_limit,orders):
    # Worst-case cost of outstanding/held contracts remains reserved until a
    # verified sell, offset or settlement credits the entry's realized result.
    realized=sum(Decimal(str(o.get('realized_cents',0))) for o in orders if o.get('kind')=='entry')
    risk=sum(Decimal(str(o.get('price',0)))*(Decimal(str(o.get('remaining',0)))+max(Decimal(0),Decimal(str(o.get('filled',0)))-Decimal(str(o.get('sold',0)))))
        for o in orders if o.get('kind')=='entry' and 'realized_cents' not in o and o.get('status')!='rejected')
    return dict(realized_cents=float(realized),reserved_cents=float(risk),
        available_cents=int(Decimal(initial_cash)+realized-risk),
        stopped=realized-risk<=-Decimal(loss_limit))

class PilotGuard:
    def __init__(self,store,exchange,binding,fence):self.store,self.exchange,self.binding,self.fence=store,exchange,binding,fence
    def __call__(self,intents):
        self.fence()
        if len(intents)!=1:raise RiskBlocked('The live pilot accepts one order at a time')
        i=intents[0]
        # Fresh exchange inventory protects against a manual sell between the
        # worker's reconciliation and this attempt. Never borrow other lots.
        positions=list(self.exchange.pages('/portfolio/positions','market_positions',count_filter='position'))
        resting=list(self.exchange.pages('/portfolio/orders','orders',status='resting'))
        with self.store.pool.connection() as c:
            c.execute('SELECT pg_advisory_xact_lock(%s)',(MODE_LOCK,))
            c.execute('SELECT pg_advisory_xact_lock(%s)',(RISK_LOCK,))
            mode=c.execute("SELECT progress FROM research_job WHERE idempotency_key='trading/mode'").fetchone()
            if not mode or mode['progress'].get('mode')!='live' or mode['progress'].get('pilot_bot')!=i['bot']:
                raise RiskBlocked('LIVE does not own the trading worker')
            trial=c.execute("SELECT progress FROM research_job WHERE idempotency_key='live/trial' FOR UPDATE").fetchone()
            if not trial or trial['progress'].get('binding')!=self.binding:raise RiskBlocked('Live account binding changed')
            trial=trial['progress']
            row=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('live/order/'+i['client_id'],)).fetchone()
            if not row or c.execute('SELECT 1 FROM research_job WHERE idempotency_key=%s',('live/write/'+i['client_id'],)).fetchone():raise RiskBlocked('A live write cannot be replayed')
            saved=dict(row['parameters'],**row['progress'])
            if any(saved.get(k)!=i.get(k) for k in ('bot','ticker','side','kind','price','quantity','close','revision')):
                raise RiskBlocked('Live order differs from its saved intent')
            bot=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s',('live/bot/'+i['bot'],)).fetchone()
            if not bot:raise RiskBlocked('Live bot missing')
            amount=Decimal(str(i['quantity']))
            if i['side']!='yes' or not amount.is_finite() or not 0<amount<=1 or amount*100!=(amount*100).to_integral_value() or i['close']<=time.time():raise RiskBlocked('Pilot is limited to one YES contract')
            if i['kind']=='entry':
                if amount!=1:raise RiskBlocked('Pilot entry must request exactly one contract')
                if mode['progress'].get('pilot_paused') or trial.get('entry_claimed') or bot['progress'].get('desired')!='running':raise RiskBlocked('Initial execution check already attempted or paused')
                if i['price']!=3 or bot['parameters']['revision']!=i['revision']:raise RiskBlocked('Pilot entry settings changed')
                if resting or any(Decimal(str(p.get('position_fp',p.get('position',0)))) for p in positions):raise RiskBlocked('Unexpected live orders or positions')
                if i['close']-time.time()>300:raise RiskBlocked('Pilot entry expiry is outside the first five minutes')
                trial['entry_claimed']=True
                c.execute("UPDATE research_job SET progress=%s WHERE idempotency_key='live/trial'",(Jsonb(trial),))
            elif i['kind']=='exit':
                parent=c.execute('SELECT parameters,progress FROM research_job WHERE idempotency_key=%s',('live/order/'+str(i.get('parent')),)).fetchone()
                if not parent:raise RiskBlocked('Sell has no owned filled contract')
                owned=Decimal(str(parent['progress'].get('filled',0)))-Decimal(str(parent['parameters'].get('sold',0)))
                if amount>owned:raise RiskBlocked('Sell exceeds the owned filled amount')
                if any(parent['parameters'].get(k)!=i.get(k) for k in ('bot','ticker','side')):raise RiskBlocked('Sell does not match its owned entry')
                if not parent['parameters'].get('late_exit_triggered') or i['price']>parent['parameters'].get('late_exit_ceiling_cents',0):raise RiskBlocked('Sell does not match the latched down-only exit')
                actual=sum(Decimal(str(p.get('position_fp',p.get('position',0)))) for p in positions if p['ticker']==i['ticker'])
                if actual!=owned or amount>actual or resting:raise RiskBlocked('Sell inventory or resting orders require reconciliation')
                if not 0<i['price']<100:raise RiskBlocked('Invalid live sell price')
            else:raise RiskBlocked('Invalid live order role')
            c.execute("INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at) VALUES(%s,'crypto','{}'::jsonb,%s,%s,'succeeded',clock_timestamp())",(uuid4(),Jsonb(dict(at=time.time(),kind=i['kind'],bot=i['bot'])),'live/write/'+i['client_id']))
