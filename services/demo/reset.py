"""Durable primary-account Demo cleanup. IOC reduce-only sales are reset-only."""
import json,time
from decimal import Decimal
from uuid import UUID,uuid4,uuid5,NAMESPACE_URL
from pydantic import BaseModel,ConfigDict,Field
from psycopg.types.json import Jsonb
from .exchange import ExchangeFailure

ACTIVE={'requested','canceling','closing','verifying','waiting','awaiting_funds','attention'}
class ResetRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_id:UUID
    fresh_bots:bool=True
    target_balance_cents:int|None=Field(default=None,ge=100,le=10000000)

class ResetConflict(ValueError):pass

def request_reset(store,request):
    identifier=str(request.request_id)
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(723741930)')
        old=c.execute("SELECT parameters,progress FROM research_job WHERE idempotency_key='demo/reset' FOR UPDATE").fetchone()
        if old and old['parameters']['request_id']==identifier:return dict(old['parameters'],**old['progress'])
        if old and old['progress']['state'] in ACTIVE:raise ResetConflict('A Demo reset is already in progress')
        bots=c.execute("SELECT idempotency_key,parameters,progress FROM research_job WHERE idempotency_key>='demo/bot/' AND idempotency_key<'demo/bot/zzzz' FOR UPDATE").fetchall()
        sources=[]
        for b in bots:
            if not b['progress'].get('archived'):
                key=b['idempotency_key'].split('/')[-1]
                sources.append(dict(old=key,new=str(uuid5(NAMESPACE_URL,'demo-reset/'+identifier+'/'+key)),config=b['parameters']['config']))
        if request.fresh_bots and len(bots)+len(sources)>100:raise ResetConflict('There is not enough bot capacity to create fresh copies; choose close positions without copying bots')
        for b in bots:
            state=dict(b['progress'],desired='paused',message='Demo reset: new entries paused')
            c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),b['idempotency_key']))
        params=dict(request_id=identifier,fresh_bots=request.fresh_bots,target_balance_cents=request.target_balance_cents,sources=sources,requested_at=time.time())
        state=dict(state='requested',message='Pausing bots and verifying all primary-account Demo orders and positions',pending=None,attempt=0,cloned=False,at=time.time())
        c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
            VALUES(%s,'crypto',%s,%s,'demo/reset','succeeded',clock_timestamp())
            ON CONFLICT(idempotency_key) DO UPDATE SET parameters=excluded.parameters,progress=excluded.progress,finished_at=clock_timestamp()""",(uuid4(),Jsonb(params),Jsonb(state)))
    store.event('reset_requested','Demo cleanup requested: cancel all open orders and close primary-account holdings; bot history retained')
    return dict(params,**state)

def reset_payload(ticker,position,client_id,market=None):
    size=Decimal(str(position))
    if not size.is_finite() or not size or size!=size.quantize(Decimal('.01')):raise ValueError('Invalid reset quantity')
    low,high=Decimal('.01'),Decimal('.99')
    ranges=(market or {}).get('price_ranges') or []
    if len(ranges)>20:raise ValueError('Invalid reset price ranges')
    for band in ranges:
        start,end,step=(Decimal(str(band[k])) for k in ('start','end','step'))
        if not all(v.is_finite() for v in (start,end,step)) or not 0<step<=1:raise ValueError('Invalid reset tick')
        if start==0:low=step
        if end==1:high=1-step
    if not 0<low<=high<1:raise ValueError('Invalid reset price bounds')
    # Use valid extreme ticks so sub-cent liquidity can also close a remainder.
    # Reduce-only prevents opening/reversing exposure even if positions change.
    return dict(ticker=ticker,client_order_id=client_id,side='ask' if size>0 else 'bid',
        count=f'{abs(size):.2f}',price=f'{low if size>0 else high:.4f}',
        time_in_force='immediate_or_cancel',post_only=False,reduce_only=True,
        self_trade_prevention_type='taker_at_cross',subaccount=0,exchange_index=-1)

def archive_and_clone(store,params,*,retire_orders=True):
    with store.pool.connection() as c:
        c.execute('SELECT pg_advisory_xact_lock(723741930)')
        for source in params['sources']:
            row=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s FOR UPDATE',('demo/bot/'+source['old'],)).fetchone()
            if row:
                state=dict(row['progress'],desired='paused',archived=params['fresh_bots'],message='Paused for Demo reset; historical orders and statistics retained')
                c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),'demo/bot/'+source['old']))
            if params['fresh_bots']:
                config=dict(source['config'],name=(source['config']['name'][:72]+' · fresh'))
                c.execute("""INSERT INTO research_job(id,asset,parameters,progress,idempotency_key,status,finished_at)
                    VALUES(%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp()) ON CONFLICT(idempotency_key) DO NOTHING""",
                    (UUID(source['new']),Jsonb(dict(config=config,revision=1,reset_source=source['old'])),
                     Jsonb(dict(desired='paused',archived=False,state='paused',message='Fresh statistics; paused until reset and funding are verified')),'demo/bot/'+source['new']))
        if not retire_orders:return
        # Open entry records are retired only after exchange verification proves
        # zero positions/orders. Completed history is never modified or deleted.
        rows=c.execute("""SELECT idempotency_key,progress FROM research_job WHERE idempotency_key>='demo/order/' AND idempotency_key<'demo/order/zzzz'
            AND progress->>'status' NOT IN ('closed','rejected') FOR UPDATE""").fetchall()
        for row in rows:
            state=dict(row['progress'],status='closed',remaining=0,closed_at=time.time(),reset_closed=True)
            c.execute('UPDATE research_job SET progress=%s WHERE idempotency_key=%s',(Jsonb(state),row['idempotency_key']))

class ResetController:
    def __init__(self,store,exchange):self.store,self.exchange=store,exchange;self.next_check=0;self.last_logged=None
    def save(self,row,**changes):
        row['progress'].update(changes,at=time.time());self.store.put('reset',row['progress'])
        summary={k:row['progress'].get(k) for k in ('state','message','open_orders','held_markets','cash_cents','deposit_needed_cents','cloned','market','market_status','close_time')}
        summary['target_balance_cents']=row['parameters']['target_balance_cents']
        summary['fresh_bots']=len(row['parameters']['sources']) if row['progress'].get('cloned') and row['parameters']['fresh_bots'] else 0
        packed=json.dumps(summary,sort_keys=True)
        if packed!=self.last_logged:
            print(json.dumps(dict(event='demo_reset_progress',**summary)),flush=True);self.last_logged=packed
    def step(self,row):
        now=time.time()
        if now<self.next_check:return
        self.next_check=now+2
        p=row['parameters'];s=row['progress'];pending=s.get('pending')
        if not s.get('cloned'):
            # Preparing paused identities is independent of exchange settlement.
            # Old exposure and order records remain tracked until verified clear.
            archive_and_clone(self.store,p,retire_orders=False)
            self.save(row,cloned=True)
            self.store.event('reset_bots_prepared','Fresh paused bot copies prepared; previous exposure and history remain tracked')
        if pending:
            if pending.get('exchange_id'):
                result=self.exchange.call('GET','/portfolio/orders/'+pending['exchange_id']);order=result.get('order',result)
            else:
                order=next((o for o in self.exchange.pages('/portfolio/orders','orders',min_ts=int(pending['created_at'])-60,subaccount=0)
                    if o.get('client_order_id')==pending['client_id']),None)
            if order is None:
                self.save(row,state='attention',message='A cleanup sale has no verified exchange result. No write will be repeated. Review Activity.',pending=pending)
                self.next_check=now+30;return
            if order.get('status')=='resting':
                self.exchange.cancel(order['order_id'],pending['ticker'])
                self.next_check=now+2;return
            if order.get('status') not in ('executed','canceled','cancelled'):
                self.save(row,state='attention',message='The cleanup sale is not yet terminal; waiting for exchange verification')
                self.next_check=now+30;return
            self.store.event('reset_sale_verified','Exchange verified a reset-only reduce-only sale',ticker=pending['ticker'],details=dict(exchange_id=order['order_id'],filled=order.get('fill_count_fp',order.get('fill_count')),status=order['status']))
            self.save(row,pending=None,scan_index=s.get('scan_index',0)+1,state='verifying',message='Verifying remaining holdings after the cleanup sale' if Decimal(str(order.get('fill_count_fp',order.get('fill_count',0)))) else 'No contracts filled; waiting for available Demo liquidity before another attempt')
            self.next_check=now+(5 if Decimal(str(order.get('fill_count_fp',order.get('fill_count',0)))) else 30);return
        orders=list(self.exchange.pages('/portfolio/orders','orders',status='resting',subaccount=0))
        positions=list(self.exchange.pages('/portfolio/positions','market_positions',count_filter='position',subaccount=0))
        holdings=[(r['ticker'],Decimal(str(r.get('position_fp',r.get('position',0))))) for r in positions if Decimal(str(r.get('position_fp',r.get('position',0))))]
        if len(orders)>500 or len(holdings)>100:raise ExchangeFailure('reset_capacity')
        balance=self.exchange.call('GET','/portfolio/balance')
        account=dict(cash_cents=int(balance['balance']),position_value_cents=int(balance['portfolio_value']),equity_cents=int(balance['balance'])+int(balance['portfolio_value']),at=now,held_markets=len(holdings))
        self.store.put('account',account)
        self.save(row,open_orders=len(orders),held_markets=len(holdings),cash_cents=account['cash_cents'],deposit_needed_cents=max(0,p['target_balance_cents']-account['cash_cents']) if p['target_balance_cents'] is not None else 0)
        if orders:
            order=orders[0]
            self.save(row,state='canceling',message=f'Canceling open Demo orders: {len(orders)} remaining')
            self.exchange.cancel(order['order_id'],order['ticker'])
            self.store.event('reset_cancel','Open order canceled for Demo reset',ticker=order['ticker'],details=dict(exchange_id=order['order_id']))
            return
        if holdings:
            ticker,position=holdings[s.get('scan_index',0)%len(holdings)]
            result=self.exchange.call('GET','/markets/'+ticker);market=result.get('market',result)
            if market.get('status')!='active':
                self.save(row,state='waiting',message='A held market is closed and cannot be sold; waiting for exchange settlement',market=ticker,market_status=market.get('status'),close_time=market.get('close_time'),scan_index=s.get('scan_index',0)+1)
                self.next_check=now+30;return
            attempt=s.get('attempt',0)+1;client_id=str(uuid5(NAMESPACE_URL,'demo-reset-sale/'+p['request_id']+'/'+str(attempt)))
            body=reset_payload(ticker,position,client_id,market)
            pending=dict(client_id=client_id,ticker=ticker,body=body,created_at=now)
            # The intent is durable before the one POST. Lost responses are
            # searched by this ID and never blindly replayed.
            self.save(row,state='closing',message=f'Closing {len(holdings)} held Demo markets with reset-only immediate sales',pending=pending,attempt=attempt)
            self.store.event('reset_sale_intent','Prepared a reset-only immediate reduce-only sale',ticker=ticker,details=dict(client_id=client_id,quantity=body['count'],position=str(position)))
            try:
                result=self.exchange.call('POST','/portfolio/events/orders',body=body)
                pending['exchange_id']=result['order_id']
                self.save(row,pending=pending)
            except ExchangeFailure as error:
                if error.ambiguous:
                    self.save(row,state='attention',message='Cleanup sale confirmation is incomplete; checking history before any further sale',pending=pending)
                else:
                    self.save(row,state='waiting',message='Kalshi rejected the cleanup sale; holdings remain visible and verification will retry',pending=None)
                    self.next_check=now+30
                raise
            return
        if not s.get('market_cleared_at'):
            archive_and_clone(self.store,p)
            self.save(row,market=None,market_status=None,close_time=None,market_cleared_at=now)
            self.store.event('reset_markets_cleared','Verified zero open orders and positions; old bots archived and fresh paused copies prepared')
        if p['target_balance_cents'] is None or account['cash_cents']==p['target_balance_cents']:
            self.save(row,state='complete',message='Demo reset complete. Zero open orders and positions; target balance verified. Fresh bots are paused.',completed_at=now)
            self.store.event('reset_complete','Demo reset and target balance verified; fresh bots remain paused')
        else:
            self.save(row,state='awaiting_funds',message='Markets cleared and fresh bots paused. Add the displayed mock deposit in Kalshi Demo to reach the target balance.' if account['cash_cents']<p['target_balance_cents'] else 'Markets cleared; cash is above the target. No balance adjustment has been invented.')
            self.next_check=now+30
