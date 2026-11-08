"""Capacity grows only from measured load; rotation never abandons exposure."""
import json,unittest,time
from decimal import Decimal as D
from unittest.mock import Mock
from services.paper_demo.shadow.monitoring import MonitoringBudget,protected
from services.paper_demo.shadow.experiments import ExperimentSuite
from services.api.tests import test_strategy_scope as scope_tests
from services.api.tests.test_strategy_folders import market,QuietAudit,profile

class BudgetTests(unittest.TestCase):
    def test_cold_or_stale_measurements_do_not_authorize_new_subscriptions(self):
        b=MonitoringBudget();self.assertFalse(b.limits(100)['admitting'])
        b.observe(100,0,.01,1);self.assertTrue(b.limits(100)['admitting']);self.assertFalse(b.limits(111)['admitting'])
    def test_capacity_grows_in_stages_after_sustained_healthy_load(self):
        b=MonitoringBudget()
        for now in range(0,241,5):b.observe(now,0,.02,2)
        self.assertEqual(b.limits(240)['total'],48);self.assertEqual(b.limits(240)['entry_candidates'],20)
        self.assertEqual(b.limits(240)['per_category'],12)
    def test_backlog_lag_processing_cost_and_read_cooldown_each_pause_admission(self):
        for values in ((300,.1,2,0),(0,3,2,0),(0,.1,101,0),(0,.1,2,30)):
            with self.subTest(values=values):
                b=MonitoringBudget();b.observe(100,*values)
                self.assertFalse(b.limits(100)['admitting']);self.assertEqual(b.limits(100)['level'],0)
    def test_fast_burst_does_not_block_admission_by_count_alone(self):
        b=MonitoringBudget();b.observe(100,600,.002,.2)
        self.assertTrue(b.limits(100)['admitting']);self.assertAlmostEqual(b.limits(100)['estimated_queue_seconds'],.12)
        slow=MonitoringBudget();slow.observe(101,600,.002,2);self.assertFalse(slow.limits(101)['admitting'])
    def test_large_burst_retains_hard_cap_even_with_fast_measured_processing(self):
        b=MonitoringBudget();b.observe(100,2001,.002,.01)
        self.assertFalse(b.limits(100)['admitting'])
    def test_one_healthy_sample_after_overload_cannot_immediately_restore_expansion(self):
        b=MonitoringBudget();b.observe(0,300,.1,1);b.observe(65,0,.1,1)
        self.assertEqual(b.limits(65)['total'],32)
        b.observe(180,0,.1,1);self.assertEqual(b.limits(180)['total'],32)

class AllocationTests(unittest.TestCase):
    def suite(self):return scope_tests.ScopeTests().suite()[0]
    def add(self,s,t,at=100):
        s.handle('weather_market',dict(market=dict(ticker=t,event_ticker='EVENT',open=0,close=10000,
            weather_category='weather_daily',discovered_at=at),taker_multiplier='1',maker_multiplier='0'),at)
    def test_held_positions_do_not_use_entry_category_slots(self):
        s=self.suite();e=s.portfolios['favorites'][0]
        for i in range(4):
            t='KXHIGHNY-'+str(i);self.add(s,t)
            e.wallet.fill(t,'yes','buy',D(1),D('.8'),D(0),1,'held'+str(i))
        stats=s.monitoring_snapshot(100)
        self.assertEqual(stats['position_and_exit_markets'],4);self.assertEqual(stats['entry_markets'],0)
        self.assertTrue(s.search_capacity('weather_daily',100))
    def test_total_limit_still_blocks_admission_and_never_evicts_positions(self):
        s=self.suite();s.host.engine.markets={str(i):dict(close=10000) for i in range(48)}
        self.assertFalse(s.extra_capacity(['new'],100));self.assertEqual(len(s.host.engine.markets),48)
    def test_global_rotation_keeps_other_strategy_inventory_and_active_orders(self):
        s=self.suite();t='KXHIGHNY-HELD';self.add(s,t)
        seq=s.portfolios['sequential'][0];fav=s.portfolios['favorites'][0]
        seq.wallet.fill(t,'yes','buy',D(1),D('.45'),D(0),1,'owned')
        s.rotate_candidates(500)
        self.assertIn(t,s.feed_markets());self.assertNotIn(t,s.rotation_exclusions)
        self.assertIn(t,fav.markets)
        other='KXHIGHNY-ORDER';self.add(s,other)
        fav.place(other,'yes','buy',D(1),D('.4'));s.rotate_candidates(500)
        self.assertIn(other,s.feed_markets())
    def test_rotated_candidate_cannot_be_immediately_rediscovered_and_state_survives_restart(self):
        s=self.suite();t='KXHIGHNY-IDLE';self.add(s,t)
        s.rotate_candidates(250)
        self.assertNotIn(t,s.feed_markets());self.assertIn(t,s.settlement_markets())
        self.assertFalse(s.candidate_allowed(t,300));self.assertTrue(s.candidate_allowed(t,311))
        state=json.loads(json.dumps(s.state(),default=str))
        restored=ExperimentSuite(s.host,s.rows,state)
        self.assertFalse(restored.candidate_allowed(t,300));self.assertTrue(restored.candidate_allowed(t,311))
    def test_flat_completed_attempt_keeps_its_cash_and_evidence_after_parking(self):
        s=self.suite();t='KXHIGHNY-COMPLETE';self.add(s,t)
        e,f,_=s.portfolios['sequential'];b=f.owner(t)
        e.wallet.fill(t,'yes','buy',D(1),D('.45'),D(0),1,'yes')
        e.wallet.fill(t,'no','buy',D(1),D('.45'),D(0),1,'no')
        b.attempts[t]=dict(first=True,recorded=True,completed=True,net='.1')
        s.rotate_candidates(250)
        self.assertNotIn(t,s.feed_markets());self.assertEqual(e.wallet.cash,D('1000.1'))
        self.assertEqual(e.wallet.stat(t).gross,D('.1'));self.assertEqual(b.attempts[t]['net'],'.1')
    def test_live_game_waiting_for_late_favorites_retains_monitoring(self):
        s=self.suite();e,f,_=s.portfolios['favorites'];t='KXNBAGAME-LIVE'
        market(e,t,close=10000);e.markets[t].update(sports=True,sports_live=True,sports_expected_end=9000,discovered_at=100)
        self.assertTrue(protected(s,t,500));s.rotate_candidates(500)
        self.assertIn(t,s.feed_markets())
