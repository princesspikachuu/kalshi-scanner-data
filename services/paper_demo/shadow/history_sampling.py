"""Bounded reporting work, independent of financial execution checkpoints."""
import json,time
from copy import deepcopy
from psycopg.errors import QueryCanceled
from .performance import record_balances
from .bot_performance import record_bot_balances

class MinuteHistory:
    def __init__(self):self.minute=None;self.retry_at=0
    def due(self,now):return int(now//60)!=self.minute and time.monotonic()>=self.retry_at
    def freeze(self,accounts,experiments,now,positions):
        # The sampler needs totals, not every price/time research cell.
        bots={folder:dict(bots={ident:dict(net_realized_pnl=b.get('net_realized_pnl','0'),
            scalper=dict(totals=deepcopy(b['scalper']['totals'])) if b.get('scalper') else None)
            for ident,b in value.get('bots',{}).items()}) for folder,value in experiments.items()}
        return deepcopy(accounts),bots,now,deepcopy(positions)
    async def write(self,audit,store,sample):
        accounts,experiments,now,positions=sample
        try:
            await audit.durable_io(record_balances,store,accounts,now)
            await audit.durable_io(record_bot_balances,store,accounts,experiments,now,positions)
        except QueryCanceled:
            # A failed reporting statement is rolled back by its connection
            # context. Never swallow checkpoint, fencing or cancellation errors.
            self.retry_at=time.monotonic()+30
            print(json.dumps(dict(event='paper_history_sample_deferred',at=now,reason='query_timeout',
                retry_seconds=30,real_orders_enabled=False)),flush=True)
            return
        self.minute=int(now//60);self.retry_at=0
