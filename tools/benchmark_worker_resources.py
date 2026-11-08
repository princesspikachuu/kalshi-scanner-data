"""Local synthetic checkpoint benchmark; never connects to trading or a database.

Run from the repository root with --baseline-ref <commit>. Results describe the
same generated state in both implementations, not production CPU savings.
"""
import argparse,json,statistics,subprocess,time,types
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,StrategyFleet,FeePolicy,Order
from services.paper_demo.shadow.state import encode
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint

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
            start=time.process_time();value=fn(e,f);middle=time.process_time();packed=pack_checkpoint(value);end=time.process_time()
            encoding.append((middle-start)*1000);checkpoint.append((end-start)*1000)
        results[label]=dict(encode_cpu_ms=statistics.median(encoding),checkpoint_cpu_ms=statistics.median(checkpoint),
            decoded_bytes=packed.get('bytes',len(json.dumps(packed))),stored_bytes=len(json.dumps(packed)))
    print(json.dumps(dict(workload=dict(profiles=53,markets=28,orders=280,iterations=21),results=results),indent=2))

if __name__=='__main__':main()
