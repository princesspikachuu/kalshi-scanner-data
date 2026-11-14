"""Approved recovery must require explicit final production settlement evidence."""
import asyncio
import time
import unittest
from unittest.mock import Mock,AsyncMock
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.host import HostedRun

class SettlementRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def run_fixture(self,enabled=False):
        run=object.__new__(HostedRun);run.engine=Engine(Mock());run.allow_rest_settlement_recovery=enabled
        run.engine.add_market(dict(ticker='BTC',close=time.time()-10),FeePolicy())
        run.settlement_checks={};run.api=Mock();run.put=AsyncMock()
        run.api.fetch=AsyncMock(return_value=dict(market=dict(ticker='BTC',status='finalized',result='yes')))
        return run

    async def test_no_rest_poll_or_barrier_release_without_opt_in(self):
        run=self.run_fixture()
        self.assertFalse(await run.settlement_observed('BTC'))
        run.api.fetch.assert_not_called();run.put.assert_not_called()
        self.assertNotIn('BTC',run.engine.settled)

    async def test_opt_in_accepts_only_finalized_matching_market_result(self):
        run=self.run_fixture(True)
        self.assertFalse(await run.settlement_observed('BTC'))
        run.put.assert_awaited_once_with('rest_settlement_confirmed',dict(ticker='BTC',status='finalized',result='yes'))
        self.assertNotIn('BTC',run.engine.settled)  # Queued, not mutated by I/O task.
        self.assertFalse(await run.settlement_observed('BTC'))
        run.api.fetch.assert_awaited_once()

    async def test_pending_unknown_and_wrong_market_never_release_barrier(self):
        for market in (dict(ticker='BTC',status='determined',result='yes'),
                       dict(ticker='BTC',status='finalized',result=''),
                       dict(ticker='OTHER',status='finalized',result='yes')):
            run=self.run_fixture(True);run.api.fetch.return_value=dict(market=market)
            self.assertFalse(await run.settlement_observed('BTC'))
            run.put.assert_not_called()

    async def test_consumer_records_actual_rest_provenance_and_keeps_invalid_cycle(self):
        run=self.run_fixture(True);run.done=asyncio.Event();run.queue=asyncio.Queue();run.audit=Mock()
        run.verified_fees=Mock();run.verified_fees.schedule.return_value=('quadratic',1)
        run.engine.wallet.stat('BTC').valid=False
        original=run.audit.flush
        def finish():run.done.set();original()
        run.audit.flush=finish
        await run.queue.put(('rest_settlement_confirmed',dict(ticker='BTC',status='finalized',result='yes'),time.time()))
        await run.consume()
        self.assertIn('BTC',run.engine.settled)
        self.assertEqual(run.engine.markets['BTC']['settlement_confirmation'],'production_rest')
        self.assertFalse(run.engine.wallet.stat('BTC').valid)
        run.engine.audit.log.assert_called_with(run.engine.now,'SETTLEMENT_RECOVERED',run.engine.wallet,
            ticker='BTC',reason='production REST finalized result; WebSocket event missed')
