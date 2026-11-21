"""Exchange-wide lifecycle noise must not delay owned-market execution."""
import asyncio,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.host import HostedRun

class TransportFilter(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        run=object.__new__(HostedRun);run.engine=Engine(Mock());run.queue=asyncio.Queue()
        run.engine.add_market(dict(ticker='LEGACY',close=10000),FeePolicy())
        other=Engine(Mock());other.add_market(dict(ticker='FAVORITE',close=10000),FeePolicy())
        run.experiments=SimpleNamespace(portfolios={'favorites':(other,None,None)})
        return run

    async def test_thousand_unrelated_notices_never_enter_trading_queue(self):
        run=self.fixture()
        for i in range(1000):
            await run.put('kalshi',dict(type='market_lifecycle_v2',sid=1,msg=dict(market_ticker='OTHER-'+str(i),event_type='created')))
        self.assertEqual(run.queue.qsize(),0);self.assertEqual(run.lifecycle_dropped,1000)
        self.assertFalse(hasattr(run,'input_lock'))

    async def test_all_tracked_lifecycle_states_are_forwarded_in_order(self):
        run=self.fixture()
        for t in ('LEGACY','FAVORITE'):
            for state in ('created','deactivated','determined','settled','close_date_updated','metadata_updated'):
                payload=dict(type='market_lifecycle_v2',sid=1,msg=dict(market_ticker=t,event_type=state))
                await run.put('kalshi',payload)
                source,received,_=run.queue.get_nowait()
                self.assertEqual(source,'kalshi');self.assertIs(received,payload)
        self.assertFalse(hasattr(run,'lifecycle_dropped'))

    async def test_sequenced_unknown_notice_is_not_filtered(self):
        run=self.fixture();payload=dict(type='market_lifecycle_v2',sid=11,seq=4,msg=dict(market_ticker='OTHER'))
        await run.put('kalshi',payload)
        self.assertIs(run.queue.get_nowait()[1],payload)

    async def test_book_trade_and_malformed_frames_are_not_filtered(self):
        run=self.fixture()
        for kind in ('orderbook_delta','trade','subscribed','market_lifecycle_v2'):
            payload=dict(type=kind,msg={})
            await run.put('kalshi',payload)
            self.assertIs(run.queue.get_nowait()[1],payload)

    async def test_clock_and_gap_inputs_still_reach_execution(self):
        run=self.fixture()
        for source in ('clock','gap'):
            await run.put(source,{})
            self.assertEqual(run.queue.get_nowait()[0],source)
