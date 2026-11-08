"""Bad input in one virtual account cannot starve later accounts of feed data."""
import asyncio,unittest
from unittest.mock import Mock
from services.paper_demo.shadow.host import HostedRun
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.market_maker import MM_FOLDERS
from services.api.tests.test_strategy_scope import ScopeTests

class Isolation(unittest.TestCase):
    def test_portfolio_rejection_does_not_skip_later_favorites(self):
        suite,_=ScopeTests().suite();seen=[]
        for folder,(e,f,ps) in suite.portfolios.items():
            e.handle=Mock(side_effect=lambda *args,folder=folder:seen.append(folder))
        first=next(iter(suite.portfolios));suite.portfolios[first][0].handle.side_effect=ValueError('stale book event')
        with self.assertRaisesRegex(ValueError,'stale book event'):
            suite.handle('kalshi',dict(type='orderbook_delta',sid=2,seq=5,msg=dict(market_ticker='KXBTC15M-test')),1000)
        self.assertIn('favorites',seen)
        self.assertEqual(set(seen),set(suite.portfolios)-{first,*MM_FOLDERS})
        for folder in MM_FOLDERS:
            self.assertEqual(suite.portfolios[folder][0].sequences[2],5)

    def test_healthy_favorite_book_does_not_mask_legacy_resnapshot(self):
        from types import SimpleNamespace
        run=object.__new__(HostedRun);run.engine=Engine(Mock());other=Engine(Mock())
        for e in (run.engine,other):e.add_market(dict(ticker='SHARED',close=2000),FeePolicy())
        run.engine.books['SHARED'].sid=11;other.books['SHARED'].valid=True
        run.experiments=SimpleNamespace(portfolios={'favorites':(other,None,None)})
        self.assertIs(run.subscription_books()['SHARED'],run.engine.books['SHARED'])
        run.engine.books['SHARED'].valid=True;other.books['SHARED'].valid=False
        self.assertIs(run.subscription_books()['SHARED'],other.books['SHARED'])

    def test_external_market_rejection_never_invalidates_legacy_books(self):
        run=object.__new__(HostedRun);run.engine=Engine(Mock());run.engine.add_market(dict(ticker='LEGACY',close=2000),FeePolicy())
        run.engine.books['LEGACY'].valid=True
        run.reject_input('kalshi',dict(msg=dict(market_ticker='HOURLY')),ValueError('stale book event'))
        self.assertTrue(run.engine.books['LEGACY'].valid)

class HostedIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_rejection_still_delivers_same_frame_to_experiments(self):
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.engine=Mock(now=1000);run.engine.handle.side_effect=ValueError('stale book event')
        run.prepare_fees=lambda source,payload,now:payload;run.reject_input=Mock()
        run.experiments=Mock()
        run.experiments.handle.side_effect=lambda *args:run.done.set()
        payload=dict(type='orderbook_snapshot',msg=dict(market_ticker='KXBTC15M-test'))
        await run.queue.put(('kalshi',payload,1000))
        await run.consume()
        run.experiments.handle.assert_called_once_with('kalshi',payload,1000)
        run.reject_input.assert_called_once();run.audit.flush.assert_called_once()
        self.assertEqual(run.queue._unfinished_tasks,0)
