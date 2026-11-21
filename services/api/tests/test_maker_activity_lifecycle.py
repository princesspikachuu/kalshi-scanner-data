"""Slow-market quote opportunities survive scalper rotation without invented fills."""
import json,unittest
from unittest.mock import Mock
from services.api.tests import test_market_maker as maker_tests
T=maker_tests.T
from services.api.tests.test_strategy_folders import QuietAudit,ready_suite
from services.paper_demo.shadow.market_maker import profiles,MM_FOLDERS,activity_deadline

class MakerActivityLifecycleTests(unittest.TestCase):
    def suite(self):
        host=Mock();host.audit=QuietAudit();host.verified_fees.schedule.return_value=('quadratic',1)
        rows=[dict(parameters=dict(p,revision=1),progress=dict(desired='running')) for p in profiles()]
        s=ready_suite(host,rows)
        payload=dict(market=dict(ticker='POL-X',market_maker=True,market_category='politics',open=100,
            close=200000,discovered_at=200,maker_idle_seconds=1200,maker_last_trade_at=190),taker_multiplier='1',maker_multiplier='0')
        s.maker_discovery=dict(candidates={'POL-X':dict(reason='awaiting_shared_admission',retry_at=500)},ranked=[])
        return s,payload

    def test_two_minute_rotation_retains_maker_then_releases_genuinely_idle_market(self):
        s,payload=self.suite();s.handle('maker_market',payload,200)
        s.rotate_candidates(500);self.assertIn('POL-X',s.feed_markets())
        s.rotate_candidates(1401);self.assertNotIn('POL-X',s.feed_markets())

    def test_flat_maker_can_still_be_reclaimed_for_another_strategy(self):
        s,payload=self.suite();s.handle('maker_market',payload,200)
        self.assertTrue(s.reclaim_idle_candidate(500));self.assertNotIn('POL-X',s.feed_markets())

    def test_cadence_survives_restart_and_recent_live_trade_extends_monitoring(self):
        s,payload=self.suite();s.handle('maker_market',payload,200)
        s=ready_suite(s.host,s.rows,json.loads(json.dumps(s.state(),default=str)))
        e=s.portfolios[MM_FOLDERS[0]][0]
        self.assertEqual(e.markets['POL-X']['maker_idle_seconds'],1200)
        e.tape.trade('POL-X',dict(trade_id='live',taker_side='yes',yes_price_dollars='.45',count_fp='1',ts_ms=1300000),1300)
        s.rotate_candidates(1500);self.assertIn('POL-X',s.feed_markets())
        s.rotate_candidates(2501);self.assertNotIn('POL-X',s.feed_markets())
        self.assertFalse(e.wallet.lots)

    def test_quiet_gate_uses_cadence_and_still_stops_a_genuinely_inactive_market(self):
        e,b,_=maker_tests.MakerTests().bot();e.markets[T].update(maker_idle_seconds=1200,maker_last_trade_at=190)
        e.now=600;b.step(T);self.assertFalse(e.markets[T]['maker_entry_blocked'])
        e.now=1401;b.step(T);self.assertTrue(e.markets[T]['maker_entry_blocked'])
        self.assertFalse(e.wallet.lots)

    def test_capacity_race_is_reported_and_retried_without_admitting_or_allocating(self):
        s,payload=self.suite();s.monitoring.limits=lambda now:dict(total=32,entry_candidates=12,
            per_category=4,admitting=False,level=0)
        s.handle('maker_market',payload,200)
        row=s.maker_discovery['candidates']['POL-X']
        self.assertEqual(row['reason'],'shared_admission_rejected_capacity');self.assertEqual(row['retry_at'],230)
        self.assertNotIn('POL-X',s.extra)
        self.assertTrue(all(not e.markets and not e.orders and e.available()==1000 for e,_,_ in s.portfolios.values()))
        s.monitoring.limits=lambda now:dict(total=32,entry_candidates=12,per_category=4,admitting=True,level=0)
        s.handle('maker_market',payload,231)
        self.assertEqual(row['reason'],'admitted_to_shared_monitoring')
        self.assertEqual(len(s.feed_markets()),1)
        self.assertTrue(all(not e.wallet.lots and e.available()==1000 for e,_,_ in s.portfolios.values()))

    def test_activity_bounds_do_not_allow_indefinite_monitoring(self):
        e,_,_=maker_tests.MakerTests().bot();m=e.markets[T]
        m['maker_idle_seconds']=999999
        self.assertEqual(activity_deadline(e,T,m),3800)
