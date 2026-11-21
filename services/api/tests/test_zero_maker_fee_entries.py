"""All hosted paper strategies require a verified zero-maker-fee schedule."""
import time
import unittest
from datetime import datetime,timezone
from decimal import Decimal as D
from unittest.mock import Mock

from services.paper_demo.exchange import Fees
from services.paper_demo.shadow.core import Engine,FeePolicy


def effective(at):
    return datetime.fromtimestamp(at,timezone.utc).isoformat().replace('+00:00','Z')


class MakerScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now=time.time()
        self.ticker='TEST-1'
        self.fees=Fees(Mock())
        self.state=dict(at=self.now,base=('quadratic',1),changes=[],events=[])
        self.fees.cache[self.ticker]=self.state

    def eligible(self):
        return self.fees.zero_maker_fees_until(self.ticker,self.now,self.now+120)

    def test_standard_series_is_maker_free(self):
        self.assertTrue(self.eligible())

    def test_current_series_maker_fee_is_excluded(self):
        self.state['base']=('quadratic_with_maker_fees',1)
        self.assertFalse(self.eligible())

    def test_future_series_maker_fee_is_excluded_before_close(self):
        self.state['changes']=[dict(scheduled_ts=effective(self.now+40),
            fee_type='quadratic_with_maker_fees',fee_multiplier=1)]
        self.assertFalse(self.eligible())

    def test_future_event_override_is_excluded_before_close(self):
        self.state['events']=[dict(scheduled_ts=effective(self.now+40),
            fee_type_override='quadratic_with_maker_fees',fee_multiplier_override=1)]
        self.assertFalse(self.eligible())

    def test_fee_scheduled_after_close_does_not_block(self):
        self.state['changes']=[dict(scheduled_ts=effective(self.now+180),
            fee_type='quadratic_with_maker_fees',fee_multiplier=1)]
        self.assertTrue(self.eligible())

    def test_unverified_and_stale_fee_data_fail_closed(self):
        self.assertFalse(self.fees.zero_maker_fees_until('missing',self.now,self.now+120))
        self.state['at']=self.now-100
        self.assertFalse(self.eligible())


class PaperEntryGuardTests(unittest.TestCase):
    def setUp(self):
        self.e=Engine(Mock(),cash='100')
        self.e.advance(1000)
        self.e.add_market(dict(ticker='TEST-1',open=900,close=1900),FeePolicy())
        self.e.require_zero_maker_fee_entries=True

    def test_unverified_market_rejects_new_buy_but_allows_exit(self):
        buy=self.e.place('TEST-1','yes','buy',D(1),D('.60'))
        self.assertEqual(self.e.orders[buy].status,'rejected')
        exit_order=self.e.place('TEST-1','yes','sell',D(1),D('.20'),maker=False)
        self.assertEqual(self.e.orders[exit_order].status,'pending')

    def test_verified_maker_free_market_allows_buy(self):
        self.e.set_zero_maker_fee_verified('TEST-1',True)
        buy=self.e.place('TEST-1','yes','buy',D(1),D('.60'))
        self.assertEqual(self.e.orders[buy].status,'pending')

    def test_fee_change_cancels_waiting_buys_without_touching_exits(self):
        self.e.set_zero_maker_fee_verified('TEST-1',True)
        buy=self.e.place('TEST-1','yes','buy',D(1),D('.60'))
        exit_order=self.e.place('TEST-1','yes','sell',D(1),D('.20'),maker=False)
        self.e.set_zero_maker_fee_verified('TEST-1',False)
        self.assertEqual(self.e.orders[buy].status,'cancelled')
        self.assertEqual(self.e.orders[exit_order].status,'pending')

    def test_nonzero_fee_blocks_even_if_market_flag_was_true(self):
        self.e.set_zero_maker_fee_verified('TEST-1',True)
        self.e.fees['TEST-1']=FeePolicy(D(1),D(1))
        buy=self.e.place('TEST-1','yes','buy',D(1),D('.60'))
        self.assertEqual(self.e.orders[buy].status,'rejected')


if __name__=='__main__':
    unittest.main()
