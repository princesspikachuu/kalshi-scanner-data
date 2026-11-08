"""Worker backlog affects request arrival; clean entry windows preserve honest learning."""
import json,unittest
from decimal import Decimal as D
from services.api.tests import test_favorite_maker_entries as fixture
from services.paper_demo.shadow.core import Book,FeePolicy
from services.paper_demo.shadow.risk import liquidation
from services.paper_demo.shadow.favorite_timing import rows

class DelayAndWindows(unittest.TestCase):
    def bot(self):return fixture.MakerEntries().setup_bot()
    def settle(self,e,b):
        t=fixture.MakerEntries.ticker;e.markets[t]['yes_payout_confirmed']='1';e.settled.add(t)
        e.handle('settlement',dict(ticker=t,yes_payout='1'),1001);b.step()
    def test_queued_request_cannot_arrive_on_the_old_150ms_timeline(self):
        e,b,book=self.bot();e.wall_clock=lambda:205
        b.step();o=next(iter(e.orders.values()))
        self.assertEqual(o.arrives,205.15);self.assertEqual(o.worker_delay_seconds,5)
        self.assertEqual(o.execution_model,'worker-delay-v1')
        e.advance(201);self.assertEqual(o.status,'pending');self.assertFalse(e.wallet.lots)
        book.at=205;e.advance(205.15);self.assertEqual(o.status,'resting')
        e.fill(o,D(10),o.price,'TEST')
        chunk=b.attempts[o.ticker]['entry_fills'][0]
        self.assertEqual(chunk['worker_delay_seconds'],5)
        self.assertEqual(rows(b.exit_evidence.cells)[0]['average_worker_delay_ms'],'5000')
    def test_post_only_still_rechecks_the_book_at_delayed_arrival(self):
        e,b,book=self.bot();e.wall_clock=lambda:205;b.step();o=next(iter(e.orders.values()))
        book.levels={'yes':{D('.78'):D(100)},'no':{D('.20'):D(100)}};book.at=205
        e.advance(205.15)
        self.assertEqual(o.status,'rejected');self.assertFalse(e.wallet.lots)
    def test_cancellation_includes_the_current_worker_delay(self):
        e,b,book=self.bot();b.step();o=next(iter(e.orders.values()));e.advance(201)
        e.wall_clock=lambda:208;e.cancel(o.id)
        event=next(p for p in e.pending if p[2]=='cancel');self.assertEqual(event[0],208.15)
        e.advance(202);self.assertEqual(o.status,'resting')
        e.advance(208.15);self.assertEqual(o.status,'cancelled')
    def test_delayed_order_metadata_survives_checkpoint_restore(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from services.paper_demo.shadow.state import encode,restore
        e,b,book=self.bot();e.wall_clock=lambda:205;b.step();o=next(iter(e.orders.values()))
        saved=json.loads(json.dumps(encode(e,SimpleNamespace(bots={'KXBTCD':b})),default=str))
        new,other,_=self.bot();restore(new,SimpleNamespace(bots={'KXBTCD':other},halted=set(),owner=lambda t:other),saved)
        restored=new.orders[o.id]
        self.assertEqual((restored.decision_at,restored.worker_delay_seconds,restored.execution_model),(205,5,'worker-delay-v1'))
        self.assertEqual(restored.status,'cancelled')

    def test_old_gap_does_not_poison_new_execution_window_or_rewrite_history(self):
        e,b,book=self.bot();e.data_gap(fixture.MakerEntries.ticker,'earlier missing data')
        book.valid=True;book.at=200;book.snapshot_at=200
        b.step();o=next(iter(e.orders.values()));e.advance(201);book.at=201
        e.fill(o,D(10),o.price,'TEST');a=b.attempts[o.ticker];a['risk_observations']={'risk-bucket':True}
        self.settle(e,b)
        self.assertFalse(e.wallet.stat(o.ticker).valid)
        self.assertTrue(a['data_window']['valid']);self.assertEqual(b.exit_evidence.cells['risk-bucket']['n'],1)
        event=[f for k,f in e.audit.events if k=='FAVORITE_TRIAL_QUALITY'][-1]
        self.assertFalse(json.loads(event['details'])['cycle_valid'])
        self.assertTrue(json.loads(event['details'])['execution_window_valid'])
    def test_mid_trial_gap_excludes_execution_learning_but_keeps_verified_forecast(self):
        e,b,book=self.bot();b.step();o=next(iter(e.orders.values()));e.advance(201);book.at=201
        e.fill(o,D(10),o.price,'TEST');a=b.attempts[o.ticker];a['risk_observations']={'risk-bucket':True}
        e.data_gap(o.ticker,'missing while holding');book.valid=True;book.at=202;book.snapshot_at=202
        self.settle(e,b)
        self.assertFalse(a['data_window']['valid']);self.assertNotIn('risk-bucket',b.exit_evidence.cells)
        result=rows(b.exit_evidence.cells)[0]
        self.assertEqual(result['events'],1);self.assertEqual(result['execution_unverified_contracts'],'10')
        self.assertEqual(D(result['net']),e.wallet.stat(o.ticker).gross-e.wallet.stat(o.ticker).realized_fees)
    def test_gap_after_full_exit_does_not_invalidate_completed_window(self):
        e,b,book=self.bot();b.step();o=next(iter(e.orders.values()));e.advance(201);book.at=201
        e.fill(o,D(10),o.price,'TEST');a=b.attempts[o.ticker]
        sell=e.place(o.ticker,'yes','sell',D(10),D('.01'),maker=False)
        e.advance(201.2);self.assertFalse(e.wallet.lots);self.assertIn('ended_at',a['data_window'])
        e.data_gap(o.ticker,'later gap after execution ended')
        self.assertTrue(a['data_window']['valid'])
    def test_restart_invalidates_an_open_execution_window(self):
        from services.api.tests import test_strategy_scope as scope
        from services.paper_demo.shadow.experiments import ExperimentSuite
        from services.api.tests.test_strategy_folders import market
        suite,host=scope.ScopeTests().suite();e,f,ps=suite.portfolios['favorites'];e.now=200
        t='KXBTC15M-window';market(e,t);b=f.owner(t)
        b.attempts[t]=dict(first=True,data_window=dict(valid=True,started_at=200))
        state=suite.state();restored=ExperimentSuite(suite.host,suite.rows,state)
        a=restored.portfolios['favorites'][1].owner(t).attempts[t]
        self.assertFalse(a['data_window']['valid']);self.assertIn('restarted',a['data_window']['reason'])


class LazyDepth(unittest.TestCase):
    def test_order_cache_survives_quantity_updates_but_tracks_insertions_and_deletions(self):
        book=Book();book.levels={'yes':{D('.90'):D(3),D('.80'):D(20)},'no':{D('.09'):D(100)}}
        levels=book.levels['yes'];ordered=levels.ordered_prices()
        levels[D('.90')]=D(5);self.assertIs(ordered,levels.ordered_prices())
        book.consume('yes','sell',D('.90'),D(2))
        self.assertEqual(next(book.iter_depth('yes','sell')),(D('.90'),D(3)))
        levels[D('.95')]=D(1);self.assertEqual(next(book.iter_depth('yes','sell')),(D('.95'),D(1)))
        levels.pop(D('.95'));self.assertEqual(next(book.iter_depth('yes','sell')),(D('.90'),D(3)))
    def test_liquidation_stops_at_needed_depth_and_preserves_fee_and_shadow_overlay(self):
        e,b,book=fixture.MakerEntries().setup_bot()
        book.levels={'yes':{D('.90'):D(3),D('.80'):D(4),D('.70'):D(20)},'no':{D('.09'):D(100)}}
        book.consume('yes','sell',D('.90'),D(1));e.fees[fixture.MakerEntries.ticker]=FeePolicy(D(1),D(0))
        expected=D(2)*D('.90')-e.fees[fixture.MakerEntries.ticker].charge(D(2),D('.90'),False)
        expected+=D(3)*D('.80')-e.fees[fixture.MakerEntries.ticker].charge(D(3),D('.80'),False)
        self.assertEqual(liquidation(e,fixture.MakerEntries.ticker,'yes',D(5)),expected)
        self.assertIsNone(liquidation(e,fixture.MakerEntries.ticker,'yes',D(100)))
        self.assertEqual(book.depth('yes','buy'),[(D('.91'),D(100))])
