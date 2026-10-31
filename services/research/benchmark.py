"""Explicit synthetic report benchmark. No DB, provider, archive, or secret access."""
import argparse
from datetime import datetime,timedelta,timezone
import json
import resource
import time
from .inventory import digest
from .reports import prepare_report_stream,MINUTES


def synthetic_datasets(days,markets_per_day):
    for day in range(days):
        start=datetime(2025,1,1,tzinfo=timezone.utc)+timedelta(days=day)
        candidates=[];records=[]
        for index in range(markets_per_day):
            close=start+timedelta(seconds=int((index+.5)*86400/markets_per_day));ts=int(close.timestamp())
            ticker=f'SYNTHETIC-{day}-{index}'
            candidates.append(dict(ticker=ticker,event_ticker='EVENT-'+ticker,series='KXBTC15M',close_time=close.isoformat(),result='yes' if index%5 else 'no'))
            for minute in range(1,16):
                bid=(55+(index%5)*10) if minute in MINUTES['btc'] else 10+(index+minute)%85
                records.append(dict(resource='candles',ticker=ticker,record={'end_period_ts':ts-minute*60,'yes_bid':{'close':format(bid/100,'.2f')}}))
        payload=dict(format='raw-evidence-dataset-v1',day=start.date().isoformat(),candidates=candidates,records=records,summary={'resources':['candles']})
        yield dict(id=day+1,payload=payload,fingerprint=digest(payload))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days',type=int,default=30);parser.add_argument('--markets-per-day',type=int,default=96)
    args=parser.parse_args()
    if not 1<=args.days<=3660 or not 1<=args.markets_per_day<=1000:parser.error('Synthetic size out of bounds')
    started=time.perf_counter();receipt=dict(contract='synthetic-report-benchmark-v1',synthetic=True,days=args.days,markets_per_day=args.markets_per_day)
    try:
        prepared=prepare_report_stream('btc',synthetic_datasets(args.days,args.markets_per_day),latest_ids=None)
        payload=json.loads(prepared.payload_json)
        expected=args.days*args.markets_per_day
        if payload['historical']['candidate_count']!=expected or payload['historical']['observation_count']!=expected*5:raise AssertionError('Benchmark cohort changed')
        if any(c['hold']['sampled_markets']!=c['loss_prevention']['sampled_markets'] for c in payload['historical']['cells']):raise AssertionError('Benchmark denominator changed')
        receipt.update(completed=True,candidates=expected,observations=expected*5,report_bytes=len(prepared.payload_json.encode()),observation_bytes=len(prepared.observations_json.encode()),fingerprint=prepared.fingerprint)
    except ValueError as error:receipt.update(completed=False,limit=str(error))
    receipt.update(wall_seconds=round(time.perf_counter()-started,3),peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    print(json.dumps(receipt,sort_keys=True))


if __name__=='__main__':main()
