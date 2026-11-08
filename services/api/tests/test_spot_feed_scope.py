"""Spot data is required only by legacy strategies and cannot gap unrelated books."""
import asyncio,unittest
from decimal import Decimal as D
from unittest.mock import Mock,patch
from services.paper_demo.shadow.host import HostedRun
from services.paper_demo.shadow.runner import ForwardRun
from services.paper_demo.shadow.core import Engine,Lot
from services.api.tests.test_strategy_scope import ScopeTests
from services.api.tests.test_strategy_folders import market

class SpotScope(unittest.TestCase):
    def test_legacy_feed_kept_for_enabled_bots_exposure_and_pending_orders(self):
        run=object.__new__(HostedRun);run.engine=Engine(Mock());bot=Mock(enabled=False)
        run.strategy=Mock(bots={'bot':bot})
        self.assertFalse(run.spot_required());bot.enabled=True
        self.assertTrue(run.spot_required());bot.enabled=False
        run.engine.wallet.lots=[Lot('l','T','yes',D(1),D('.8'),D(0),1)]
        self.assertTrue(run.spot_required());run.engine.wallet.lots=[]
        run.engine.orders={'o':Mock(status='resting')};self.assertTrue(run.spot_required())
    def test_spot_disconnect_leaves_favorite_book_valid_but_kalshi_gap_invalidates_it(self):
        suite,_=ScopeTests().suite();e,f,ps=suite.portfolios['favorites'];e.now=200
        market(e);suite.handle('gap',dict(reason='spot stream disconnected'),201)
        self.assertTrue(e.books['KXBTC15M-test'].valid)
        suite.handle('gap',dict(reason='Kalshi stream disconnected; resnapshot required'),202)
        self.assertFalse(e.books['KXBTC15M-test'].valid)

class IdleSpot(unittest.IsolatedAsyncioTestCase):
    async def test_idle_worker_does_not_connect_or_emit_disconnect_gaps(self):
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.engine=Engine(Mock());run.strategy=Mock(bots={})
        async def pause(_):run.done.set()
        with patch('services.paper_demo.shadow.runner.connect') as connect,patch('services.paper_demo.shadow.runner.asyncio.sleep',side_effect=pause):
            await run.spot()
        connect.assert_not_called()
