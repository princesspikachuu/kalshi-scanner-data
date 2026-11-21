"""Bound trade-print deduplication without changing virtual fills or settlement."""

import unittest
from decimal import Decimal as D
from unittest.mock import Mock, patch

from services.paper_demo.shadow.core import Engine, FeePolicy, TRADE_DEDUP_MAX_IDS


class BaseEngineTradeDedupTests(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(Mock(), cash='100', toxic_fill_probability=0)
        self.engine.advance(1000)
        self.engine.add_market(dict(ticker='TEST', close=2000), FeePolicy())
        self.engine.handle('kalshi', dict(type='orderbook_snapshot', sid=1, seq=1,
            sending_ts_ms=1000000, msg=dict(market_ticker='TEST',
                yes_dollars_fp=[['.1', '100']], no_dollars_fp=[['.8', '100']])), 1000)
        oid = self.engine.place('TEST', 'yes', 'buy', D('10'), D('.1'))
        self.engine.advance(1000.15)
        self.order = self.engine.orders[oid]

    def print(self, ident, at, quantity='100', price='.1', block=False):
        self.engine.handle('kalshi', dict(type='trade', msg=dict(
            market_ticker='TEST', trade_id=ident, yes_price_dollars=price,
            count_fp=quantity, taker_side='no', ts_ms=at*1000,
            is_block_trade=block)), at)

    def test_valid_print_is_deduplicated_and_recent_cache_stays_aligned(self):
        self.print('first', 1000.2, quantity='105')
        self.assertEqual(self.order.remaining, D('5'))
        self.print('first', 1000.3, quantity='105')
        self.assertEqual(self.order.remaining, D('5'))
        self.assertEqual(len(self.engine.trade_ids), 1)
        self.assertEqual(len(self.engine._trade_id_recent), 1)

    def test_invalid_stale_and_block_prints_do_not_enter_cache(self):
        self.print('blocked', 1000.2, block=True)
        self.assertEqual(len(self.engine.trade_ids), 0)
        with self.assertRaises(ValueError):
            self.print('invalid', 1000.3, quantity='-1')
        self.assertEqual(len(self.engine.trade_ids), 0)
        self.engine.advance(1005)
        self.engine.books['TEST'].at = 1005  # The book is current; only the print is stale.
        # A print that was valid long ago cannot change an order now.
        with patch.object(self.engine, 'data_gap') as gap:
            self.engine.trade('TEST', dict(trade_id='old', taker_side='no',
                yes_price_dollars='.1', count_fp='200', ts_ms=1000*1000))
            gap.assert_called_once()
        self.assertNotIn(('TEST', 'old'), self.engine.trade_ids)

    def test_retention_is_bounded_over_long_active_market(self):
        # Many distinct valid prints in a long-running, unsettled market.
        for i in range(500):
            at = 1000.2 + i*.05
            self.engine.advance(at)
            self.engine.books['TEST'].at = at
            self.engine.trade('TEST', dict(trade_id=str(i), taker_side='no',
                yes_price_dollars='.1', count_fp='1', ts_ms=at*1000))
        self.assertLessEqual(len(self.engine.trade_ids), 165)
        self.assertEqual(len(self.engine.trade_ids), len(self.engine._trade_id_recent))
        self.assertNotIn(('TEST', '0'), self.engine.trade_ids)

    def test_print_without_resting_order_does_not_allocate_dedup(self):
        # No paper bid can fill while every order is still pending/cancelled.
        self.order.status = 'cancelled'
        self.print('unfillable', 1000.2, quantity='100')
        self.assertEqual(len(self.engine.trade_ids), 0)
        self.assertEqual(len(self.engine._trade_id_recent), 0)

    def test_pending_order_cannot_retroactively_fill_skipped_print(self):
        self.order.status = 'pending'
        self.order.arrives = 1000.5
        self.print('before-arrival', 1000.2, quantity='500')
        self.assertEqual(len(self.engine.trade_ids), 0)
        self.order.status = 'resting'
        self.print('before-arrival', 1000.6, quantity='500')
        # Delivery time cannot change the original exchange print time.
        # Replaying the same earlier print must never fill the later bid.
        # A validly timed later print remains eligible for execution.
        self.assertEqual(self.order.remaining, D(10))
        self.assertEqual(len(self.engine.trade_ids), 0)
        self.print('later', 1000.7, quantity='105')
        self.assertEqual(self.order.remaining, D(5))

    def test_over_capacity_fails_closed_and_leaves_orders_untouched(self):
        with patch('services.paper_demo.shadow.core.TRADE_DEDUP_MAX_IDS', 2):
            self.print('a', 1000.2, quantity='1')
            self.print('b', 1000.3, quantity='1')
            before = self.order.remaining
            with patch.object(self.engine, 'data_gap') as gap:
                self.print('c', 1000.4, quantity='1000')
                gap.assert_called_once_with('TEST', 'trade deduplication capacity reached')
            self.assertEqual(self.order.remaining, before)
            self.assertEqual(len(self.engine.trade_ids), 2)
        self.assertGreater(TRADE_DEDUP_MAX_IDS, 1000)

    def test_clear_and_confirmed_settlement_release_retained_ids(self):
        self.print('before', 1000.2)
        self.engine.clear_trade_ids()
        self.assertEqual(self.engine.trade_ids, set())
        self.assertEqual(len(self.engine._trade_id_recent), 0)
        self.print('again', 1000.3)
        self.engine.markets['TEST']['paid'] = True
        self.engine.settled.add('TEST')
        # Use a wallet without lots to avoid an unrelated financial report.
        self.engine.complete_settlement('TEST', D(1))
        self.assertEqual(self.engine.trade_ids, {('TEST', 'again')})
        self.engine.markets['TEST']['paid'] = False
        with patch.object(self.engine, 'report'), patch.object(self.engine, 'log'):
            self.engine.complete_settlement('TEST', D(1))
        self.assertEqual(len(self.engine.trade_ids), 0)
        self.assertEqual(len(self.engine._trade_id_recent), 0)


if __name__ == '__main__':
    unittest.main()
