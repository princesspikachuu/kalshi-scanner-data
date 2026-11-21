"""Regression checks for Favorites position classification without wallet mutation."""
import unittest
from decimal import Decimal as D
from types import SimpleNamespace

from services.paper_demo.shadow.position_health import position_settlement_health


class PositionSettlementHealthTests(unittest.TestCase):
    def test_separates_active_expired_settled_and_unknown_without_mutation(self):
        lots = [
            SimpleNamespace(ticker="OPEN", quantity=D("2")),
            SimpleNamespace(ticker="WAIT", quantity=D("3.5")),
            SimpleNamespace(ticker="WAIT", quantity=D("1.5")),
            SimpleNamespace(ticker="WS", quantity=D("4")),
            SimpleNamespace(ticker="PAID", quantity=D("5")),
            SimpleNamespace(ticker="UNKNOWN", quantity=D("6")),
        ]
        engine = SimpleNamespace(
            wallet=SimpleNamespace(lots=lots),
            markets={
                "OPEN": {"close": 120, "paid": False},
                "WAIT": {"close": 90, "paid": False},
                "WS": {"close": 90, "paid": False},
                "PAID": {"close": 90, "paid": True},
            },
            settled={"WS"},
        )
        before_cash = D("0.4742")
        engine.wallet.cash = before_cash
        snapshot = position_settlement_health(engine, 100)
        self.assertEqual(snapshot["still_open"], {"lots": 1, "contracts": "2", "markets": 1})
        self.assertEqual(snapshot["expired_not_ws_settled"], {"lots": 2, "contracts": "5.0", "markets": 1})
        self.assertEqual(snapshot["expired_ws_settled"], {"lots": 1, "contracts": "4", "markets": 1})
        self.assertEqual(snapshot["expired_already_paid"], {"lots": 1, "contracts": "5", "markets": 1})
        self.assertEqual(snapshot["unknown_market"], {"lots": 1, "contracts": "6", "markets": 1})
        self.assertEqual(engine.wallet.cash, before_cash)
        self.assertEqual(len(engine.wallet.lots), 6)

    def test_no_lots_has_explicit_zero_counts(self):
        engine = SimpleNamespace(wallet=SimpleNamespace(lots=[]), markets={}, settled=set())
        result = position_settlement_health(engine, 100)
        self.assertEqual(len(result), 5)
        self.assertTrue(all(group["lots"] == 0 and group["markets"] == 0
                            and group["contracts"] == "0" for group in result.values()))


if __name__ == "__main__":
    unittest.main()
