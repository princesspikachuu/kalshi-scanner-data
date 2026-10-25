"""Guard against unbounded optional trade-history work in full-size collections."""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_backtest import (
    execution_sample_indices, quick_trade_history,
    EXECUTION_MARKETS_PER_DAY, EXECUTION_TRADE_PAGES,
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

    def test_one_page_trade_fetch(self):
        with patch("collect_backtest.urllib.request.urlopen",
                   return_value=FakeResponse({"trades": [{"trade_id": "ok"}], "cursor": ""})) as request:
            items = quick_trade_history({"ticker":"X"}, False, 10, 20)
        self.assertEqual(len(items), 1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["timeout"], 7)

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
