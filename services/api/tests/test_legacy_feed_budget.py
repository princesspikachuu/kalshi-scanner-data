"""An idle legacy engine cannot consume capacity or hide active strategy books."""
import asyncio,unittest
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import Mock
from services.paper_demo.shadow.core import Engine,FeePolicy,Lot
from services.paper_demo.shadow.host import HostedRun

class LegacyFeedBudget(unittest.TestCase):
    def fixture(self):
        run=object.__new__(HostedRun);run.suspend_idle_feeds=True
        run.engine=Engine(Mock());run.strategy=SimpleNamespace(bots={'bot':SimpleNamespace(enabled=False)})
        run.engine.add_market(dict(ticker='SHARED',close=2000),FeePolicy())
        return run
    def test_idle_book_bursts_skip_legacy_but_lifecycle_stays_enabled(self):
        run=self.fixture()
        for _ in range(1000):self.assertFalse(run.legacy_input_needed('kalshi',dict(type='orderbook_delta')))
        self.assertEqual(run.legacy_inputs_skipped,1000)
        self.assertTrue(run.legacy_input_needed('kalshi',dict(type='market_lifecycle_v2')))
        self.assertTrue(run.legacy_input_needed('clock',{}))
    def test_legacy_exposure_and_orders_require_full_processing(self):
        run=self.fixture();run.engine.wallet.lots=[Lot('l','SHARED','yes',D(1),D('.8'),D(0),1)]
        self.assertTrue(run.legacy_input_needed('kalshi',dict(type='trade')))
        run.engine.wallet.lots=[];run.engine.orders={'o':SimpleNamespace(status='pending')}
        self.assertTrue(run.legacy_input_needed('kalshi',dict(type='orderbook_snapshot')))
    def test_resume_invalidates_skipped_book_and_sequence_before_execution(self):
        run=self.fixture();run.engine.books['SHARED'].valid=True;run.engine.sequences[11]=4
        self.assertFalse(run.legacy_input_needed('kalshi',dict(type='trade')))
        run.strategy.bots['bot'].enabled=True
        self.assertTrue(run.legacy_input_needed('clock',{}))
        self.assertFalse(run.engine.books['SHARED'].valid);self.assertEqual(run.engine.sequences,{})
        self.assertFalse(run.legacy_feed_suspended)
    def test_idle_legacy_copy_does_not_trigger_repeated_shared_snapshots(self):
        run=self.fixture();other=Engine(Mock());other.add_market(dict(ticker='SHARED',close=2000),FeePolicy())
        other.books['SHARED'].valid=True
        run.experiments=SimpleNamespace(portfolios={'favorites':(other,Mock(),None)},idle_feed=lambda *args:False)
        self.assertIs(run.subscription_books()['SHARED'],other.books['SHARED'])

class LegacyDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_full_stream_still_reaches_active_experiments(self):
        run=LegacyFeedBudget().fixture();run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine.handle=Mock();run.prepare_fees=Mock()
        run.experiments=Mock();run.experiments.handle.side_effect=lambda *args:run.done.set()
        payload=dict(type='trade',msg=dict(market_ticker='SHARED'))
        await run.queue.put(('kalshi',payload,1000))
        await run.consume()
        run.prepare_fees.assert_not_called();run.engine.handle.assert_not_called()
        run.experiments.handle.assert_called_once_with('kalshi',payload,1000)
        self.assertEqual(run.queue._unfinished_tasks,0)
