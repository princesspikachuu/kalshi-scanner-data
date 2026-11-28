"""Transient control SELECT timeouts must not restart the shadow executor."""
import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from psycopg.errors import QueryCanceled

from services.paper_demo.shadow.bot_catalog import BotCatalogCapacityError
from services.paper_demo.shadow.control_read_safety import (
    suspend_new_entries, restore_prior_entries,
)
from services.paper_demo.shadow.experiments import ExperimentSuite
from services.paper_demo.shadow.host import HostedRun


class ControlReadSafetyTests(unittest.TestCase):
    @staticmethod
    def host_with_financial_state():
        old=SimpleNamespace(enabled=True)
        active=SimpleNamespace(enabled=True)
        paused=SimpleNamespace(enabled=False)
        order=SimpleNamespace(status='resting',quantity=1,filled=0)
        wallet=SimpleNamespace(cash='987.50',lots=[object()])
        host=SimpleNamespace(
            profiles=[dict(series='old',id='legacy-bot')],
            strategy=SimpleNamespace(bots={'old':old}),
            experiments=SimpleNamespace(portfolios={'favorites':(
                SimpleNamespace(wallet=wallet,orders={'bid':order}),
                SimpleNamespace(bots={'active':active,'paused':paused}),
                [dict(series='active',id='active-bot'),dict(series='paused',id='paused-bot')])}))
        return host,old,active,paused,wallet,order

    @staticmethod
    def rows(*ids):
        return [dict(parameters=dict(id=ident)) for ident in ids]

    def test_freeze_preserves_wallet_existing_bids_and_pause_flags(self):
        host,old,active,paused,wallet,order=self.host_with_financial_state()
        original_lots=wallet.lots
        self.assertEqual(suspend_new_entries(host),2)
        self.assertFalse(old.enabled)
        self.assertFalse(active.enabled)
        self.assertFalse(paused.enabled)
        self.assertEqual(wallet.cash,'987.50')
        self.assertIs(wallet.lots,original_lots)
        self.assertEqual((order.status,order.quantity,order.filled),('resting',1,0))
        self.assertEqual(suspend_new_entries(host),0)
        self.assertEqual(restore_prior_entries(host,self.rows('legacy-bot','active-bot','paused-bot')),2)
        self.assertTrue(old.enabled)
        self.assertTrue(active.enabled)
        self.assertFalse(paused.enabled)
        self.assertIsNone(host._suspended_entry_bots)

    def test_repeated_errors_keep_original_flags_not_intermediate_changes(self):
        host,old,active,paused,wallet,order=self.host_with_financial_state()
        suspend_new_entries(host)
        active.enabled=True  # An unrelated mutation must not replace saved state.
        self.assertEqual(suspend_new_entries(host),0)
        self.assertEqual(restore_prior_entries(host,self.rows('legacy-bot','active-bot','paused-bot')),2)
        self.assertTrue(active.enabled)
        self.assertFalse(paused.enabled)
        self.assertEqual(restore_prior_entries(host,self.rows('legacy-bot','active-bot','paused-bot')),0)

    def test_new_verified_pause_still_cancels_existing_maker_bids(self):
        host,old,active,paused,wallet,order=self.host_with_financial_state()
        ticker='KXBTC15M-TEST'
        profile=dict(id='favorite-bot',series='KXBTC15M',paused_markets=[])
        engine=SimpleNamespace(markets={ticker:{}},books={ticker:SimpleNamespace(valid=True)},
                               cancel_buys=Mock())
        fleet=SimpleNamespace(bots={'KXBTC15M':active},owner=lambda t:active)
        suite=ExperimentSuite.__new__(ExperimentSuite)
        suite.portfolios={'favorites':(engine,fleet,[profile])}
        suite.ticker_exposed=lambda e,t:True
        host.experiments=suite
        self.assertEqual(suspend_new_entries(host),2)
        self.assertFalse(active.enabled)
        # No entries admitted while controls cannot be verified.
        self.assertEqual(restore_prior_entries(host,self.rows('legacy-bot','favorite-bot')),2)
        suite.control([dict(parameters=dict(id='favorite-bot',contracts='1'),
                            progress=dict(desired='paused'))],'demo')
        engine.cancel_buys.assert_called_once_with(ticker)
        self.assertFalse(active.enabled)
        self.assertTrue(old.enabled)

    def test_missing_or_empty_verified_catalog_cannot_reenable_removed_bots(self):
        host,old,active,paused,wallet,order=self.host_with_financial_state()
        suspend_new_entries(host)
        self.assertEqual(restore_prior_entries(host,self.rows('legacy-bot')),1)
        self.assertTrue(old.enabled)
        self.assertFalse(active.enabled)  # Control row removed; no stale authority.
        self.assertFalse(paused.enabled)
        suspend_new_entries(host)
        self.assertEqual(restore_prior_entries(host,[]),0)
        self.assertFalse(old.enabled)
        self.assertFalse(active.enabled)

    def test_actual_control_coroutine_catches_only_read_timeouts(self):
        async def scenario(error,expected_frozen):
            host=HostedRun.__new__(HostedRun)
            host.done=asyncio.Event()
            host.outer_stop=asyncio.Event()
            host.store=SimpleNamespace(pool=object())
            host.profiles=[dict(series='old',id='legacy-bot')]
            host.strategy=SimpleNamespace(bots={'old':SimpleNamespace(enabled=True)})
            host.experiments=SimpleNamespace(portfolios={'favorites':(
                object(),SimpleNamespace(bots={'new':SimpleNamespace(enabled=True)}),
                [dict(series='new',id='new-bot')])})
            @asynccontextmanager
            async def mutex():
                yield
            host.state_mutex=mutex
            class Audit:
                async def durable_io(self,fn,*args):
                    if fn.__name__=='load_bots':
                        host.done.set()
                        raise error
                    return {'mode':'demo'}
            host.audit=Audit()
            with patch('services.paper_demo.shadow.host.asyncio.sleep',new_callable=AsyncMock):
                with patch('builtins.print'):
                    if expected_frozen:
                        await host.control()
                    else:
                        with self.assertRaises(BotCatalogCapacityError):
                            await host.control()
            self.assertEqual(host.strategy.bots['old'].enabled,not expected_frozen)
            self.assertEqual(host.experiments.portfolios['favorites'][1].bots['new'].enabled,
                             not expected_frozen)
        asyncio.run(scenario(QueryCanceled('statement timeout'),True))
        asyncio.run(scenario(BotCatalogCapacityError('too many bots'),False))


if __name__=='__main__':
    unittest.main()
