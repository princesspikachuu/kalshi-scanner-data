"""Reuse the reviewed bot rules, replacing only market source and execution."""
import time
from services.demo.runtime import Worker
from .model import D,decimal

class PaperFunding:
    waits={}
    def __init__(self,exchange):self.exchange=exchange
    def poll(self):pass
    def ensure(self,shard,amount,target,reservations):
        with self.exchange.store.pool.connection() as c:return self.exchange.ledger.free_cash(c)*100>=decimal(amount)

class PaperWorker(Worker):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.funding=PaperFunding(self.exchange)
        self.paper_trade_sid=None;self.fee_refresh_at=0;self.exchange.before_read=self.drain_stream_during_read
        self.exchange.data.before_read=self.drain_stream_during_read
    def poll_funding(self):
        # Fees have no relationship to funding on the real account. Refresh one
        # active market at a time, outside stream consumption, on a fixed budget.
        now=time.time()
        due=[t for t in self.exchange.active_tickers if t in self.exchange.markets and now-self.exchange.fees.cache.get(t,{}).get('at',0)>30]
        if due and now>=self.fee_refresh_at:
            self.fee_refresh_at=now+.5
            ticker=min(due,key=lambda t:self.exchange.fees.cache.get(t,{}).get('at',0))
            try:self.exchange.fees.load(ticker,self.exchange.markets[ticker],now)
            except Exception:self.store.alert('paper-fees-'+ticker,'Paper fills paused for this market: current fees could not be verified.',False)
            else:self.store.clear_alert('paper-fees-'+ticker)
    def trade(self,allow_entries=True):
        self.poll_funding()
        return super().trade(allow_entries)
    def record(self,kind,order,message,**detail):
        message=message.replace('Exchange-confirmed','Simulated').replace('Exchange confirmation','Paper ledger confirmation').replace('Kalshi Demo accepted','Paper engine accepted')
        return super().record(kind,order,message,**dict(detail,simulated=True,market_data='production',fill_model='conservative_queue_v1'))
    def health(self,state,message):
        if state=='ready':message='Production market data verified · simulated orders and funds'
        super().health(state,message)
