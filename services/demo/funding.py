"""On-demand, durable transfers of existing Demo collateral between primary shards."""
import math,time
from decimal import Decimal
from uuid import uuid4
from .exchange import ExchangeFailure

class ShardFunding:
    def __init__(self,store,exchange):
        self.store,self.exchange=store,exchange
        self.balances={};self.checked_at=0;self.poll_at=0
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
        if self.pending():return False
        if time.time()-self.checked_at>=30:self.balances_now()
        available={i:max(0,v-reservations.get(i,0)) for i,v in self.balances.items()}
        current=available.get(index,0)
        if current>=required:return True
        donors=sorted(((v,i) for i,v in available.items() if i!=index),reverse=True)
        if not donors or donors[0][0]<required-current:
            self.store.alert('funding','Existing Demo funds are unavailable on this market’s shard; waiting for transferable primary-account cash.',False)
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
        return False
