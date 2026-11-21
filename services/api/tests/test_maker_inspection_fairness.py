
"""Previously rejected leaders must not starve uninspected maker candidates."""
import time,unittest
from datetime import datetime,timezone
from unittest.mock import Mock,AsyncMock
from services.paper_demo.shadow.market_maker import maker_once,profiles
from services.paper_demo.shadow.core import FeePolicy
def iso(at):return datetime.fromtimestamp(at,timezone.utc).isoformat()
class MakerInspectionFairnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_measured_free_slots_verify_two_candidates_in_one_healthy_pass(self):
        now=time.time()
        def row(ticker,score):
            return dict(raw=dict(ticker=ticker,event_ticker='POL',open_time=iso(now-86400),close_time=iso(now+172800),status='active',
                    yes_bid_dollars='.42',no_bid_dollars='.52',volume_24h_fp='1000'),
                event=dict(series_ticker='POL',category='Politics',title='Election'),category='politics',
                score=score,at=now,retry_at=0,inspected_at=0,scheduled_events=[])
        suite=Mock();suite.portfolios={};suite.enabled_profiles.return_value=[dict(next(profiles()),revision=1)]
        suite.monitoring_snapshot.return_value=dict(admitting=True,maker_slots_free=2)
        suite.feed_markets.return_value={};suite.search_capacity.return_value=True
        suite.maker_discovery=dict(cursor='',candidates={'FIRST':row('FIRST',2),'SECOND':row('SECOND',1)},
            reads=0,next_at=0,incentive_at=now+1000,incentives={},settlement_at={},rejected={})
        host=Mock();host.experiments=suite;host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=FeePolicy())
        def call(method,path,params=None):
            if path=='/events':return dict(events=[])
            if path=='/markets/trades':
                return dict(trades=[dict(created_time=iso(now-10),yes_price_dollars='.45',count_fp='5') for _ in range(30)])
            if path in ('/markets/FIRST/orderbook','/markets/SECOND/orderbook'):
                return dict(orderbook_fp=dict(yes_dollars=[['.42','100']],no_dollars=[['.52','100']]))
            raise AssertionError(path)
        host.verified_data.call.side_effect=call
        await maker_once(host)
        self.assertEqual(host.put.await_count,2)
        self.assertEqual({call.args[1]['market']['ticker'] for call in host.put.call_args_list},{'FIRST','SECOND'})
        self.assertEqual(host.verified_data.call.call_count,5)
        self.assertEqual(suite.maker_discovery['verification_budget'],2)
        self.assertTrue(all('ready' in suite.maker_discovery['candidates'][t] for t in ('FIRST','SECOND')))

    async def test_uninspected_candidate_precedes_a_retry_of_rejected_leader(self):
        now=time.time()
        def row(ticker,score,inspected=0):
            return dict(raw=dict(ticker=ticker,event_ticker='POL',open_time=iso(now-86400),close_time=iso(now+172800),status='active',yes_bid_dollars='.42',no_bid_dollars='.52',volume_24h_fp='1000'),
                event=dict(series_ticker='POL',category='Politics',title='Election'),category='politics',score=score,at=now,retry_at=0,inspected_at=inspected,scheduled_events=[])
        suite=Mock();suite.portfolios={};suite.enabled_profiles.return_value=[dict(next(profiles()),revision=1)]
        suite.monitoring_snapshot.return_value=dict(admitting=True);suite.feed_markets.return_value={};suite.search_capacity.return_value=True
        suite.maker_discovery=dict(cursor='',candidates={'LEADER':row('LEADER',10,now-400),'FRESH':row('FRESH',1)},reads=0,next_at=0,incentive_at=now+1000,incentives={},settlement_at={},rejected={})
        host=Mock();host.experiments=suite;host.put=AsyncMock();host.fee_policy=AsyncMock(return_value=FeePolicy())
        def call(method,path,params=None):
            if path=='/events':return dict(events=[])
            if path=='/markets/trades':
                self.assertEqual(params['ticker'],'FRESH')
                return dict(trades=[dict(created_time=iso(now-10),yes_price_dollars='.45') for _ in range(30)])
            if path=='/markets/FRESH/orderbook':return dict(orderbook_fp=dict(yes_dollars=[['.42','100']],no_dollars=[['.52','100']]))
            raise AssertionError(path)
        host.verified_data.call.side_effect=call
        await maker_once(host)
        self.assertEqual(host.put.call_args.args[1]['market']['ticker'],'FRESH')
        self.assertEqual(host.verified_data.call.call_count,3)
        self.assertEqual(suite.maker_discovery['candidates']['FRESH']['trades_24h'],30)
