"""Synthetic, reproducible checkpoint comparison; does not access market data or secrets."""
import argparse,json,statistics,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services.paper_demo.shadow.scalper import bucket
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint,unpack_checkpoint
from services.paper_demo.shadow.checkpoint_segments import CheckpointSegments

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--rounds',type=int,default=12)
    args=parser.parse_args();strategies={}
    for b in range(60):
        cells={}
        for i in range(80):
            c=bucket()
            for k,v in list(c.items()):
                if isinstance(v,(int,float)):c[k]=(b*80+i+1)*.123456789 if isinstance(v,float) else b+i
            c['dimensions']=dict(category='finance',underlying='INDEX',horizon='24h',price_tier=str(i))
            cells[str(i)]=c
        strategies[str(b)]=dict(attempts={},scalper=dict(research=dict(totals=bucket(),cells=cells,recent=[]),config=dict(order_ttl=1800)))
    data=dict(wallet=dict(cash='1000.0166'),experiments=dict(maker=dict(engine=dict(wallet=dict(cash='1000.0166')),model={},strategies=strategies)))
    cache=CheckpointSegments();pack_checkpoint(data,threshold=0,binary=True,segments=cache);results={}
    for label,segments in (('whole',None),('cached',cache)):
        elapsed=[]
        for n in range(max(1,args.rounds)):
            data['wallet']['cash']=str(1000+n/100)
            strategies['0']['scalper']['research']['totals']['completed']=n
            started=time.process_time();out=pack_checkpoint(data,threshold=0,binary=True,segments=segments)
            elapsed.append((time.process_time()-started)*1000)
        assert unpack_checkpoint(out)==data
        results[label]=dict(median_cpu_ms=round(statistics.median(elapsed),2),stored_chars=len(out['data']),decoded_bytes=out['bytes'])
    print(json.dumps(dict(results=results,cache=cache.metrics())))

if __name__=='__main__':main()
