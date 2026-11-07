"""Transactional virtual cash, orders and positions in existing durable PostgreSQL.

Every receipt, queue advance, partial fill, fee and cash change commits together.
There is no network client, API signer or production account ID in this ledger.
"""
import time,json,hashlib
from uuid import uuid4
from psycopg.types.json import Jsonb
from .model import D,decimal,charge,queue_ahead,eligible_trade
from services.demo.exchange import ExchangeFailure

PREFIX='demo/paper/'
LOCK=723741945

def get(c,key):
    r=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(PREFIX+key,)).fetchone()
    return r['progress'] if r else None

def put(c,key,data):
    c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
      VALUES(%s,'crypto','{}'::jsonb,%s,%s,'succeeded',clock_timestamp())
      ON CONFLICT(idempotency_key) DO UPDATE SET progress=excluded.progress,finished_at=clock_timestamp()""",(uuid4(),Jsonb(data),PREFIX+key))

def rows(c,kind,ticker=None,min_ts=0):
    found=c.execute("SELECT progress FROM research_job WHERE idempotency_key>=%s AND idempotency_key<%s AND (%s::text IS NULL OR progress->>'ticker'=%s) AND created_at>=to_timestamp(%s) AND (%s<>'position' OR (progress->>'quantity')::numeric<>0) AND (%s<>'resting' OR progress->>'status'='resting') ORDER BY created_at LIMIT 10001",(PREFIX+kind+'/',PREFIX+kind+'/zzzz',ticker,ticker,min_ts,kind,kind)).fetchall()
    if len(found)>10000:raise ExchangeFailure('paper_ledger_capacity')
    return [r['progress'] for r in found]

def save(c,order):
    put(c,'order/'+order['client_id'],order)
    if order['status']=='resting':put(c,'resting/'+order['client_id'],order)
    else:c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(dict(status=order['status'])),PREFIX+'resting/'+order['client_id']))

def wire(order):
    return dict(order_id=order['id'],client_order_id=order['client_id'],ticker=order['ticker'],side=order['side'],action='buy' if order['kind']=='entry' else 'sell',
      status=order['status'],fill_count_fp=order['filled'],remaining_count_fp=order['remaining'],fill_count=float(order['filled']),remaining_count=float(order['remaining']),
      maker_fees_dollars=order['fees'],taker_fees_dollars='0',created_time=order['created_time'],created_ts=order['created_at'],exchange_index=order['exchange_index'],
      yes_price_dollars=order['price_dollars'] if order['side']=='yes' else str(1-decimal(order['price_dollars'])),no_price_dollars=order['price_dollars'] if order['side']=='no' else str(1-decimal(order['price_dollars'])))

class Ledger:
    def __init__(self,store,guard=lambda:None,latency=.25):self.store,self.guard,self.latency=store,guard,latency
    def transaction(self,c):self.guard();c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
    def initialize(self,cents):
        with self.store.pool.connection() as c:
            self.transaction(c)
            if not get(c,'cash'):put(c,'cash',dict(dollars=str(D(cents)/100),starting_cents=cents,created_at=time.time()))
    def orders(self,status=None,ticker=None,min_ts=0):
        with self.store.pool.connection() as c:return rows(c,'resting' if status=='resting' else 'order',ticker,min_ts)
    def free_cash(self,c):
        cash=decimal(get(c,'cash')['dollars'])
        for o in rows(c,'resting'):
            if o['status']!='resting' or o['kind']!='entry':continue
            cost,fee=charge(o['price_dollars'],o['remaining'],o['fee_type'],o['fee_multiplier']);cash-=cost+fee
        return max(D(0),cash)
    def balance(self,quotes):
        with self.store.pool.connection() as c:
            cash=get(c,'cash');positions=rows(c,'position');value=D(0)
            for p in positions:
                q=quotes.get(p['ticker'],{});bid=decimal(q.get('bid',0))/100;ask=decimal(q.get('ask',100))/100
                n=decimal(p['quantity'])
                mark=bid if n>0 else 1-ask
                if not q or not q.get('book_verified'):mark=decimal(p.get('mark_dollars','0'))
                elif p.get('mark_dollars')!=str(mark):p['mark_dollars']=str(mark);put(c,'position/'+p['ticker'],p)
                value+=abs(n)*mark
        return dict(balance=int(decimal(cash['dollars'])*100),portfolio_value=int(value*100))
    def positions(self):
        with self.store.pool.connection() as c:return [dict(ticker=p['ticker'],position_fp=p['quantity']) for p in rows(c,'position') if decimal(p['quantity'])]
    def submit(self,intent,book,q,schedule,now):
        from datetime import datetime,timezone
        p=decimal(intent['price'])/100;n=decimal(intent['quantity'])
        if not 0<p<1 or n<=0 or n!=n.quantize(D('.01')):raise ExchangeFailure('paper_invalid_order')
        if not q.get('book_verified') or not q.get('book_ready') or now-q.get('at',0)>2 or now>=q['close']:raise ExchangeFailure('paper_stale_book')
        bid=decimal(q['bid'])/100;ask=decimal(q['ask'])/100
        if intent['side']=='no':bid,ask=1-ask,1-bid
        if (intent['kind']=='entry' and p>=ask) or (intent['kind']=='exit' and p<=bid):raise ExchangeFailure('exchange_rejected',reason='post_only',status=400)
        kind,multiplier=schedule
        cost,fee=charge(p,n,kind,multiplier)
        with self.store.pool.connection() as c:
            self.transaction(c);old=get(c,'order/'+intent['client_id'])
            if old:return wire(old)
            if intent['kind']=='entry' and cost+fee>self.free_cash(c):raise ExchangeFailure('paper_insufficient_cash')
            if intent['kind']=='exit':
                position=get(c,'position/'+intent['ticker']) or dict(quantity='0')
                held=decimal(position['quantity'])*(1 if intent['side']=='yes' else -1)
                reserved=sum((decimal(o['remaining']) for o in rows(c,'resting') if o['ticker']==intent['ticker'] and o['side']==intent['side'] and o['kind']=='exit' and o['status']=='resting'),D(0))
                if n>held-reserved:raise ExchangeFailure('paper_insufficient_position')
            o=dict(id='paper-'+intent['client_id'],client_id=intent['client_id'],ticker=intent['ticker'],side=intent['side'],kind=intent['kind'],parent=intent.get('parent'),
              quantity=str(n),remaining=str(n),filled='0',price_dollars=str(p),fees='0',status='resting',exchange_index=q.get('exchange_index',0),
              fee_type=kind,fee_multiplier=str(multiplier),created_at=now,created_time=datetime.fromtimestamp(now,timezone.utc).isoformat(),active_at=now+self.latency,
              expires=min(intent.get('entry_expires_at',intent.get('close',q['close'])),q['close']),cancel_at=None,
              queue_ahead=str(queue_ahead(book,intent['side'],intent['kind'],p)),needs_requeue=False)
            save(c,o)
            return wire(o)
    def cancel(self,identifier,now):
        key=identifier.removeprefix('paper-')
        with self.store.pool.connection() as c:
            self.transaction(c);o=get(c,'order/'+key)
            if not o:raise ExchangeFailure('paper_order_not_found',status=404)
            # Ack is immediate locally, but execution remains possible until the
            # modeled cancellation reaches the exchange; reservations stay held.
            if o['status']=='resting' and o.get('cancel_at') is None:
                o['cancel_at']=now+self.latency;save(c,o)
            return dict(order=wire(o))
    def expire(self,now):
        with self.store.pool.connection() as c:
            self.transaction(c)
            for o in rows(c,'resting'):
                if o['status']=='resting' and now>=min(o['expires'],o.get('cancel_at') or float('inf')):
                    o.update(status='canceled',remaining='0');save(c,o)
    def requeue(self,ticker,book):
        with self.store.pool.connection() as c:
            self.transaction(c)
            for o in rows(c,'resting'):
                if o['ticker']==ticker and o['status']=='resting' and o.get('needs_requeue'):
                    o.update(queue_ahead=str(max(decimal(o['queue_ahead']),queue_ahead(book,o['side'],o['kind'],o['price_dollars']))),needs_requeue=False)
                    save(c,o)
    def gap(self):
        with self.store.pool.connection() as c:
            self.transaction(c)
            for o in rows(c,'resting'):
                if o['status']=='resting':o['needs_requeue']=True;save(c,o)
    def trade(self,trade,q,now,schedule=None):
        ticker=trade.get('market_ticker');identifier=trade.get('trade_id')
        if not isinstance(identifier,str) or not 1<=len(identifier)<=128:return False
        if q and q.get('paper_epoch_at') is not None:
            try:
                event_at=decimal(trade['ts_ms'])/1000 if trade.get('ts_ms') is not None else decimal(trade['ts'])
                if event_at<=decimal(q['paper_epoch_at']):return False
            except Exception:return False
        if not q or not q.get('book_ready') or not q.get('book_verified') or now-q.get('at',0)>2 or now>=q['close']:return False
        changed=False
        with self.store.pool.connection() as c:
            self.transaction(c);orders=[o for o in rows(c,'resting',ticker) if o['ticker']==ticker and o['status']=='resting' and not o.get('needs_requeue')]
            if not orders:return False
            receipt='trade/'+hashlib.sha256(identifier.encode()).hexdigest()
            if get(c,receipt):return False
            eligible=[o for o in orders if eligible_trade(o,trade,now) is not None]
            if not eligible:return False
            available=decimal(trade['count_fp']);cash=get(c,'cash');position=get(c,'position/'+ticker) or dict(ticker=ticker,quantity='0')
            # A public print's volume is shared across every simulated bot/order.
            for o in sorted(eligible,key=lambda o:(( -decimal(o['price_dollars']) if o['kind']=='entry' else decimal(o['price_dollars'])),o['created_at'],o['client_id'])):
                ahead=min(available,decimal(o['queue_ahead']));available-=ahead;o['queue_ahead']=str(decimal(o['queue_ahead'])-ahead)
                quantity=min(available,decimal(o['remaining']))
                if quantity>0:
                    if schedule:o['fee_type'],o['fee_multiplier']=schedule[0],str(schedule[1])
                    p=decimal(o['price_dollars']);cost,fee=charge(p,quantity,o['fee_type'],o['fee_multiplier'])
                    sign=1 if o['side']=='yes' else -1;held=decimal(position['quantity'])
                    if o['kind']=='exit':quantity=min(quantity,max(D(0),held*sign));cost,fee=charge(p,quantity,o['fee_type'],o['fee_multiplier']) if quantity else (D(0),D(0))
                    if quantity:
                        if o['kind']=='entry':
                            offset=min(quantity,max(D(0),-held*sign));cash['dollars']=str(decimal(cash['dollars'])-cost-fee+offset);held+=quantity*sign
                        else:cash['dollars']=str(decimal(cash['dollars'])+cost-fee);held-=quantity*sign
                        if decimal(cash['dollars'])<0:raise ExchangeFailure('paper_cash_invariant')
                        position['quantity']=str(held)
                        if held*sign>0 and o['kind']=='entry':position['mark_dollars']=str(p)
                        o['filled']=str(decimal(o['filled'])+quantity);o['remaining']=str(decimal(o['remaining'])-quantity);o['fees']=str(decimal(o['fees'])+fee)
                        if not decimal(o['remaining']):o['status']='executed'
                        available-=quantity;changed=True
                        fill=dict(trade_id=identifier,order_id=o['id'],client_order_id=o['client_id'],ticker=ticker,side=o['side'],action='buy' if o['kind']=='entry' else 'sell',count_fp=str(quantity),price_dollars=str(p),fee_dollars=str(fee),created_time=now,evidence='production trade + conservative queue estimate')
                        put(c,'fill/'+str(uuid4()),fill)
                save(c,o)
                if available<=0:break
            put(c,receipt,dict(at=now));put(c,'cash',cash);put(c,'position/'+ticker,position)
        return changed
    def settle(self,raw):
        ticker=raw.get('ticker');result=raw.get('result')
        if raw.get('status') not in ('settled','finalized') or result not in ('yes','no'):return
        with self.store.pool.connection() as c:
            self.transaction(c)
            if get(c,'settlement/'+ticker):return
            p=get(c,'position/'+ticker);cash=get(c,'cash')
            if not cash:return
            n=decimal(p['quantity']) if p else D(0)
            payout=max(D(0),n) if result=='yes' else max(D(0),-n)
            cash['dollars']=str(decimal(cash['dollars'])+payout);put(c,'cash',cash)
            if p:p['quantity']='0';put(c,'position/'+ticker,p)
            for o in rows(c,'resting'):
                if o['ticker']==ticker and o['status']=='resting':o.update(status='canceled',remaining='0');save(c,o)
            put(c,'settlement/'+ticker,dict(ticker=ticker,result=result,payout_dollars=str(payout),at=time.time()))
