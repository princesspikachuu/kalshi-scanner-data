"""Known entry-window wake hints remove unnecessary venue polling without relaxing entry gates."""
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

from services.paper_demo.shadow.discovery_wake import (
    asleep, remember, daily_scan_wake, known_entry_wake)
from services.paper_demo.shadow.weather import weather_once
from services.paper_demo.shadow.hourly import hourly_once
from services.paper_demo.shadow.experiments import ExperimentSuite
from services.api.tests.test_favorite_scan import Scan


def at(when):
    return datetime.fromisoformat(when.replace('Z','+00:00')).timestamp()


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class KnownWake(unittest.TestCase):
    def test_daily_city_midnight_entry_window_and_dst(self):
        noon=at('2026-11-21T17:00Z')  # New York noon local
        entry=at('2026-11-22T03:00Z')  # 22:00 EST Nov 21
        self.assertEqual(daily_scan_wake('KXHIGHNY',noon),entry)
        self.assertIsNone(daily_scan_wake('KXHIGHNY',entry))
        self.assertIsNone(daily_scan_wake('KXHIGHNY',entry+3600))
        self.assertEqual(daily_scan_wake('KXHIGHNY',entry+7200),
                         at('2026-11-23T03:00Z'))
        # June uses EDT; 22:00 local is 02:00Z the next calendar day.
        self.assertEqual(daily_scan_wake('KXHIGHNY',at('2026-06-15T16:00Z')),
                         at('2026-06-16T02:00Z'))

    def test_future_hourly_and_sports_wakes_use_actual_venue_times(self):
        now=1000
        hourly=dict(open_time=stamp(now-100),close_time=stamp(now+7200))
        self.assertEqual(known_entry_wake(hourly,'hourly',now),now+3600)
        hourly['open_time']=stamp(now+4000)
        self.assertEqual(known_entry_wake(hourly,'hourly',now),now+4000)
        future=dict(open_time=stamp(now-100),close_time=stamp(now+86400),
                    expected_expiration_time=stamp(now+10800))
        self.assertEqual(known_entry_wake(future,'sports',now),now+3300)
        self.assertIsNone(known_entry_wake(future,'sports',now+3300))
        missing=dict(open_time=stamp(now),close_time=stamp(now+3600))
        self.assertIsNone(known_entry_wake(missing,'sports',now))

    def test_malformed_venue_timestamps_do_not_abort_future_discovery(self):
        # A nullable or structurally invalid market schedule is unknown,
        # never permission to sleep until a fabricated future entry window.
        now=1000
        row=dict(ticker='KXHIGHNY-example',event_ticker='EVENT',
                 open_time=stamp(now+3600),close_time=stamp(now+7200),
                 expected_expiration_time=stamp(now+5400))
        invalid=(None,[],{},True,False)
        for kind in ('15m','hourly','weather_daily','sports'):
            for field in ('open_time','close_time'):
                for value in invalid:
                    with self.subTest(kind=kind,field=field,value=repr(value)):
                        broken=dict(row);broken[field]=value
                        self.assertIsNone(known_entry_wake(broken,kind,now))
        for value in invalid:
            with self.subTest(kind='sports',field='expected_expiration_time',
                              value=repr(value)):
                broken=dict(row);broken['expected_expiration_time']=value
                self.assertIsNone(known_entry_wake(broken,'sports',now))

    def test_wake_at_is_only_a_hint_not_a_market_authorization(self):
        suite=Mock();suite.discovery_wakes={}
        remember(suite,'hourly:ABC',200,100)
        self.assertTrue(asleep(suite,'hourly:ABC',199))
        self.assertFalse(asleep(suite,'hourly:ABC',200))
        self.assertNotIn('hourly:ABC',suite.discovery_wakes)
        remember(suite,'weather:ABC',float('inf'),100)
        self.assertNotIn('weather:ABC',suite.discovery_wakes)


class DiscoveryWakeIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_daily_weather_discovers_at_local_noon_without_sleep(self):
        suite=Mock();suite.feed_markets.return_value={}
        suite.enabled_profiles.side_effect=lambda category:(
            [dict(series='KXHIGHNY')] if category=='weather_daily' else [])
        suite.weather_cursor={};suite.weather_pages={};suite.portfolios={};suite.weather_scan_log_at=0
        suite.settlement_markets.return_value={}
        suite.search_capacity.return_value=True
        suite.discovery_wakes={'weather_daily:KXHIGHNY':at('2026-11-22T03:00Z')}
        host=Mock(experiments=suite);host.put=AsyncMock()
        host.verified_data.call.return_value={'markets':[],'cursor':''}
        now=at('2026-11-21T17:00Z')
        with patch('services.paper_demo.shadow.weather.time.time',return_value=now):
            await weather_once(host)
        host.verified_data.call.assert_called_once()
        host.put.assert_not_awaited()
        self.assertNotIn('weather_daily:KXHIGHNY',suite.discovery_wakes)
    async def test_provider_future_hourly_open_sleeps_and_survives_checkpoint(self):
        host,suite=Scan().setup_host();now=1000
        suite.enabled_profiles=lambda asset:([dict(series='KXBTCD')]
            if asset=='hourly' else [])
        future=dict(ticker='KXBTCD-future',event_ticker='E',status='active',
                    open_time=stamp(now-100),close_time=stamp(now+7200),
                    yes_bid_dollars='.80',no_bid_dollars='.18',volume_fp='100')
        def response(method,path,query=None):
            if path.startswith('/series/'):return dict(series=dict(frequency='hourly'))
            self.assertEqual(path,'/markets')
            return dict(markets=[future])
        host.verified_data.call.side_effect=response
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=now):
            await hourly_once(host)
        self.assertEqual(suite.discovery_wakes['hourly:KXBTCD'],now+3600)
        self.assertEqual(host.verified_data.call.call_count,2)
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=now+90):
            await hourly_once(host)
        self.assertEqual(host.verified_data.call.call_count,2)
        saved=suite.state()
        self.assertEqual(saved['_discovery_wakes']['hourly:KXBTCD'],now+3600)
        restored=ExperimentSuite(suite.host,suite.rows,saved)
        self.assertTrue(asleep(restored,'hourly:KXBTCD',now+100))
        self.assertFalse(asleep(restored,'hourly:KXBTCD',now+3600))
        with patch('services.paper_demo.shadow.hourly.time.time',return_value=now+3600):
            await hourly_once(host)
        self.assertGreater(host.verified_data.call.call_count,2)
        host.put.assert_awaited_once()
