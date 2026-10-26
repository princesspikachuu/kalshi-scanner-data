"""Guard against unbounded optional trade-history work in full-size collections."""
import io
import json
import urllib.error
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_backtest import (
    execution_sample_indices, quick_trade_history,
    EXECUTION_MARKETS_PER_DAY, EXECUTION_TRADE_PAGES, OptionalTradeRateLimit,
)

class FakeResponse:
    def __init__(self, payload):
        self.data = io.BytesIO(json.dumps(payload).encode("utf-8"))
    def __enter__(self):
        return self.data
    def __exit__(self, *args):
        self.data.close()

class CollectionRuntimeTests(unittest.TestCase):
    def test_execution_sample_is_bounded_and_even(self):
        self.assertEqual(execution_sample_indices(0), set())
        self.assertEqual(execution_sample_indices(5), set(range(5)))
        sample = execution_sample_indices(300)
        self.assertEqual(len(sample), EXECUTION_MARKETS_PER_DAY)
        self.assertEqual(min(sample), 0)
        self.assertGreater(max(sample), 270)

    def test_batch_keeps_all_markets_and_falls_back_for_missing_entry(self):
        import collect_backtest as collector
        sample=[{"ticker":str(n),"close_time":"2026-10-20T12:00:00Z"} for n in range(20)]
        bars=[{"end_period_ts":123}]
        payload={"markets":[{"market_ticker":str(n),"candlesticks":bars} for n in range(19)]}
        with patch.object(collector,"req",return_value=payload) as batch, patch.object(collector,"candles",return_value=bars) as single:
            result=list(collector.candle_batches(sample,"crypto",False))
        self.assertEqual(len(result),20)
        self.assertEqual(batch.call_count,1)
        self.assertEqual(single.call_count,1)
        self.assertEqual(single.call_args.args[0]["ticker"],"19")
        self.assertTrue(all(b==bars for _,b in result))

    def test_archived_candles_do_not_use_recent_batch_endpoint(self):
        import collect_backtest as collector
        sample=[{"ticker":"old","close_time":"2026-10-20T12:00:00Z"}]
        with patch.object(collector,"req") as batch, patch.object(collector,"candles",return_value=[]) as single:
            self.assertEqual(list(collector.candle_batches(sample,"sports",True)),[(sample[0],[])])
        batch.assert_not_called()
        single.assert_called_once()

    def test_optional_budget_stops_before_second_page(self):
        import collect_backtest as collector
        with patch.object(collector.time,"monotonic",return_value=100), patch.object(collector.urllib.request,"urlopen") as request:
            self.assertIsNone(quick_trade_history({"ticker":"X"},False,10,20,deadline=99))
        request.assert_not_called()

    def test_main_request_retries_are_bounded_without_final_sleep(self):
        import collect_backtest as collector
        error=urllib.error.HTTPError("https://example.invalid",429,"Too Many Requests",None,None)
        with patch.object(collector,"paced_open",side_effect=error) as request, patch.object(collector.time,"sleep") as sleep:
            with self.assertRaises(RuntimeError):collector.req("/markets",{})
        self.assertEqual(request.call_count,3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[2,4])

    def test_one_page_trade_fetch(self):
        with patch("collect_backtest.urllib.request.urlopen",
                   return_value=FakeResponse({"trades": [{"trade_id": "ok"}], "cursor": ""})) as request:
            items = quick_trade_history({"ticker":"X"}, False, 10, 20)
        self.assertEqual(len(items), 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["timeout"], 7)

    def test_429_opens_optional_analysis_circuit_breaker(self):
        err = urllib.error.HTTPError("https://example.invalid", 429,
                                     "Too Many Requests", None, None)
        with patch("collect_backtest.urllib.request.urlopen", side_effect=err) as request:
            with self.assertRaises(OptionalTradeRateLimit):
                quick_trade_history({"ticker":"X"}, False, 10, 20)
        self.assertEqual(request.call_count, 1)

    def test_truncation_is_missing_not_zero_fills(self):
        responses = [FakeResponse({"trades": [{"trade_id": str(n)}], "cursor": "next"})
                     for n in range(EXECUTION_TRADE_PAGES)]
        with patch("collect_backtest.urllib.request.urlopen",
                   side_effect=responses) as request:
            items = quick_trade_history({"ticker":"X"}, True, 10, 20)
        self.assertIsNone(items)
        self.assertEqual(request.call_count, EXECUTION_TRADE_PAGES)

if __name__=="__main__":
    unittest.main()
