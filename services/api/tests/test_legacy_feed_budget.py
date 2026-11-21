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
        run.engine=Engine(Mock());bot=SimpleNamespace(enabled=False);run.strategy=SimpleNamespace(bots={'bot':bot},owner=lambda ticker:bot)
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
    def test_one_legacy_position_does_not_keep_other_paused_tickers_hot(self):
        run=self.fixture();run.engine.add_market(dict(ticker='IDLE',close=2000),FeePolicy())
        run.engine.wallet.lots=[Lot('l','SHARED','yes',D(1),D('.8'),D(0),1)]
        self.assertTrue(run.legacy_ticker_needed('SHARED'))
        self.assertFalse(run.legacy_ticker_needed('IDLE'))
        payload=dict(type='orderbook_snapshot',sid=9,seq=1,msg=dict(market_ticker='IDLE'))
        self.assertFalse(run.legacy_input_needed('kalshi',payload))
        self.assertFalse(run.engine.books['IDLE'].valid)
        self.assertIn('SHARED',run.subscription_books());self.assertNotIn('IDLE',run.subscription_books())

    def test_idle_legacy_copy_does_not_trigger_repeated_shared_snapshots(self):
        run=self.fixture();other=Engine(Mock());other.add_market(dict(ticker='SHARED',close=2000),FeePolicy())
        other.books['SHARED'].valid=True
        run.experiments=SimpleNamespace(portfolios={'favorites':(other,Mock(),None)},idle_feed=lambda *args:False,ticker_feed_needed=lambda *args:True)
        self.assertIs(run.subscription_books()['SHARED'],other.books['SHARED'])

class LegacyFeeReadinessScope(unittest.TestCase):
    def fixture(self):
        run=LegacyFeedBudget().fixture()
        run.selected={'legacy':'SHARED','other':'IDLE'}
        run.engine.add_market(dict(ticker='IDLE',close=2000),FeePolicy())
        run.verified_fees=Mock()
        run.engine.books['SHARED'].valid=True
        run.engine.books['IDLE'].valid=True
        return run

    def test_idle_selected_markets_do_not_reparse_fees_or_count_valid_books(self):
        run=self.fixture()
        balance=run.engine.wallet.cash
        run.legacy_ticker_needed=Mock(side_effect=AssertionError('idle owner checks must be bypassed'))
        active,books,verified,skipped=run.legacy_health_readiness(1000)
        self.assertEqual((active,books,verified,skipped),([],[],0,2))
        run.verified_fees.schedule.assert_not_called()
        run.legacy_ticker_needed.assert_not_called()
        self.assertEqual(run.engine.wallet.cash,balance)
        self.assertTrue(run.engine.books['SHARED'].valid)
        self.assertEqual(len(run.selected),2)

    def test_resume_and_per_market_pause_keep_only_running_book(self):
        run=self.fixture()
        active=SimpleNamespace(enabled=True)
        paused=SimpleNamespace(enabled=False)
        run.strategy=SimpleNamespace(bots={'SHARED':active,'IDLE':paused},
            owner=lambda t: active if t=='SHARED' else paused)
        selected,books,verified,skipped=run.legacy_health_readiness(1000)
        self.assertEqual((selected,verified,skipped),(['SHARED'],1,1))
        self.assertEqual(books,[run.engine.books['SHARED']])
        run.verified_fees.schedule.assert_called_once_with('SHARED',1000)
        paused.enabled=True
        run.verified_fees.schedule.reset_mock()
        selected,books,verified,skipped=run.legacy_health_readiness(1001)
        self.assertEqual((selected,verified,skipped),(['SHARED','IDLE'],2,0))
        self.assertEqual(run.verified_fees.schedule.call_count,2)

    def test_paused_with_position_or_order_still_verifies_and_requires_fresh_fee(self):
        run=self.fixture()
        run.engine.wallet.lots=[Lot('existing','SHARED','yes',D(1),D('.8'),D(0),1)]
        run.engine.orders={'bid':SimpleNamespace(ticker='IDLE',status='resting')}
        run.verified_fees.schedule.side_effect=lambda ticker,now: (
            (_ for _ in ()).throw(ValueError('stale fees')) if ticker=='IDLE' else ('quadratic',1)
        )
        selected,books,verified,skipped=run.legacy_health_readiness(1000)
        self.assertEqual((selected,verified,skipped),(['SHARED','IDLE'],1,0))
        self.assertEqual(len(books),2)
        self.assertEqual(run.verified_fees.schedule.call_count,2)
        self.assertEqual(run.engine.wallet.lots[0].ticker,'SHARED')
        self.assertEqual(run.engine.orders['bid'].status,'resting')

    def test_standalone_nonhosted_mode_keeps_previous_all_market_behavior(self):
        run=self.fixture()
        run.suspend_idle_feeds=False
        selected,books,verified,skipped=run.legacy_health_readiness(1000)
        self.assertEqual((selected,verified,skipped),(['SHARED','IDLE'],2,0))
        self.assertEqual(len(books),2)
        self.assertEqual(run.verified_fees.schedule.call_count,2)

    def test_expired_market_does_not_get_fee_checked_even_when_running(self):
        run=self.fixture()
        run.engine.markets['SHARED']['close']=999
        run.strategy.bots['bot'].enabled=True
        selected,books,verified,skipped=run.legacy_health_readiness(1000)
        self.assertEqual((selected,verified,skipped),(['IDLE'],1,0))
        run.verified_fees.schedule.assert_called_once_with('IDLE',1000)


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
