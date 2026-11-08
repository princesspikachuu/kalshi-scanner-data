import json,unittest
from decimal import Decimal as D
from services.api.tests import test_favorite_maker_entries as fixture
from services.paper_demo.shadow.favorite_entries import entry_key,estimate
from services.paper_demo.shadow.favorite_timing import rows,clock
from services.paper_demo.shadow.core import FeePolicy

class EntryTiming(unittest.TestCase):
    def setup_bot(self,close=3800,fees=False):
        e,b,book=fixture.MakerEntries().setup_bot()
        t=fixture.MakerEntries.ticker;e.markets[t]['close']=close
        book.levels={'yes':{D('.89'):D(100)},'no':{D('.09'):D(100)}}
        if fees:e.fees[t]=FeePolicy(D(1),D(1))
        b.step();e.advance(201);book.at=201
        return e,b,book,next(iter(e.orders.values()))
    def settle(self,e,b,at):
        t=fixture.MakerEntries.ticker;e.settled.add(t);e.markets[t]['yes_payout_confirmed']='1'
        e.handle('settlement',dict(ticker=t,yes_payout='1'),at);b.step()
    def test_fill_is_assigned_to_remaining_time_at_purchase_not_original_submission(self):
        e,b,book,o=self.setup_bot();original=b.attempts[o.ticker]['entry_key']
        e.now=3200;book.at=3200;o.expiry=3800
        e.fill(o,D(10),o.price,'TEST');self.settle(e,b,3801)
        actual='paper-data-v3|'+entry_key('KXBTCD','yes',D('.90'),600)
        self.assertNotEqual(original,actual)
        self.assertEqual(estimate(b.exit_evidence.cells,original)['samples'],0)
        self.assertEqual(estimate(b.exit_evidence.cells,actual)['samples'],1)
        result=rows(b.exit_evidence.cells)[0]
        self.assertEqual((result['price'],result['horizon'],result['net']),('0.90','10–15m','1.00'))
    def test_partial_fills_in_different_time_bands_keep_separate_training_records(self):
        e,b,book,o=self.setup_bot()
        e.fill(o,D(4),o.price,'TEST')
        e.now=3300;book.at=3300;o.expiry=3800;e.fill(o,D(6),o.price,'TEST')
        self.settle(e,b,3801)
        result=rows(b.exit_evidence.cells)
        self.assertEqual(len(result),2);self.assertEqual({r['events'] for r in result},{1})
        self.assertEqual(sum(D(r['contracts']) for r in result),10)
    def test_market_series_and_sports_clock_are_isolated(self):
        self.assertNotEqual(entry_key('KXHIGHNY','yes',D('.90'),600),entry_key('KXBTC15M','yes',D('.90'),600))
        remaining,basis=clock(dict(sports=True,close=200000,sports_expected_end=1000),400)
        self.assertEqual((remaining,basis),(600,'estimated_game_end'))
        self.assertNotEqual(entry_key('KXNBAGAME','yes',D('.90'),600,basis),entry_key('KXNBAGAME','yes',D('.90'),600))
    def test_protective_exit_and_settlement_costs_reconcile_to_the_wallet(self):
        e,b,book,o=self.setup_bot(close=1000,fees=True)
        e.fill(o,D(10),o.price,'TEST')
        book.levels={'yes':{D('.85'):D(100)},'no':{D('.14'):D(100)}}
        e.place(o.ticker,'yes','sell',D(4),D('.01'),maker=False)
        e.advance(202);book.at=202
        result=rows(b.exit_evidence.cells)[0]
        stat=e.wallet.stat(o.ticker)
        self.assertEqual(D(result['net']),stat.gross-stat.realized_fees)
        self.assertEqual(result['events'],0);self.assertEqual(D(result['open_contracts']),6)
        self.settle(e,b,1001)
        result=rows(b.exit_evidence.cells)[0];stat=e.wallet.stat(o.ticker)
        self.assertEqual(D(result['net']),stat.gross-stat.realized_fees)
        self.assertEqual(D(result['open_contracts']),0);self.assertEqual(result['events'],1)
        self.assertGreater(D(result['dollar_hours']),0)
    def test_repeated_partial_fills_do_not_inflate_event_samples_or_checkpoint_chunks(self):
        e,b,book,o=self.setup_bot(close=1000)
        for _ in range(10):e.fill(o,D(1),o.price,'TEST')
        self.assertEqual(len(b.attempts[o.ticker]['entry_fills']),1)
        self.settle(e,b,1001);b.step()
        result=rows(b.exit_evidence.cells)[0]
        self.assertEqual(result['events'],1);self.assertEqual(D(result['contracts']),10)
        self.assertEqual(D(result['closed']),10)
    def test_entry_verification_and_authoritative_outcome_are_required_for_learning(self):
        e,b,book,o=self.setup_bot(close=1000);book.valid=False
        e.fill(o,D(10),o.price,'TEST');self.settle(e,b,1001)
        result=rows(b.exit_evidence.cells)[0]
        self.assertEqual(result['events'],0);self.assertEqual(D(result['unverified']),10)
        self.assertEqual(D(result['net']),1)
    def test_prior_gaps_do_not_discard_a_fresh_entry_with_confirmed_outcome(self):
        e,b,book,o=self.setup_bot(close=1000);e.wallet.stat(o.ticker).valid=False
        e.fill(o,D(10),o.price,'TEST');self.settle(e,b,1001)
        self.assertEqual(rows(b.exit_evidence.cells)[0]['events'],1)
    def test_timing_aggregates_survive_serialization(self):
        e,b,book,o=self.setup_bot(close=1000);e.fill(o,D(10),o.price,'TEST');self.settle(e,b,1001)
        copied=json.loads(json.dumps(b.exit_evidence.cells))
        self.assertEqual(rows(copied),rows(b.exit_evidence.cells))
    def test_same_bucket_fills_at_different_times_keep_fifo_holding_time(self):
        e,b,book,o=self.setup_bot(close=1000)
        e.fill(o,D(5),o.price,'TEST')
        e.now=250;book.at=250;o.expiry=1000;e.fill(o,D(5),o.price,'TEST')
        self.assertEqual(len(b.attempts[o.ticker]['entry_fills']),2)
        e.now=300;book.at=300
        sell=e.place(o.ticker,'yes','sell',D(5),D('.01'),maker=False)
        e.fill(e.orders[sell],D(5),D('.90'),'TEST')
        self.assertEqual(D(rows(b.exit_evidence.cells)[0]['holding_seconds']),D(5)*99)
