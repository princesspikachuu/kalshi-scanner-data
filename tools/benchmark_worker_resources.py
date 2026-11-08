"""Local synthetic checkpoint benchmark; never connects to trading or a database.

Run from the repository root with --baseline-ref <commit>. Results describe the
same generated state in both implementations, not production CPU savings.
"""
import argparse,json,statistics,subprocess,time,types,threading,random
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,StrategyFleet,FeePolicy,Order
from services.paper_demo.shadow.state import encode
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint
from services.paper_demo.exchange import Fees
from services.paper_demo.shadow.scalper import bucket

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline-ref',required=True);args=parser.parse_args()
    source=subprocess.run(['git','show',args.baseline_ref+':services/paper_demo/shadow/state.py'],check=True,capture_output=True,text=True).stdout
    old=types.ModuleType('services.paper_demo.shadow.baseline_state');old.__package__='services.paper_demo.shadow';exec(compile(source,'baseline_state.py','exec'),old.__dict__)
    profiles=[dict(series='S'+str(i),name='Synthetic '+str(i),contracts=5) for i in range(53)]
    e=Engine(Mock(),cash='1000');f=StrategyFleet(e,profiles);e.advance(1000)
    for i in range(28):
        ticker='S'+str(i)+'-test';e.add_market(dict(ticker=ticker,open=900,close=1900),FeePolicy())
        e.wallet.stat(ticker);f.halted.add(ticker)
        for j in range(10):
            ident=str(i)+'-'+str(j)
            e.orders[ident]=Order(id=ident,ticker=ticker,side='yes',action='buy',quantity=D(5),price=D('.3'),maker=True,
                phase=1,created=1000,arrives=1000.15,expiry=1010,reference=D('.32'))
    results={}
    for label,fn in [('before',old.encode),('after',encode)]:
        encoding=[];checkpoint=[]
        for _ in range(21):
            start=time.process_time();value=fn(e,f);middle=time.process_time();packed=pack_checkpoint(value,binary=label=='after');end=time.process_time()
            encoding.append((middle-start)*1000);checkpoint.append((end-start)*1000)
        results[label]=dict(encode_cpu_ms=statistics.median(encoding),checkpoint_cpu_ms=statistics.median(checkpoint),
            decoded_bytes=packed.get('bytes',len(json.dumps(packed))),stored_bytes=len(json.dumps(packed)))
    fee_source=subprocess.run(['git','show',args.baseline_ref+':services/paper_demo/exchange.py'],check=True,capture_output=True,text=True).stdout
    fee_old=types.ModuleType('services.paper_demo.baseline_exchange');fee_old.__package__='services.paper_demo';exec(compile(fee_source,'baseline_exchange.py','exec'),fee_old.__dict__)
    fee_reads={}
    for label,cls in [('before',fee_old.Fees),('after',Fees)]:
        calls=[];start=threading.Barrier(4)
        def call(method,path,params=None):
            calls.append(path)
            if path=='/series/S':
                time.sleep(.01)
                return dict(series=dict(fee_type='quadratic',fee_multiplier=1))
            return {'series_fee_change_arr':[]} if path=='/series/fee_changes' else {'event_fee_changes':[]}
        fees=cls(Mock(call=call));now=time.time()
        def load(i):start.wait();fees.load('S-'+str(i),dict(event_ticker='EVENT-'+str(i)),now)
        with ThreadPoolExecutor(max_workers=4) as executor:list(executor.map(load,range(4)))
        fee_reads[label]=len(calls)
    rng=random.Random(7)
    evidence=dict(research=[{k:(rng.random()*1000 if isinstance(v,float) else v) for k,v in bucket().items()} for _ in range(5000)])
    research={}
    for label,binary in [('before',False),('after',True)]:
        samples=[]
        for _ in range(11):
            start=time.process_time();packed=pack_checkpoint(evidence,binary=binary);samples.append((time.process_time()-start)*1000)
        research[label]=dict(checkpoint_cpu_ms=statistics.median(samples),decoded_bytes=packed['bytes'],stored_bytes=len(packed['data']))
    print(json.dumps(dict(workload=dict(profiles=53,markets=28,orders=280,iterations=21),results=results,
        concurrent_fee_reads=fee_reads,research_checkpoint_results=research),indent=2))

if __name__=='__main__':main()
