import unittest
from datetime import datetime,timezone
from services.paper.engine import replay


class PaperTests(unittest.TestCase):
    def test_only_strict_trade_through_can_fill_and_cash_cannot_be_overdrawn(self):
        close=int(datetime(2026,10,25,12,tzinfo=timezone.utc).timestamp());target=close-60
        payload={'candidates':[dict(ticker=t,close_time='2026-10-25T12:00:00Z',result='yes') for t in ('a','b','c')]}
        records=[]
        for ticker,price in (('a','0.79'),('b','0.80'),('c','0.79')):
            records.extend([dict(resource='candles',ticker=ticker,record=dict(end_period_ts=target,yes_bid={'close':'0.80'},yes_ask={'close':'0.90'})),
                dict(resource='trades',ticker=ticker,record=dict(created_time=datetime.fromtimestamp(target+3,timezone.utc).isoformat(),
                    taker_outcome_side='no',yes_price_dollars=price,no_price_dollars=str(1-float(price)),count_fp='1'))])
        strategy=dict(minutes=[1],min_price=70,max_price=98,bid_offset=0,contracts=1,starting_cash_cents=100)
        result=replay(payload,strategy,records)
        self.assertEqual(result['simulated_fills'],1);self.assertEqual(result['no_fill_evidence'],1)
        self.assertEqual(result['insufficient_cash'],1);self.assertEqual(result['ending_cash_cents'],119)
