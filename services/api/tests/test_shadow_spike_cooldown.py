"""A spike cancels entries temporarily without silently disabling a whole cycle."""
import unittest
from decimal import Decimal as D
from unittest.mock import Mock,AsyncMock
from services.paper_demo.shadow.core import Engine,FeePolicy,ConvexityStrategy
from services.paper_demo.shadow.host import HostedRun

class SpikeCooldownTests(unittest.TestCase):
    def fixture(self):
        e=Engine(Mock());e.advance(1000)
        e.add_market(dict(ticker='KXBTC15M-test',close=1900),FeePolicy())
        b=ConvexityStrategy(e,contracts=1,require_spot_warmup=False)
        e.handle('kalshi',self.snapshot(1),1000);e.advance(1000.2)
        for i in range(60):e.spot.add(100000+i%2,941.2+i,941.2+i)
        e.handle('spot',dict(price=100100,event_time=1000.3),1000.3)
        return e,b
    def snapshot(self,seq):
        return dict(type='orderbook_snapshot',sid=1,seq=seq,msg=dict(market_ticker='KXBTC15M-test',yes_dollars_fp=[['.3','100']],no_dollars_fp=[['.6','100']]))
    def recover(self,e,at=1010.31):
        e.handle('kalshi',self.snapshot(2),at-.01)
        e.handle('spot',dict(price=100100,event_time=at),at)
        e.handle('clock',{},at)

    def test_unfilled_bids_cancel_then_resume_after_stable_cooldown(self):
        e,b=self.fixture();self.assertAlmostEqual(e.safety_until,1010.3)
        self.assertNotIn('KXBTC15M-test',b.halted)
        e.handle('clock',{},1000.5)
        self.assertTrue(all(o.status=='cancelled' for o in e.orders.values()))
        self.recover(e)
        self.assertEqual(sum(o.status=='pending' for o in e.orders.values()),2)
        self.assertTrue(all(o.price==D('.1') for o in e.orders.values()))

    def test_sustained_spike_does_not_repeat_market_audits_per_print(self):
        e,b=self.fixture();e.audit.log.reset_mock();initial=e.safety_until
        for i in range(1000):
            at=1000.31+i*.0001
            e.handle('spot',dict(price=100100,event_time=at),at)
        self.assertGreater(e.safety_until,initial)
        e.audit.log.assert_not_called()
        self.assertEqual(sum(item[2]=='cancel' for item in e.pending),2)

    def test_new_spike_extends_the_pause(self):
        e,b=self.fixture()
        e.handle('spot',dict(price=100200,event_time=1005),1005)
        self.assertAlmostEqual(e.safety_until,1015)
        self.assertEqual(len(e.orders),2)

    def test_fill_during_cancel_latency_prevents_reentry(self):
        e,b=self.fixture()
        e.handle('kalshi',dict(type='trade',msg=dict(market_ticker='KXBTC15M-test',trade_id='race',
            yes_price_dollars='.1',count_fp='1',taker_side='no',ts_ms=1000350)),1000.35)
        self.assertEqual(e.wallet.inventory('KXBTC15M-test','yes'),1)
        self.recover(e)
        self.assertEqual(len(e.orders),2)
        self.assertIn(('KXBTC15M-test',1),b.locked)

    def test_cooldown_never_reopens_entry_during_hard_freeze(self):
        e,b=self.fixture();self.recover(e,1782)
        self.assertEqual(len(e.orders),2)
        self.assertFalse(any(o.status in ('resting','pending') for o in e.orders.values()))

    def test_other_permanent_safety_halts_are_preserved(self):
        e,b=self.fixture();b.halted.add('KXBTC15M-test');self.recover(e)
        self.assertEqual(len(e.orders),2)
        self.assertIn('KXBTC15M-test',b.halted)

class MetadataRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_uses_verified_fee_metadata_without_duplicate_series_request(self):
        run=object.__new__(HostedRun);run.api=Mock();run.api.fetch=AsyncMock()
        run.verified_fees=Mock();run.verified_fees.schedule.return_value=('quadratic',1)
        run.fee_policy=AsyncMock(return_value=FeePolicy())
        metadata,fee=await run.market_metadata(dict(ticker='KXBTC15M-test'),'KXBTC15M')
        self.assertEqual(metadata,dict(fee_type='quadratic',fee_multiplier=1))
        run.api.fetch.assert_not_called()
