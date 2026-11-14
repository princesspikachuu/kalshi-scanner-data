"""Bounded screening can collect fresh observations without authorizing overloaded entries."""
import time,unittest
from unittest.mock import Mock,AsyncMock,patch
from services.api.tests.test_market_maker import iso
from services.paper_demo.shadow.market_maker import maker_once,profiles
from services.paper_demo.shadow.core import FeePolicy

class ReadOnlyMakerScreeningTests(unittest.IsolatedAsyncioTestCase):
    def host(self,now):
        h=Mock();s=h.experiments;s.portfolios={};s.enabled_profiles.return_value=[next(profiles())]
        s.monitoring_snapshot.return_value=dict(admitting=False,telemetry_fresh=True,backlog=5000,
            lag_p95_seconds=1,processing_p95_ms=1,read_cooldown_seconds=0)
        s.search_capacity.return_value=False;s.feed_markets.return_value={};h.put=AsyncMock();h.fee_policy=AsyncMock(return_value=FeePolicy())
        def row(t):return dict(raw=dict(ticker=t,event_ticker='POL',open_time=iso(now-86400),close_time=iso(now+172800),status='active',
            yes_bid_dollars='.42',no_bid_dollars='.52',volume_24h_fp='1000'),event=dict(series_ticker='POL'),category='politics',score=1,at=now)
        s.maker_discovery=dict(cursor='',candidates={t:row(t) for t in ('POL-HOT','POL-NEXT')},reads=0,next_at=0,incentive_at=0,
            incentives={},settlement_at={},rejected={})
        def call(method,path,params=None):
            if path=='/markets/trades':return dict(trades=[dict(created_time=iso(now-10),yes_price_dollars='.45',count_fp='5')]*30)
            if path.endswith('/orderbook'):return dict(orderbook_fp=dict(yes_dollars=[['.42','100']],no_dollars=[['.52','100']]))
            raise AssertionError('Read-only screening must not fetch event pages or incentive catalogues: '+path)
        h.verified_data.call.side_effect=call;return h
    async def test_only_one_cached_candidate_is_verified_per_minute_with_no_orders_or_catalogue_calls(self):
        at=[100000.0];h=self.host(at[0])
        with patch('services.paper_demo.shadow.market_maker.time',Mock(wraps=time,time=lambda:at[0])):
            await maker_once(h);self.assertEqual(h.verified_data.call.call_count,2);h.put.assert_not_called()
            self.assertEqual(h.experiments.maker_discovery['next_at'],100060)
            self.assertIn('ready',h.experiments.maker_discovery['candidates']['POL-HOT'])
            at[0]+=30;await maker_once(h);self.assertEqual(h.verified_data.call.call_count,2);h.put.assert_not_called()
            at[0]+=30;await maker_once(h);self.assertEqual(h.verified_data.call.call_count,4);h.put.assert_not_called()
    async def test_stale_telemetry_excessive_load_and_provider_cooldown_stop_even_readonly_verification(self):
        for blocked in (dict(telemetry_fresh=False),dict(backlog=10001),dict(lag_p95_seconds=5),dict(processing_p95_ms=20),dict(read_cooldown_seconds=1)):
            h=self.host(100000);h.experiments.monitoring_snapshot.return_value.update(blocked)
            with patch('services.paper_demo.shadow.market_maker.time',Mock(wraps=time,time=lambda:100000)):
                await maker_once(h)
            h.verified_data.call.assert_not_called();h.put.assert_not_called()
    async def test_cached_result_retries_without_http_only_after_healthy_capacity_returns(self):
        at=[100000.0];h=self.host(at[0])
        with patch('services.paper_demo.shadow.market_maker.time',Mock(wraps=time,time=lambda:at[0])):
            await maker_once(h);at[0]+=6
            h.experiments.search_capacity.return_value=True
            await maker_once(h)
            self.assertEqual(h.put.await_count,1);self.assertEqual(h.verified_data.call.call_count,2)
            self.assertEqual(h.put.call_args.args[0],'maker_market')
