"""Conservative trade-through proxy; never asserts actual maker fills."""
from collections import defaultdict
from decimal import Decimal
import heapq
from scripts.execution_model import best_quote,trade_evidence,timestamp


def replay(payload,strategy,records):
    bars=defaultdict(list);trades=defaultdict(list)
    for row in records:
        (bars if row['resource']=='candles' else trades)[row['ticker']].append(row['record'])
    entries=[]
    for candidate in payload['candidates']:
        close=timestamp(candidate['close_time'])
        for minute in strategy['minutes']:
            target=close-minute*60
            eligible=[b for b in bars[candidate['ticker']] if 0<=target-b['end_period_ts']<=60]
            if not eligible:continue
            quote=best_quote(max(eligible,key=lambda b:b['end_period_ts']))
            if quote is None:continue
            side,bid,ask=quote;bid+=strategy['bid_offset']
            if not strategy['min_price']<=bid<=strategy['max_price'] or bid>=ask:continue
            evidence,_,through,_=trade_evidence(trades[candidate['ticker']],side,bid,target,min(target+60,close-1))
            entries.append((target,candidate['ticker'],minute,close,side,bid,candidate['result'],evidence,through))
    cash=strategy['starting_cash_cents'];pending=[];results=[];missed=0;insufficient=0
    for target,ticker,minute,close,side,bid,result,evidence,through in sorted(entries):
        while pending and pending[0][0]<=target:cash+=heapq.heappop(pending)[1]
        quantity=strategy['contracts'];cost=(bid+1)*quantity
        if evidence!='trade_through' or through<quantity:missed+=1;continue
        if cost>cash:insufficient+=1;continue
        cash-=cost;payment=100*quantity if result==side else 0
        heapq.heappush(pending,(close,payment))
        results.append(dict(ticker=ticker,minute=minute,side=side,entry_cents=bid,contracts=quantity,
            outcome=result,profit_loss_cents=payment-cost,evidence='trade-through proxy'))
    cash+=sum(payment for _,payment in pending)
    return dict(mode='historical paper replay',fill_model='Strict trade-through proxy; actual queue position and fills are unknown',
        starting_cash_cents=strategy['starting_cash_cents'],ending_cash_cents=cash,
        profit_loss_cents=cash-strategy['starting_cash_cents'],simulated_fills=len(results),
        no_fill_evidence=missed,insufficient_cash=insufficient,attempts=len(entries),trades=results[:500],
        total_trades=len(results),trades_truncated=len(results)>500)
