"""On-demand, durable transfers of existing Demo collateral between primary shards."""
import math,time
from decimal import Decimal
from uuid import uuid4
from .exchange import ExchangeFailure

def resting_reservation(order):
    """Worst-case cash cost at the limit, without assuming position netting."""
    if order.get('subaccount_number') not in (None,0):return 0
    quantity=Decimal(str(order.get('remaining_count_fp',order.get('remaining_count',0))))
    book=order.get('book_side')
    if book not in ('bid','ask') and order.get('action') in ('buy','sell') and order.get('side') in ('yes','no'):
        book='bid' if (order['action']=='buy')==(order['side']=='yes') else 'ask'
    key='yes_price_dollars' if book=='bid' else 'no_price_dollars' if book=='ask' else None
    price=Decimal(str(order[key]))*100 if key and order.get(key) is not None else Decimal(100)
    if not price.is_finite() or not 0<=price<=100 or not quantity.is_finite() or quantity<0:
        raise ExchangeFailure('shard_reservation_contract')
    return math.ceil(quantity*price)

class ShardFunding:
    def __init__(self,store,exchange):
        self.store,self.exchange=store,exchange
        self.balances={};self.checked_at=0;self.poll_at=0;self.notice_at={}
        self.waits={}
    def balances_now(self):
        rows=self.exchange.call('GET','/portfolio/subaccounts/balances').get('subaccount_balances')
        if not isinstance(rows,list) or len(rows)>6464:raise ExchangeFailure('shard_balance_contract')
        balances={}
        for row in rows:
            if row['subaccount_number']!=0:continue
            index=row['exchange_index']
            if not isinstance(index,int) or not 0<=index<=100 or index in balances:raise ExchangeFailure('shard_balance_contract')
            balances[index]=math.floor(Decimal(str(row['balance']))*100)
        self.balances=balances;self.checked_at=time.time()
        old=self.store.get('alert/funding')
        if old and old['progress'].get('message')=='Existing Demo funds are unavailable on this market’s shard; waiting for transferable primary-account cash.':
            self.store.clear_alert('funding')
    def pending(self):
        row=self.store.get('funding')
        pending=row['progress'] if row else None
        if not pending or pending['status'] in ('complete','rejected'):return False
        now=time.time()
        if now<self.poll_at:return True
        self.poll_at=now+5
        if pending.get('transfer_id'):
            transfer=self.exchange.call('GET','/portfolio/intra_exchange_instance_transfers/'+pending['transfer_id']).get('transfer')
        else:
            # A lost POST response is resolved by its unique client ID, never by
            # repeating the write or assuming that a missing record means failure.
            transfer=None;cursor=None
            for _ in range(5):
                page=self.exchange.call('GET','/portfolio/intra_exchange_instance_transfers',params=dict(limit=200,**({'cursor':cursor} if cursor else {})))
                rows=page.get('transfers')
                if not isinstance(rows,list) or len(rows)>200:raise ExchangeFailure('transfer_history_contract')
                transfer=next((r for r in rows if r.get('client_transfer_id')==pending['body']['client_transfer_id']),None)
                following=page.get('cursor')
                if transfer or not following:break
                if following==cursor:raise ExchangeFailure('invalid_cursor')
                cursor=following
        if not transfer:
            self.store.alert('funding','Demo collateral transfer confirmation is incomplete. New entries wait; no transfer is repeated.',True)
            return True
        body=pending['body']
        if (transfer.get('source')!='event_contract' or transfer.get('destination')!='event_contract'
            or transfer.get('source_exchange_shard')!=body['source_exchange_shard']
            or transfer.get('destination_exchange_shard')!=body['destination_exchange_shard']
            or Decimal(str(transfer.get('amount','-1')))*10000!=body['amount']):
            raise ExchangeFailure('transfer_confirmation_contract')
        pending['transfer_id']=transfer['transfer_id']
        if transfer.get('status')!='complete':
            self.store.put('funding',pending);return True
        self.balances_now() # Verify exchange balances after confirmed completion.
        if self.balances.get(body['destination_exchange_shard'],0)<pending.get('destination_before_cents',0)+body['amount']//100:
            self.store.put('funding',pending);return True
        pending['status']='complete';pending['completed_at']=now
        self.store.put('funding',pending);self.store.clear_alert('funding')
        self.store.event('funding_transfer','Existing Demo funds moved to the trading shard',details=dict(source=body['source_exchange_shard'],destination=body['destination_exchange_shard'],amount_cents=body['amount']//100))
        print(__import__('json').dumps(dict(event='demo_shard_funded',source=body['source_exchange_shard'],destination=body['destination_exchange_shard'],amount_cents=body['amount']//100)),flush=True)
        return False
    def ensure(self,index,required,target,reservations):
        if not isinstance(index,int) or not 0<=index<=100:raise ExchangeFailure('market_shard_contract')
        if self.pending():self.waits[index]=dict(reason='transfer',at=time.time());return False
        if time.time()-self.checked_at>=30:self.balances_now()
        available={i:max(0,v-reservations.get(i,0)) for i,v in self.balances.items()}
        current=available.get(index,0)
        if current>=required:
            self.waits.pop(index,None)
            if index not in self.notice_at or self.notice_at[index]!=-1:
                self.store.clear_alert('funding-cash-'+str(index));self.notice_at[index]=-1
            return True
        donors=sorted(((v,i) for i,v in available.items() if i!=index),reverse=True)
        if not donors or sum(v for v,_ in donors)<required-current:
            self.waits[index]=dict(reason='funding',at=time.time(),required_cents=required,available_cents=current,transferable_cents=sum(v for v,_ in donors),reserved_cents=sum(reservations.values()))
            if time.time()-self.notice_at.get(index,-30)>=30:
                self.store.alert('funding-cash-'+str(index),f'Demo shard {index}: this bid needs ${required/100:.2f}; ${current/100:.2f} available here and ${sum(v for v,_ in donors)/100:.2f} transferable from other shards. Resting orders reserve up to ${sum(reservations.values())/100:.2f}. This entry waits; other funded markets continue. Funds are checked automatically.',False)
                self.notice_at[index]=time.time()
            return False
        free,source=donors[0]
        # Prefund at most the remaining bot budget to avoid a transfer per bid.
        amount=min(free,max(required-current,math.ceil(target)-current))
        body=dict(client_transfer_id=str(uuid4()),source='event_contract',destination='event_contract',
            source_exchange_shard=source,destination_exchange_shard=index,amount=int(amount)*100)
        pending=dict(status='intent',body=body,created_at=time.time(),destination_before_cents=self.balances.get(index,0))
        self.store.put('funding',pending) # Durability before the one network write.
        try:
            response=self.exchange.call('POST','/portfolio/intra_exchange_instance_transfer',body=body)
            identifier=response.get('transfer_id')
            if not isinstance(identifier,str) or not __import__('re').fullmatch(r'[A-Za-z0-9-]{1,128}',identifier):raise ExchangeFailure('transfer_confirmation_contract',True)
            pending.update(status='pending',transfer_id=identifier)
        except ExchangeFailure as error:
            pending['status']='uncertain' if error.ambiguous else 'rejected'
            self.store.put('funding',pending)
            self.store.alert('funding','Demo shard funding could not be verified. Existing funds and orders are retained.',True)
            raise
        self.store.put('funding',pending);self.poll_at=time.time()+2
        self.store.alert('funding','Moving existing Demo funds to the trading shard; matching entries will resume after confirmation.',False)
        self.waits[index]=dict(reason='transfer',at=time.time())
        return False
