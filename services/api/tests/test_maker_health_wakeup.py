"""Healthy windows can trigger discovery without increasing request/settlement budgets."""
import time,unittest
from unittest.mock import Mock,AsyncMock,patch
from services.paper_demo.shadow.market_maker import maker_once,profiles,MM_FOLDERS

class MakerHealthWakeupTests(unittest.IsolatedAsyncioTestCase):
    def host(self):
        host=Mock();suite=host.experiments;suite.portfolios={}
        suite.enabled_profiles.return_value=[next(profiles())]
        suite.monitoring_snapshot.return_value=dict(admitting=False)
        suite.feed_markets.return_value={};suite.search_capacity.return_value=True
        suite.maker_discovery=dict(cursor='',candidates={},reads=0,next_at=0,incentive_at=9999,
            incentives={},settlement_at={},rejected={},series_at=9999)
        host.put=AsyncMock();return host
    async def test_paused_probe_does_not_postpone_the_next_healthy_scan_or_spend_api_budget(self):
        host=self.host();at=[1000.0]
        host.verified_data.call.return_value=dict(events=[],cursor='')
        with patch('services.paper_demo.shadow.market_maker.time',Mock(wraps=time,time=lambda:at[0])):
            await maker_once(host)
            self.assertEqual(host.experiments.maker_discovery['next_at'],0)
            host.verified_data.call.assert_not_called()
            at[0]=1001;host.experiments.monitoring_snapshot.return_value=dict(admitting=True)
            await maker_once(host)
            self.assertEqual(host.verified_data.call.call_count,1)
            self.assertEqual(host.experiments.maker_discovery['next_at'],1031)
            for n in range(1002,1031):at[0]=n;await maker_once(host)
            self.assertEqual(host.verified_data.call.call_count,1)
            at[0]=1031;await maker_once(host)
            self.assertEqual(host.verified_data.call.call_count,2)
    async def test_paused_health_retries_preserve_four_settlement_reads_per_thirty_seconds(self):
        host=self.host();at=[1000.0];e=Mock()
        e.markets={str(i):dict(close=900,paid=False) for i in range(12)}
        host.experiments.portfolios={MM_FOLDERS[0]:(e,Mock(),[])}
        host.verified_data.call.return_value=dict(market=dict(status='closed',result=None))
        with patch('services.paper_demo.shadow.market_maker.time',Mock(wraps=time,time=lambda:at[0])):
            await maker_once(host);self.assertEqual(host.verified_data.call.call_count,4)
            for n in range(1001,1030):at[0]=n;await maker_once(host)
            self.assertEqual(host.verified_data.call.call_count,4)
            at[0]=1030;await maker_once(host);self.assertEqual(host.verified_data.call.call_count,8)
        host.put.assert_not_called()
