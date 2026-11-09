"""Long-lived valid quotes and causal cached admission without synthetic fills."""
import time,unittest
from unittest.mock import Mock,AsyncMock,patch
from services.api.tests import test_market_maker as fixture
from services.paper_demo.shadow.maker_opportunities import retry_verified,turnover_score,ranked_rows
from services.paper_demo.shadow.market_maker import profiles
from services.paper_demo.shadow.core import FeePolicy
from decimal import Decimal as D
T=fixture.T

class QuoteLifetimeTests(unittest.TestCase):
    def test_valid_quote_keeps_identity_queue_and_reservation_past_five_minutes(self):
        e,b,p=fixture.MakerTests().bot();o=next(iter(e.orders.values()))
        e.books[T].at=e.now+.2;e.advance(e.now+.2)
        ahead=o.ahead;reserved=o.reserved;created=o.created
        e.books[T].at=600;e.advance(600);b.step(T)
        self.assertEqual(o.status,'resting');self.assertEqual(o.created,created);self.assertEqual(o.ahead,ahead)
        self.assertEqual(o.reserved,reserved);self.assertEqual(len(e.orders),1);self.assertFalse(e.wallet.lots)
        self.assertGreaterEqual(o.expiry-o.created,900)
    def test_adaptive_lifetime_is_bounded_and_custom_shorter_limit_is_respected(self):
        e,b,_=fixture.MakerTests().bot();e.markets[T]['maker_idle_seconds']=3600
        self.assertEqual(b.phase(T)['order_ttl'],1800)
        b.config['order_ttl']=60;self.assertEqual(b.phase(T)['order_ttl'],60)
    def test_long_profit_ask_does_not_delay_adverse_selection_liquidation(self):
        f=fixture.MakerTests();e,b,_=f.bot();f.print_fill(e,next(iter(e.orders.values())),'entry')
        e.books[T].at=e.now+.2;e.advance(e.now+.2);b.step(T)
        sell=next(o for o in e.orders.values() if o.action=='sell')
        self.assertAlmostEqual(sell.expiry-sell.created,900)
        e.books[T].at=e.now+.2;e.advance(e.now+.2)
        with patch.object(b,'features',return_value=dict(trend=-.04,sigma=.001,trade_pressure=-.8,depth_withdrawal=0)):
            b.step(T);e.books[T].at=e.now+.2;e.advance(e.now+.2);b.step(T)
            self.assertEqual(sell.status,'cancelled')
            e.books[T].at=e.now+.2;e.advance(e.now+.2)
        self.assertFalse(e.wallet.lots);self.assertEqual(b.attempts[T]['exit_reason'],'maker_adverse_selection')
        self.assertLess(b.research['totals']['adverse_losses'],0)

class CachedAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def state(self):
        h=Mock();h.put=AsyncMock();h.experiments.feed_markets.return_value={}
        h.experiments.enabled_profiles.return_value=[next(profiles())];h.experiments.search_capacity.return_value=True
        row=dict(category='politics',score=1,execution_score=2,ready=dict(payload=dict(market=dict(ticker='POL-X')),verified_at=1000,next_try=1005))
        return h,dict(candidates={'POL-X':row}),row
    async def test_retry_reuses_metadata_without_http_and_has_a_five_second_backoff(self):
        h,s,row=self.state()
        self.assertFalse(await retry_verified(h,s,1004));self.assertTrue(await retry_verified(h,s,1005))
        self.assertFalse(await retry_verified(h,s,1006));self.assertEqual(h.put.await_count,1)
        h.verified_data.call.assert_not_called();self.assertEqual(row['ready']['next_try'],1010)
    async def test_stale_paused_and_resource_blocked_candidates_never_bypass_admission(self):
        h,s,row=self.state();h.experiments.search_capacity.return_value=False
        self.assertFalse(await retry_verified(h,s,1005));h.put.assert_not_called()
        h.experiments.search_capacity.return_value=True
        self.assertFalse(await retry_verified(h,s,1121));self.assertNotIn('ready',row)
        h,s,row=self.state();h.experiments.enabled_profiles.return_value=[]
        self.assertFalse(await retry_verified(h,s,1005));h.put.assert_not_called();self.assertNotIn('ready',row)
    async def test_highest_verified_turnover_candidate_is_retried_first(self):
        h,s,row=self.state();s['candidates']['BETTER']=dict(row,execution_score=10,
            ready=dict(row['ready'],payload=dict(market=dict(ticker='BETTER'))))
        await retry_verified(h,s,1005)
        self.assertEqual(h.put.call_args.args[1]['market']['ticker'],'BETTER')
        self.assertFalse(await retry_verified(h,s,1006));self.assertEqual(h.put.await_count,1)

class TurnoverRankingTests(unittest.TestCase):
    def prints(self,now,recent):
        return [dict(created_time=fixture.iso(now-(60+i if recent else 36000+i)),count_fp='5') for i in range(100)]
    def test_active_two_cent_market_can_outrank_an_inactive_wide_spread(self):
        now=100000;p=list(profiles())[4];fee=FeePolicy(D(1),D(0))
        active=turnover_score(self.prints(now,True),now,dict(yes=.40,no=.58),[p],fee,{})
        slow=turnover_score(self.prints(now,False),now,dict(yes=.40,no=.54),[p],fee,{})
        self.assertGreater(active['execution_score'],slow['execution_score'])
        self.assertLess(active['expected_hold_seconds'],slow['expected_hold_seconds'])
    def test_recent_slowdown_is_not_hidden_by_old_daily_volume(self):
        now=100000;p=list(profiles())[4];fee=FeePolicy(D(1),D(0))
        stale=[dict(created_time=fixture.iso(now-10),count_fp='5')]
        stale.extend(dict(created_time=fixture.iso(now-36000-i),count_fp='5') for i in range(99))
        steady=[dict(created_time=fixture.iso(now-300-i*120),count_fp='5') for i in range(20)]
        wide=turnover_score(stale,now,dict(yes=.40,no=.54),[p],fee,{})
        active=turnover_score(steady,now,dict(yes=.40,no=.58),[p],fee,{})
        self.assertLess(wide['recent_flow_per_hour'],active['recent_flow_per_hour'])
        self.assertGreater(active['execution_score'],wide['execution_score'])
        self.assertLess(active['expected_hold_seconds'],wide['expected_hold_seconds'])

    def test_fees_affect_ranking_and_economically_negative_candidates_are_rejected(self):
        now=100000;p=dict(list(profiles())[4],contracts=1)
        free=turnover_score(self.prints(now,True),now,dict(yes=.40,no=.58),[p],FeePolicy(D(1),D(0)),{})
        costly=turnover_score(self.prints(now,True),now,dict(yes=.40,no=.58),[p],FeePolicy(D(1),D(100)),{})
        self.assertIsNotNone(free);self.assertIsNone(costly)
    def test_verified_opportunities_precede_high_volume_rejected_priors(self):
        s=dict(candidates={'REJECTED':dict(category='politics',score=99,inspected_at=10,reason='insufficient_executed_trade_frequency'),
            'READY':dict(category='politics',score=.1,execution_score=2,reason='awaiting_shared_admission')})
        self.assertEqual(ranked_rows(s)[0]['ticker'],'READY')
