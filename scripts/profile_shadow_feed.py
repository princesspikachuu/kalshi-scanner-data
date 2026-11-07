"""CPU-only synthetic benchmark: python -m scripts.profile_shadow_feed.

Not an exchange latency or profit estimate. Exercises 28 books with 257 depth
levels and 10,000 sequenced updates. Audit/HTTP are excluded to isolate compute.
"""
import time,cProfile,pstats
from decimal import Decimal as D
from services.paper_demo.shadow.core import Engine,StrategyFleet,FeePolicy
from services.paper_demo.shadow.host import HostedRun
from services.paper_demo.exchange import Fees
class Audit:
 def log(self,*a,**k):pass
run=object.__new__(HostedRun);e=run.engine=Engine(Audit());e.advance(1000)
fleet=StrategyFleet(e,[dict(series='S'+str(i),name='Bot',contracts=1) for i in range(28)])
fees=run.verified_fees=Fees(None)
for i in range(28):
 t='S'+str(i)+'-test';e.add_market(dict(ticker=t,close=1900),FeePolicy());fees.cache[t]=dict(at=time.time(),base=('quadratic',1),changes=[],events=[])
 e.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=i+1,msg=dict(market_ticker=t,yes_dollars_fp=[[str(D(j)/1000),'10'] for j in range(1,43)],no_dollars_fp=[[str(D(j)/1000),'10'] for j in range(1,216)])),1000)
 e.wallet.stat(t).valid=False
for i in range(60):e.spot.add(100000+i*.01,940+i,940+i)
pr=cProfile.Profile();at=time.perf_counter();pr.enable()
for i in range(10000):
 now=1000+i*.0001;t='S'+str(i%28)+'-test'
 p=dict(type='orderbook_delta',sid=1,seq=i+29,msg=dict(market_ticker=t,side='yes',price_dollars='.01',delta_fp='0'))
 p=run.prepare_fees('kalshi',p,now);e.handle('kalshi',p,now)
pr.disable();print('seconds',time.perf_counter()-at);pstats.Stats(pr).sort_stats('tottime').print_stats(15)
