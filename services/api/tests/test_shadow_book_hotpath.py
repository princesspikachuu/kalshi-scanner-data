"""Incremental depth validation preserves full-book and fee-boundary invariants."""
import random
import time
import unittest
from datetime import datetime,timezone
from decimal import Decimal as D
from unittest.mock import Mock,patch
from services.demo.exchange import ExchangeFailure
from services.paper_demo.exchange import Fees
from services.paper_demo.shadow.core import Book

class BookHotpathTests(unittest.TestCase):
    def snapshot(self,book,yes=None,no=None):
        book.apply(dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(
            yes_dollars_fp=yes or [['.1','10']],no_dollars_fp=no or [['.2','10']])),1000)

    def test_randomized_incremental_updates_match_reconstructed_full_depth(self):
        book=Book();self.snapshot(book)
        expected={'yes':{D('.1'):D(10)},'no':{D('.2'):D(10)}};rng=random.Random(7)
        for seq in range(2,1002):
            side=rng.choice(('yes','no'));price=D(rng.randrange(1,301))/1000
            old=expected[side].get(price,D(0));quantity=D(rng.randrange(0,20))
            book.apply(dict(type='orderbook_delta',sid=1,seq=seq,msg=dict(
                side=side,price_dollars=str(price),delta_fp=str(quantity-old))),1000+seq*.001)
            if quantity:expected[side][price]=quantity
            else:expected[side].pop(price,None)
            self.assertEqual(book.levels,expected)
            self.assertEqual(book.bid(side),max(expected[side],default=None))
        for side in ('yes','no'):
            while expected[side]:
                best=max(expected[side]);book.levels[side].pop(best);expected[side].pop(best)
                self.assertEqual(book.bid(side),max(expected[side],default=None))

    def test_malformed_levels_cannot_revalidate_a_book(self):
        for value in ('NaN','Infinity','-1'):
            book=Book()
            with self.assertRaises(ValueError):self.snapshot(book,yes=[['.1',value]])
            self.assertFalse(book.valid)
        for changed in (dict(side='bad'),dict(price_dollars='NaN'),dict(delta_fp='Infinity'),dict(delta_fp='-11')):
            book=Book();self.snapshot(book)
            msg=dict(side='yes',price_dollars='.1',delta_fp='1');msg.update(changed)
            with self.assertRaises(ValueError):book.apply(dict(type='orderbook_delta',sid=1,seq=2,msg=msg),1001)
            self.assertFalse(book.valid)

    def test_best_bid_stays_correct_for_external_depth_updates(self):
        book=Book();self.snapshot(book)
        book.levels['yes'][D('.15')]=D(5);self.assertEqual(book.bid('yes'),D('.15'))
        del book.levels['yes'][D('.15')];self.assertEqual(book.bid('yes'),D('.1'))
        book.levels['yes']={D('.3'):D(1)};self.assertEqual(book.bid('yes'),D('.3'))
        book.levels['yes'].clear();self.assertIsNone(book.bid('yes'))

class CachedFeeBoundaryTests(unittest.TestCase):
    def test_cache_switches_at_exact_scheduled_boundary_and_accepts_earlier_lookup(self):
        # Match exchange ISO timestamp precision exactly at the boundary.
        now=float(int(time.time()));stamp=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        fees=Fees(Mock());fees.cache['t']=dict(at=now,base=('quadratic',1),changes=[],events=[
            dict(scheduled_ts=stamp(now+10),fee_type_override='quadratic_with_maker_fees',fee_multiplier_override=2),
            dict(scheduled_ts=stamp(now+20),fee_type_override=None,fee_multiplier_override=None)])
        for at,wanted in ((now,('quadratic',1)),(now+9.99,('quadratic',1)),
                          (now+10,('quadratic_with_maker_fees',2)),(now+20,('quadratic',1)),
                          (now+11,('quadratic_with_maker_fees',2))):
            self.assertEqual(fees.schedule('t',at),wanted)

    def test_cached_fee_never_bypasses_schedule_verification_expiry(self):
        fees=Fees(Mock());fees.cache['t']=dict(at=1000,base=('quadratic',1),changes=[],events=[])
        with patch('services.paper_demo.exchange.time.time',return_value=1000):self.assertEqual(fees.schedule('t',1000),('quadratic',1))
        with patch('services.paper_demo.exchange.time.time',return_value=1061):
            with self.assertRaises(ExchangeFailure):fees.schedule('t',1061)
