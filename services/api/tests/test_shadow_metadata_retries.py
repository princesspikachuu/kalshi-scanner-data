"""REST metadata failures cannot masquerade as loss of a healthy WS feed."""
import time
import unittest
from datetime import datetime,timezone
from unittest.mock import AsyncMock,Mock,patch
from services.demo.exchange import ExchangeFailure
from services.paper_demo.shadow.core import Engine,FeePolicy
from services.paper_demo.shadow.runner import ForwardRun

class MetadataRetryTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        run=object.__new__(ForwardRun);run.engine=Engine(Mock());run.engine.advance(time.time())
        run.selected={};run.profiles=[];run.api=Mock();run.records=[]
        async def put(source,payload):
            run.records.append((source,payload))
            if source=='settlement':run.engine.markets[payload['ticker']]['paid']=True
            else:run.engine.handle(source,payload,run.engine.now)
        run.put=put
        run.engine.add_market(dict(ticker='KXBTC15M-known',close=time.time()+300),FeePolicy())
        run.engine.books['KXBTC15M-known'].valid=True
        run.engine.books['KXBTC15M-known'].at=run.engine.now
        run.engine.sequences={7:10}
        for i in range(60):run.engine.spot.add(100000,run.engine.now-59+i,run.engine.now-59+i)
        return run

    async def test_inventory_429_preserves_prices_spot_and_valid_cycle(self):
        run=self.fixture();run.profiles=[dict(series='MISSING')]
        run.api.fetch=AsyncMock(side_effect=RuntimeError('Public data HTTP 429'))
        await run.discover_once()
        self.assertEqual([s for s,p in run.records],['metadata_retry'])
        self.assertEqual(run.records[0][1]['status'],429)
        self.assertTrue(run.engine.books['KXBTC15M-known'].valid)
        self.assertTrue(run.engine.wallet.stat('KXBTC15M-known').valid)
        self.assertTrue(run.engine.spot.ready(run.engine.now))
        self.assertEqual(run.engine.sequences,{7:10})

    async def test_failed_settlement_lookup_does_not_block_other_series(self):
        run=self.fixture();run.selected={'BAD':'BAD-old','GOOD':'GOOD-old'}
        for t in run.selected.values():
            run.engine.add_market(dict(ticker=t,close=run.engine.now-1),FeePolicy())
            run.engine.settled.add(t);run.engine.closed_reports.add(t)
        async def fetch(path,*args):
            if path.endswith('BAD-old'):raise RuntimeError('Public data HTTP 503')
            return dict(market=dict(ticker='GOOD-old',status='finalized',result='yes'))
        run.api.fetch=AsyncMock(side_effect=fetch)
        await run.discover_once()
        self.assertIn('BAD',run.selected);self.assertNotIn('GOOD',run.selected)
        self.assertTrue(run.engine.markets['GOOD-old']['paid'])
        self.assertEqual([s for s,p in run.records],['metadata_retry','settlement'])
        self.assertTrue(run.engine.books['KXBTC15M-known'].valid)

    async def test_one_bad_fee_response_does_not_block_other_market_discovery(self):
        run=self.fixture();now=time.time();stamp=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
        run.profiles=[dict(series=s,id=s,name=s,version='1') for s in ('BAD','GOOD')]
        rows=[dict(ticker=s+'-new',status='active',open_time=stamp(now-10),
            close_time=stamp(now+300),event_ticker=s+'-event') for s in ('BAD','GOOD')]
        async def fetch(path,*args):
            return dict(markets=rows) if path=='/markets' else dict(series=dict(fee_type='quadratic',fee_multiplier=1))
        async def fee(market,metadata):
            if market['ticker']=='BAD-new':raise ExchangeFailure('paper_data_unavailable',status=503)
            return FeePolicy()
        run.api.fetch=AsyncMock(side_effect=fetch);run.fee_policy=fee
        await run.discover_once()
        self.assertEqual(run.selected,{'GOOD':'GOOD-new'})
        self.assertIn('GOOD-new',run.engine.markets)
        self.assertEqual([s for s,p in run.records],['metadata_retry','market'])
        self.assertEqual(run.records[0][1]['series'],'BAD')

    async def test_inactive_family_is_not_polled_again_for_15_minutes(self):
        run=self.fixture();run.profiles=[dict(series='IDLE')]
        run.api.fetch=AsyncMock(return_value=dict(markets=[]));now=time.time()
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):
            await run.discover_once();await run.discover_once()
        run.api.fetch.assert_awaited_once()
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now+901):await run.discover_once()
        self.assertEqual(run.api.fetch.await_count,2)

    async def test_known_rolling_family_retries_quickly_at_market_boundary(self):
        run=self.fixture();run.known_active={'KNOWN'};run.profiles=[dict(series='KNOWN')]
        run.api.fetch=AsyncMock(return_value=dict(markets=[]));now=time.time()
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now):await run.discover_once()
        with patch('services.paper_demo.shadow.runner.time.time',return_value=now+3):await run.discover_once()
        self.assertEqual(run.api.fetch.await_count,2)

    async def test_shared_cooldown_creates_one_warning_not_one_per_bot(self):
        run=self.fixture()
        for i in range(28):await run.metadata_unavailable('fees',ExchangeFailure('paper_data_rate_limited'),series=str(i))
        self.assertEqual(len(run.records),1)
        self.assertIsNone(run.records[0][1]['ticker'])
        self.assertTrue(run.engine.spot.ready(run.engine.now))

class AuthenticatedDiscoveryTests(unittest.TestCase):
    def test_public_market_reads_use_connected_read_key_when_available(self):
        from services.paper_demo.shadow.runner import ProductionData
        signer=Mock();signer.headers.return_value={'test-auth':'read-only-test'}
        session=Mock();session.get.return_value.status_code=200;session.get.return_value.json.return_value={'markets':[]}
        context=Mock();context.__enter__=Mock(return_value=session);context.__exit__=Mock(return_value=False)
        with patch('services.paper_demo.shadow.runner.requests.Session',return_value=context),patch('services.paper_demo.shadow.runner.PRODUCTION_READS.wait'):
            self.assertEqual(ProductionData(signer).get('/markets',{'limit':1}),{'markets':[]})
        signer.headers.assert_called_once_with('GET','/trade-api/v2/markets')
        self.assertEqual(session.get.call_args.kwargs['headers'],{'test-auth':'read-only-test'})
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])
