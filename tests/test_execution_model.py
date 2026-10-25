import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from execution_model import cents, best_quote, simulate, trade_evidence

class ExecutionTests(unittest.TestCase):
    def test_cent_prices_and_missing_ask(self):
        self.assertEqual(cents("0.6100"), 61)
        self.assertIsNone(cents("0.6105"))
        self.assertIsNone(best_quote({"yes_bid":{"close_dollars":"0.60"}}))
        quote = best_quote({"yes_bid":{"close_dollars":"0.60"},
                            "yes_ask":{"close_dollars":"0.64"}})
        self.assertEqual(quote, ("yes",60,64))

    def test_opposite_taker_only_and_trade_through(self):
        trades=[{"taker_outcome_side":"no","yes_price_dollars":"0.59",
                 "count_fp":"2.00","created_time":"2026-10-24T12:00:05Z",
                 "is_block_trade":False},
                {"taker_outcome_side":"yes","yes_price_dollars":"0.55",
                 "count_fp":"99.00","created_time":"2026-10-24T12:00:05Z"},
                {"taker_outcome_side":"no","yes_price_dollars":"0.60",
                 "count_fp":"2.00","created_time":"2026-10-24T12:00:06Z"}]
        t=1792843200
        evidence, _count, thru, at=trade_evidence(trades,"yes",60,t,t+60)
        self.assertEqual(evidence,"trade_through")
        self.assertEqual(thru,2)
        self.assertEqual(at,2)
        no_evidence, *_=trade_evidence(trades,"yes",58,t,t+60)
        self.assertEqual(no_evidence,"no_trade_evidence")

    def test_post_only_offsets_and_proxy_math(self):
        time=1792843200
        market={"series_ticker":"KXTEST","ticker":"M1","result":"yes"}
        bar={"end_period_ts":time,"yes_bid":{"close_dollars":"0.60"},
             "yes_ask":{"close_dollars":"0.64"}}
        trade=[{"taker_outcome_side":"no","yes_price_dollars":"0.59",
                "count_fp":"5.00","created_time":"2026-10-24T12:00:06Z"}]
        rows=simulate(market,"btc","2026-10-24",5,bar,trade,time,time+300)
        self.assertEqual({r[11] for r in rows},set(range(57,64)))
        confirmed=[r for r in rows if r[11]==60][0]
        self.assertEqual(confirmed[15],"trade_through")
        self.assertEqual(confirmed[-1],39.0)
        self.assertEqual({r[11] for r in rows if r[15]=="trade_through"},
                         {60,61,62,63})

if __name__ == "__main__":
    unittest.main()
