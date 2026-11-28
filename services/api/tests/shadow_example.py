"""Generate a SYNTHETIC validation tape, not a historical Kalshi backtest."""
import json
from pathlib import Path


def generate(path):
    ticker, start = 'KXBTC15M-SYNTHETIC', 1700000000
    rows = [dict(source='config',time=0,payload=dict(cash='50',latency_ms=150,seed=7,
                    toxic_probability=.35,contracts=100)),
            dict(source='market',time=start,payload=dict(market=dict(ticker=ticker,
                    open=start,close=start+900,event_ticker='KXBTC15M-SYNTHETIC'),
                    taker_multiplier='1',maker_multiplier='0'))]
    seq=0
    for second in range(902):
        at=start+second
        rows.append(dict(source='clock',time=at,payload={}))
        rows.append(dict(source='spot',time=at,payload=dict(price=str(100000+second%2),event_time=at)))
        seq+=1
        if second in (0,300):
            yes,no,quantity=('.10','.80','100') if second==0 else ('.41','.58','200')
            event=dict(type='orderbook_snapshot',sid=1,seq=seq,sending_ts_ms=at*1000,
                       msg=dict(market_ticker=ticker,yes_dollars_fp=[[yes,quantity]],
                                no_dollars_fp=[[no,quantity]]))
        else:
            event=dict(type='orderbook_delta',sid=1,seq=seq,sending_ts_ms=at*1000,
                       msg=dict(market_ticker=ticker,side='yes',
                                price_dollars='.10' if second<300 else '.41',delta_fp='0'))
        rows.append(dict(source='kalshi',time=at,payload=event))
        if second==60:
            rows.append(dict(source='kalshi',time=at+.01,payload=dict(type='trade',sid=2,seq=1,
                msg=dict(market_ticker=ticker,trade_id='SYNTHETIC-TRADE',yes_price_dollars='.10',
                         count_fp='200',taker_side='no',ts_ms=(at+.01)*1000))))
    rows.append(dict(source='kalshi',time=start+901.1,payload=dict(type='market_lifecycle_v2',
                    msg=dict(market_ticker=ticker,event_type='settled'))))
    rows.append(dict(source='settlement',time=start+901.2,payload=dict(ticker=ticker,yes_payout='1')))
    Path(path).write_text(''.join(json.dumps(r)+'\n' for r in rows))


if __name__=='__main__':
    generate(Path(__file__).with_name('synthetic_validation.jsonl'))
