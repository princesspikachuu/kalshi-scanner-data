import unittest
from pydantic import ValidationError
from services.api.live_bots import TrialBudget,LiveSizing,sizing
from services.api.tests.test_demo_engine import config

class LiveBudgetTests(unittest.TestCase):
    def test_dollar_limits_use_trial_amount_and_round_down(self):
        c=config(bid_percent=.5,market_percent=1,bot_percent=3,cycle_buy_cents=3)
        result=sizing(c,dict(trial_cap_cents=2500,portfolio_reference_cents=100000))
        self.assertEqual((result['bid_cents'],result['market_cents'],result['bot_cents']),(12,25,75))
        self.assertEqual(result['contracts_per_bid'],4)
        self.assertEqual(result['portfolio_equivalent_bid_percent'],.012)
        self.assertIsNone(sizing(c,None))
    def test_tiny_budget_never_rounds_up_to_an_oversized_contract(self):
        self.assertEqual(sizing(config(bid_percent=.5,cycle_buy_cents=3),dict(trial_cap_cents=100))['contracts_per_bid'],0)
        self.assertEqual(sizing(config(bid_percent=10,market_percent=1,bot_percent=3,cycle_buy_cents=3),dict(trial_cap_cents=1000))['contracts_per_bid'],3)
    def test_invalid_or_over_portfolio_cap_and_execution_fields_are_rejected(self):
        for body in [dict(trial_cap_cents=0),dict(trial_cap_cents=2,portfolio_reference_cents=1),
                dict(trial_cap_cents=True),dict(trial_cap_cents=100,execution_enabled=True)]:
            with self.assertRaises(ValidationError):TrialBudget.model_validate(body)
        with self.assertRaises(ValidationError):LiveSizing(expected_settings_revision=1,bid_percent=1,market_percent=2,bot_percent=3,desired='running')
