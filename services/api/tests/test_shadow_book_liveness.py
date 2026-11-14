"""A quiet unchanged book is not a feed gap when the stream is verified alive."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,FeePolicy

class BookLivenessTests(unittest.TestCase):
    def fixture(self):
        e=Engine(Mock());e.advance(1000)
        e.add_market(dict(ticker='BTC',close=1900),FeePolicy())
        e.handle('kalshi',dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(market_ticker='BTC',
            yes_dollars_fp=[['.1','100']],no_dollars_fp=[['.8','100']])),1000)
        return e

    def test_verified_heartbeat_keeps_unchanged_book_usable_without_inventing_depth(self):
        e=self.fixture()
        e.handle('book_heartbeat',dict(sid=1),1005)
        e.handle('clock',{},1005)
        self.assertTrue(e.books['BTC'].valid)
        self.assertTrue(e.wallet.stat('BTC').valid)
        self.assertEqual(e.books['BTC'].at,1000)
        ident=e.place('BTC','yes','buy',D(1),D('.1'))
        e.advance(1005.15)
        self.assertEqual(e.orders[ident].status,'resting')
        self.assertEqual(e.orders[ident].ahead,100)

    def test_no_heartbeat_still_expires_quote_freshness(self):
        e=self.fixture();e.handle('clock',{},1005)
        self.assertFalse(e.books['BTC'].valid)
        self.assertFalse(e.wallet.stat('BTC').valid)

    def test_live_heartbeat_does_not_repair_a_sequence_gap(self):
        e=self.fixture();e.handle('book_heartbeat',dict(sid=1),1001)
        e.handle('kalshi',dict(type='orderbook_delta',sid=1,seq=4,msg=dict(
            market_ticker='BTC',side='yes',price_dollars='.1',delta_fp='1')),1001)
        e.handle('book_heartbeat',dict(sid=1),1002)
        self.assertFalse(e.books['BTC'].valid)
        self.assertFalse(e.wallet.stat('BTC').valid)
        e.handle('gap',dict(reason='socket disconnected'),1002)
        self.assertEqual(e.book_feed_at,{})
