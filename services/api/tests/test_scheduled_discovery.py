"""Schedule hints reduce reads without authorizing entries or abandoning exposure."""
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock,AsyncMock,patch
from decimal import Decimal as D
from services.paper_demo.shadow.schedules import session_wake,EASTERN
from services.paper_demo.shadow.runner import ForwardRun
from services.paper_demo.shadow.sports import sports_once
from services.api.tests import test_monitoring_capacity as allocation
from services.api.tests import test_favorite_scan as scan
from services.api.tests.test_strategy_folders import market


def at(value):return datetime.fromisoformat(value).replace(tzinfo=EASTERN).timestamp()


class Sessions(unittest.TestCase):
    def test_weekend_wakes_before_monday_open_and_dst_is_local(self):
        self.assertEqual(session_wake('KXINXU',at('2026-11-07T12:00')),at('2026-11-09T09:29'))
        self.assertEqual(session_wake('KXNASDAQ100U',at('2026-03-06T17:00')),at('2026-03-09T09:29'))
        self.assertIsNone(session_wake('KXINXU',at('2026-11-09T09:29')))
    def test_holidays_early_close_and_unknown_series_or_year(self):
        self.assertEqual(session_wake('KXINXU',at('2026-11-26T12:00')),at('2026-11-27T09:29'))
        self.assertIsNone(session_wake('KXINXU',at('2026-11-27T12:59')))
        self.assertEqual(session_wake('KXINXU',at('2026-11-27T13:00')),at('2026-11-30T09:29'))
        self.assertIsNone(session_wake('KXBTCD',at('2026-11-07T12:00')))
        self.assertIsNone(session_wake('KXINXU',at('2029-11-10T12:00')))


class Subscriptions(unittest.TestCase):
    def test_expired_and_parked_books_leave_feed_but_keep_settlement_state(self):
        run=object.__new__(ForwardRun)
        run.engine=SimpleNamespace(markets={'old':dict(close=100),'new':dict(close=200)})
        run.selected={'a':'old','b':'new'}
        state={'held':dict(close=200),'expired':dict(close=100),'parked':dict(close=200,entry_parked=True)}
        run.experiments=SimpleNamespace(extra={t:t for t in state},portfolios={'favorites':(SimpleNamespace(markets=state),None,None)})
        self.assertEqual(run.subscription_tickers(100),{'new','held'})
        self.assertIn('expired',state)


class Allocation(unittest.TestCase):
    def test_restored_active_book_counts_without_extra_cache_and_expired_does_not(self):
        s=allocation.AllocationTests().suite();e=s.portfolios['favorites'][0]
        market(e,'KXHIGHNY-current',close=200);e.markets['KXHIGHNY-current']['weather_category']='weather_daily'
        market(e,'KXHIGHNY-expired',close=100);e.markets['KXHIGHNY-expired']['weather_category']='weather_daily'
        s.extra['KXHIGHNY-expired']='KXHIGHNY-expired'
        self.assertEqual(s.monitoring_snapshot(100)['entry_markets'],1)
    def test_priority_reclaim_preserves_held_positions_and_pending_entries(self):
        fixture=allocation.AllocationTests();s=fixture.suite();e=s.portfolios['favorites'][0]
        for name in ('held','pending','idle'):fixture.add(s,'KXHIGHNY-'+name)
        e.wallet.fill('KXHIGHNY-held','yes','buy',D(1),D('.8'),D(0),1,'held')
        e.place('KXHIGHNY-pending','yes','buy',D(1),D('.4'))
        self.assertTrue(s.reclaim_idle_candidate(200))
        self.assertNotIn('KXHIGHNY-idle',s.feed_markets())
        self.assertIn('KXHIGHNY-held',s.feed_markets());self.assertIn('KXHIGHNY-pending',s.feed_markets())


class Discovery(unittest.IsolatedAsyncioTestCase):
    async def test_closed_cash_index_uses_no_provider_reads(self):
        host,s=scan.Scan().setup_host();s.enabled_profiles=lambda asset:[dict(series='KXINXU')]
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=at('2026-11-07T12:00')):
            from services.paper_demo.shadow.hourly import hourly_once
            await hourly_once(host)
        host.verified_data.call.assert_not_called();host.put.assert_not_awaited()
        self.assertEqual(s.hourly_retry_at['KXINXU'],at('2026-11-09T09:29'))
    async def test_shared_game_live_read_and_settlement_backoff(self):
        s=allocation.AllocationTests().suite();e=s.portfolios['favorites'][0]
        now=at('2026-11-07T12:00')
        for suffix in ('a','b'):
            t='KXNBAGAME-'+suffix;market(e,t,close=now+1000)
            e.markets[t].update(sports=True,sports_expected_end=now-100,sports_start=now-10000,
                milestone_id='shared',event_ticker='EVENT')
        s.enabled_profiles=lambda asset:[]
        host=Mock(experiments=s);host.put=AsyncMock()
        def call(method,path,query=None):
            if path.startswith('/markets/'):return dict(market=dict(status='closed'))
            self.assertEqual(path,'/live_data/milestone/shared')
            return dict(live_data=dict(milestone_id='shared',details=dict(status='in_progress',last_updated_ts=now)))
        host.verified_data.call.side_effect=call
        with patch('services.paper_demo.shadow.sports.time.time',return_value=now):await sports_once(host)
        self.assertEqual(host.verified_data.call.call_count,3)
        gates=[c.args[1]['gate'] for c in host.put.await_args_list]
        self.assertTrue(all(g['sports_live'] for g in gates))
        host.verified_data.call.reset_mock()
        with patch('services.paper_demo.shadow.sports.time.time',return_value=now+10):await sports_once(host)
        self.assertEqual(host.verified_data.call.call_count,1)
    async def test_future_games_sleep_without_live_reads_and_recheck_before_start(self):
        s=allocation.AllocationTests().suite();s.enabled_profiles=lambda asset:[dict(series='KXNBAGAME')]
        host=Mock(experiments=s);host.put=AsyncMock();now=at('2026-11-07T12:00')
        date=lambda n:datetime.fromtimestamp(n,EASTERN).isoformat()
        row=dict(ticker='KXNBAGAME-FUTURE',event_ticker='EVENT',status='active',open_time=date(now-100),
            close_time=date(now+86400),expected_expiration_time=date(now+10800))
        def call(method,path,query=None):
            if path=='/markets':return dict(markets=[row])
            if path=='/milestones':return dict(milestones=[dict(id='future',category='Sports',start_date=now+3600,related_event_tickers=['EVENT'])])
            if path.startswith('/live_data/'):
                return dict(live_data=dict(milestone_id='future',details=dict(status='scheduled',last_updated_ts=now+3300)))
            raise AssertionError(path)
        host.verified_data.call.side_effect=call
        with patch('services.paper_demo.shadow.sports.time.time',return_value=now):await sports_once(host)
        self.assertEqual(host.verified_data.call.call_count,2);host.put.assert_not_awaited()
        host.verified_data.call.reset_mock()
        with patch('services.paper_demo.shadow.sports.time.time',return_value=now+15):await sports_once(host)
        host.verified_data.call.assert_not_called()
        with patch('services.paper_demo.shadow.sports.time.time',return_value=now+3300):await sports_once(host)
        self.assertTrue(any(c.args[1].startswith('/live_data/') for c in host.verified_data.call.call_args_list))
        host.put.assert_not_awaited()
