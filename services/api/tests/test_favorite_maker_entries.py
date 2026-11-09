"""Maker-only favorites: actual costs, changing evidence, expiry and queue races."""
import json
import unittest
from unittest.mock import Mock
from decimal import Decimal as D
from services.api.tests.test_strategy_folders import QuietAudit,market,profile
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.favorites import FavoritesStrategy
from services.paper_demo.shadow.favorite_entries import entry_key,observe,estimate


class MakerEntries(unittest.TestCase):
    ticker='KXBTCD-test'

    def setup_bot(self, **settings):
        e=Engine(QuietAudit(),cash='1000',latency_ms=150,toxic_fill_probability=0)
        e.advance(200)
        book=market(e,self.ticker,yes='.79',no='.19',close=1000)
        p=dict(profile(series='KXBTCD',strategy='favorites'),**settings)
        b=FavoritesStrategy(e,p);e.strategy=b;e.fill_callback=b.on_fill
        return e,b,book

    def seed(self,b,n=200,wins=200):
        key=('paper-data-v3|' if b.profile.get('paper_exploration',True) is not False else '')+entry_key('KXBTCD','yes',D('.80'),800)
        for i in range(n):observe(b.exit_evidence.cells,key,str(i),int(i<wins))
        return key

    def test_unknown_probability_uses_configured_size_and_competitive_maker_bid(self):
        e,b,book=self.setup_bot();b.step();o=next(iter(e.orders.values()))
        self.assertEqual((o.price,o.quantity,o.maker,o.expiry),(D('.80'),D(10),True,230))
        self.assertEqual(b.attempts[self.ticker]['entry_mode'],'paper_exploration')
        self.assertIn('10-contract maker data trial',b.last_reason)
        self.assertFalse(any(not x.maker for x in e.orders.values()))

    def test_exploration_can_be_disabled_without_inventing_an_edge(self):
        e,b,_=self.setup_bot(paper_exploration=False);b.step();self.assertFalse(e.orders)

    def test_supported_estimate_can_use_configured_size_after_all_costs(self):
        e,b,_=self.setup_bot(paper_exploration=False);self.seed(b)
        e.fees[self.ticker]=FeePolicy(D(1),D(1));b.step()
        o=next(iter(e.orders.values()));a=b.attempts[self.ticker]
        self.assertEqual(o.quantity,D(10));self.assertTrue(o.maker)
        cost=o.price+e.fees[self.ticker].charge(o.quantity,o.price,True)/o.quantity
        self.assertLessEqual(cost+D('.02'),D(str(a['entry_estimate']['lower'])))

    def test_weak_evidence_blocks_even_a_high_market_price(self):
        e,b,_=self.setup_bot(paper_exploration=False);self.seed(b,100,75);b.step()
        self.assertFalse(e.orders)

    def test_series_fees_can_eliminate_the_entry(self):
        e,b,_=self.setup_bot(paper_exploration=False);self.seed(b);e.fees[self.ticker]=FeePolicy(D(1),D(100))
        b.step();self.assertFalse(e.orders)

    def test_maker_cannot_cross_after_submission_latency(self):
        e,b,book=self.setup_bot();b.step();o=next(iter(e.orders.values()))
        book.levels['no']={D('.22'):D(100)}
        e.advance(201)
        self.assertEqual(o.status,'rejected');self.assertFalse(e.wallet.lots)

    def test_stale_data_cancels_resting_bid_before_its_expiry(self):
        e,b,book=self.setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()));book.valid=False;b.step();e.advance(202)
        self.assertEqual(o.status,'cancelled');self.assertFalse(e.wallet.lots)

    def test_valid_bid_keeps_its_queue_beyond_the_first_minute(self):
        e,b,book=self.setup_bot();b.step();e.advance(201)
        old=next(iter(e.orders.values()));ahead=old.ahead;arrived=old.arrives
        for now in range(210,281,10):
            e.advance(now);book.at=now
            book.levels={'yes':{D('.79'):D(100)},'no':{D('.19'):D(100)}}
            b.step()
        self.assertEqual(len(e.orders),1)
        self.assertEqual((old.status,old.price,old.ahead,old.arrives),('resting',D('.80'),ahead,arrived))
        self.assertEqual(old.expiry,310)
        self.assertFalse(b.attempts[self.ticker]['recorded'])

    def test_expired_unfilled_bid_can_retry_after_one_minute(self):
        e,b,book=self.setup_bot();b.step();old=next(iter(e.orders.values()))
        e.advance(270);book.at=270;b.step()
        new=list(e.orders.values())[-1]
        self.assertEqual(old.status,'expired');self.assertNotEqual(new.id,old.id)
        self.assertLessEqual(new.price,D('.95'))
        e.advance(940);book.at=940;b.step()
        self.assertFalse(any(o.status in ('pending','resting') for o in e.orders.values()))

    def test_evidence_deterioration_cancels_without_stacking_replacement(self):
        e,b,book=self.setup_bot(paper_exploration=False);key=self.seed(b);b.step();e.advance(201)
        for i in range(200,500):observe(b.exit_evidence.cells,key,str(i),0)
        b.step();b.step();self.assertEqual(len(e.orders),1)
        e.advance(202);self.assertEqual(next(iter(e.orders.values())).status,'cancelled')

    def test_partial_fill_keeps_requested_remainder_without_duplicate_entries(self):
        e,b,book=self.setup_bot();self.seed(b);b.step();e.advance(201)
        o=next(iter(e.orders.values()));e.fill(o,D(1),o.price,'TEST');e.advance(202)
        book.at=202;b.step()
        self.assertTrue(b.attempts[self.ticker]['first'])
        self.assertEqual(len(e.orders),1);self.assertEqual(o.status,'resting')
        self.assertEqual(o.remaining,D(9))
        self.assertEqual(e.wallet.inventory(self.ticker,'yes'),D(1))

    def test_clock_only_decisions_keep_trade_fills_immediate(self):
        e,b,book=self.setup_bot()
        e.clock_only_strategy_steps=True
        b.step();e.advance(201)
        order=next(iter(e.orders.values()))
        original_step=b.step;b.step=Mock(wraps=original_step)
        volume=order.ahead+D(1)
        e.handle('kalshi',dict(type='trade',sid=7,seq=1,msg=dict(
            market_ticker=self.ticker,trade_id='clock-only-fill',taker_side='no',
            yes_price_dollars=str(order.price),count_fp=str(volume),ts_ms=201100)),201.1)
        self.assertEqual(e.wallet.inventory(self.ticker,'yes'),D(1))
        b.step.assert_not_called()
        book.at=201.2
        e.handle('clock',{},201.2)
        self.assertGreater(b.step.call_count,0)

    def test_clock_only_mode_does_not_defer_non_kalshi_state_changes(self):
        e,b,_=self.setup_bot();e.clock_only_strategy_steps=True
        b.step=Mock()
        ticker='KXBTCD-next'
        e.handle('market',dict(market=dict(ticker=ticker,open=100,close=1000,event_ticker='NEXT',bot_id='next'),
            taker_multiplier='1',maker_multiplier='0'),200.1)
        b.step.assert_called_once_with(ticker)

    def test_only_confirmed_settlement_teaches_entry_model_and_survives_json(self):
        e,b,_=self.setup_bot();b.step();e.advance(201)
        o=next(iter(e.orders.values()));e.fill(o,D(1),o.price,'TEST')
        key=b.attempts[self.ticker]['entry_key']
        b.step();self.assertNotIn(key,b.exit_evidence.cells)
        e.markets[self.ticker].update(paid=True,yes_payout_confirmed='1');b.step();b.step()
        cells=json.loads(json.dumps(b.exit_evidence.cells))
        self.assertEqual(estimate(cells,key)['samples'],1)
        self.assertEqual(cells[key]['events'],{'TEST':1})

    def test_correlated_thresholds_do_not_inflate_confidence(self):
        cells={}
        for i in range(40):observe(cells,'key','same-event',1)
        self.assertEqual(estimate(cells,'key')['samples'],1)
        observe(cells,'key','same-event',0)
        self.assertEqual(cells['key']['events']['same-event'],0)
