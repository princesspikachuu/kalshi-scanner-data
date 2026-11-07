"""Fee verification must survive a restored 28-market cohort without relaxing TTL."""
import asyncio
import json
import time
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from unittest.mock import Mock
from services.demo.exchange import ExchangeFailure
from services.paper_demo.exchange import ProductionData
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.host import HostedRun


class FeeInputTests(unittest.TestCase):
    def setUp(self):
        self.run=object.__new__(HostedRun)
        self.run.engine=Engine(Mock());self.run.engine.advance(1000)
        self.run.verified_fees=Mock()
        for ticker in ('BTC','WTI'):
            self.run.engine.add_market(dict(ticker=ticker,close=1900),FeePolicy())
            self.run.engine.books[ticker].valid=True
        def schedule(ticker,at):
            if ticker=='WTI':raise ExchangeFailure('paper_fee_schedule_stale')
            return 'quadratic_with_maker_fees',D('2')
        self.run.verified_fees.schedule.side_effect=schedule

    def test_unverified_snapshot_cannot_revalidate_or_trade_book(self):
        payload=dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(market_ticker='WTI',
            yes_dollars_fp=[['.1','10']],no_dollars_fp=[['.8','10']]))
        prepared=self.run.prepare_fees('kalshi',payload,1000)
        self.run.engine.handle('kalshi',prepared,1000)
        self.assertFalse(self.run.engine.books['WTI'].valid)
        self.assertEqual(self.run.engine.books['WTI'].sid,1)
        self.assertFalse(self.run.resnapshot_allowed('WTI'))
        self.assertFalse(self.run.engine.wallet.stat('WTI').valid)
        self.assertTrue(self.run.engine.books['BTC'].valid)
        self.assertEqual(self.run.engine.sequences[1],1)
        self.assertEqual(self.run.engine.fees['BTC'].maker_multiplier,0)
        self.run.prepare_fees('clock',{},1000)
        self.assertEqual(self.run.engine.fees['BTC'].maker_multiplier,2)

    def test_lifecycle_settlement_still_processed_when_fee_lookup_fails(self):
        payload=dict(type='market_lifecycle_v2',msg=dict(market_ticker='WTI',event_type='settled'))
        prepared=self.run.prepare_fees('kalshi',payload,1000)
        self.run.engine.handle('kalshi',prepared,1000)
        self.assertIn('WTI',self.run.engine.settled)

    def test_fresh_verification_does_not_silently_revalidate_gap_cycle(self):
        self.run.prepare_fees('clock',{},1000)
        self.run.verified_fees.schedule.side_effect=None
        self.run.verified_fees.schedule.return_value=('quadratic',1)
        payload=dict(type='orderbook_snapshot',sid=1,seq=1,msg=dict(market_ticker='WTI',
            yes_dollars_fp=[['.1','10']],no_dollars_fp=[['.8','10']]))
        self.run.engine.handle('kalshi',self.run.prepare_fees('kalshi',payload,1000),1000)
        self.assertTrue(self.run.engine.books['WTI'].valid)
        self.assertFalse(self.run.engine.wallet.stat('WTI').valid)


class FeeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_restored_fee_warmup_finishes_before_any_feed_tasks_start(self):
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.audit=Mock();run.verified_data=Mock()
        run.engine=Engine(Mock());run.selected={};ready=set();launched=[]
        for i in range(28):
            ticker='M'+str(i);run.selected[ticker]=ticker
            run.engine.add_market(dict(ticker=ticker,close=1900),FeePolicy())
        async def refresh(ticker):
            await asyncio.sleep(0)
            ready.add(ticker);return True
        async def feed():
            self.assertEqual(len(ready),28)
            launched.append(True);run.done.set()
        run.refresh_fee=refresh
        run.discover=run.kalshi=run.spot=run.clock=run.consume=run.control=run.fee_maintenance=feed
        await run.run()
        self.assertTrue(launched)

    async def test_28_market_refresh_is_bounded_and_not_tied_to_control_passes(self):
        run=object.__new__(HostedRun);run.done=asyncio.Event();run.engine=Engine(Mock())
        run.selected={};run.verified_fees=Mock();run.verified_fees.cache={}
        run.fee_slots=asyncio.Semaphore(4);run.fee_locks={}
        active=peak=0;finished=[]
        gate=threading.Barrier(4,timeout=2);lock=threading.Lock()
        def load(ticker,market,now):
            nonlocal active,peak
            self.assertEqual(market['event_ticker'],'event-'+ticker)
            with lock:active+=1;peak=max(peak,active)
            gate.wait()
            with lock:active-=1
        run.verified_fees.load=load
        run.verified_fees.schedule.return_value=('quadratic',1)
        original=run.refresh_fee
        async def refresh(ticker):
            result=await original(ticker)
            self.assertTrue(result);finished.append(ticker)
            if len(finished)==28:run.done.set()
            return result
        run.refresh_fee=refresh
        for i in range(28):
            ticker='M'+str(i);run.selected[ticker]=ticker
            run.engine.add_market(dict(ticker=ticker,close=time.time()+100,event_ticker='event-'+ticker),FeePolicy())
        await run.fee_maintenance()
        self.assertEqual(len(set(finished)),28)
        self.assertEqual(peak,4)


class SharedPacingTests(unittest.TestCase):
    def test_parallel_fee_requests_share_global_network_pacing(self):
        starts=[]
        class Response:
            status_code=200
            def __enter__(self):starts.append(time.monotonic());return self
            def __exit__(self,*args):pass
            def iter_bytes(self):yield b'{}'
        client=Mock();client.stream.side_effect=lambda *a,**k:Response()
        data=ProductionData(client=client)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _:data.call('GET','/series/KXBTC15M'),range(4)))
        self.assertEqual(data.reads,4)
        self.assertGreaterEqual(max(starts)-min(starts),.13)
