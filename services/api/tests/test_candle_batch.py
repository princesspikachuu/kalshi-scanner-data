"""Batch reads preserve per-market evidence, bounds and explicit fallback gaps."""
from dataclasses import replace
from datetime import datetime,timezone
import math
from unittest.mock import Mock
import unittest
import httpx

from services.research.archive import ArchiveStore
from services.research.evidence import KalshiEvidence,build_scopes,ManifestCache
from services.research.inventory import ProviderFailure,ProviderDeferred
from test_evidence import BATCH,CANDIDATE,candle
from test_normalize import MemoryObjects
from test_kalshi import reply


class CandleBatchTests(unittest.TestCase):
    def setUp(self):
        self.archives=ArchiveStore(MemoryObjects())
        candidates=tuple(replace(CANDIDATE,ticker='KXBTC15M-'+str(i),event_ticker='E'+str(i)) for i in range(100))
        plan=build_scopes(replace(BATCH,candidates=candidates),self.archives,lookback_seconds=1020,resources=('candles',))
        self.scopes=[s for s in plan.scopes if s.source=='recent']
    def provider(self,handler):
        p=KalshiEvidence(archives=self.archives,transport=httpx.MockTransport(handler));self.addCleanup(p.close);return p
    def test_one_http_read_covers_100_markets_with_exact_verified_batch_provenance(self):
        calls=[]
        def handler(request):
            calls.append(request)
            return reply(payload={'markets':[dict(market_ticker=s.ticker,candlesticks=[candle(s)]) for s in reversed(self.scopes)]})
        p=self.provider(handler);p.plan_batch(self.scopes)
        first=p.fetch(self.scopes[0],'',10)
        for scope in self.scopes:
            value=p.cached(scope,'');self.assertIsNotNone(value)
            self.assertEqual(value.payload['ticker'],scope.ticker)
            self.assertEqual(value.payload['candlesticks'],[candle(scope)])
            raw=self.archives.read(value.payload['batch_receipt'])
            self.assertEqual(len(raw['response']['markets']),100)
        self.assertEqual(first,p.cached(self.scopes[0],''));self.assertEqual(len(calls),1)
        self.assertEqual(calls[0].url.path,'/trade-api/v2/markets/candlesticks')
        self.assertEqual(len(calls[0].url.params['market_tickers'].split(',')),100)
    def test_omitted_member_is_retried_individually_never_invented_empty(self):
        s=self.scopes[0];calls=[]
        def handler(r):
            calls.append(r)
            return reply(payload={'markets':[]} if len(calls)==1 else dict(ticker=s.ticker,candlesticks=[candle(s)]))
        p=self.provider(handler);p.plan_batch(self.scopes[:2])
        with self.assertRaises(ProviderDeferred):p.fetch(s,'',10)
        self.assertIsNone(p.cached(s,''));p.plan_batch(self.scopes[:2])
        self.assertEqual(p.fetch(s,'',10).payload['candlesticks'],[candle(s)])
        self.assertEqual(calls[-1].url.path,'/trade-api/v2'+s.request('')[0])
    def test_explicit_truncation_does_not_publish_partial_market(self):
        scopes=self.scopes[:2]
        p=self.provider(lambda _:reply(payload={'markets':[dict(market_ticker=s.ticker,candlesticks=[candle(s)]) for s in scopes], 'adjusted_end_ts':scopes[0].end_ts-60}))
        p.plan_batch(scopes)
        with self.assertRaises(ProviderDeferred):p.fetch(scopes[0],'',10)
        self.assertTrue(all(p.cached(s,'') is None for s in scopes))
    def test_foreign_or_duplicate_market_fails_whole_batch_before_caching(self):
        for ticker in ('FOREIGN',self.scopes[0].ticker):
            entries=[dict(market_ticker=self.scopes[0].ticker,candlesticks=[]),dict(market_ticker=ticker,candlesticks=[])]
            p=self.provider(lambda _:reply(payload={'markets':entries}));p.plan_batch(self.scopes[:2])
            with self.assertRaises(ProviderFailure):p.fetch(self.scopes[0],'',10)
            self.assertFalse(p.responses)
    def test_worst_case_window_bound_and_archived_scope_exclusion(self):
        far=replace(self.scopes[1],start_ts=self.scopes[1].start_ts+7*86400,end_ts=self.scopes[1].end_ts+7*86400,
                    close_time='2026-11-01T12:00:00Z')
        p=self.provider(lambda _:self.fail('No network during planning'))
        p.plan_batch([self.scopes[0],far]);self.assertFalse(p.batch)
        p.plan_batch([replace(s,source='historical') for s in self.scopes]);self.assertFalse(p.batch)

    def test_anchor_locality_fills_dense_batch_before_far_window_neighbors(self):
        anchor=self.scopes[0];far=[]
        for i in range(20):
            offset=6*3600
            far.append(replace(anchor,ticker='KXBTC15M-FAR-'+str(i),start_ts=anchor.start_ts+offset,
                end_ts=anchor.end_ts+offset,close_time=datetime.fromtimestamp(anchor.end_ts+offset,timezone.utc).isoformat().replace('+00:00','Z')))
        # Old UUID/input ordering admitted far windows first, widening every
        # later trial and limiting this fixture to 23 markets instead of 100.
        original=[anchor]+far+self.scopes[1:];before=list(original)
        p=self.provider(lambda _:self.fail('Planning performs no HTTP request'))
        p.plan_batch(original)
        self.assertEqual(len(p.batch),100);self.assertEqual(p.batch[0],anchor)
        self.assertEqual({s.key for s in p.batch},{s.key for s in self.scopes})
        span=max(s.end_ts for s in p.batch)-min(s.start_ts for s in p.batch)
        self.assertLessEqual(len(p.batch)*(math.ceil(span/60)+1),9000)
        self.assertEqual(original,before)  # Unselected work remains available.
        selected={s.key for s in p.batch};p.plan_batch([s for s in original if s.key not in selected])
        self.assertEqual({s.key for s in p.batch},{s.key for s in far})
    def test_rejected_batch_falls_back_to_existing_per_market_route(self):
        for status in (400,404,422):
            calls=[];scope=self.scopes[0]
            def handler(request):
                calls.append(request)
                return reply(status=status) if len(calls)==1 else reply(payload=dict(ticker=scope.ticker,candlesticks=[]))
            p=self.provider(handler);p.plan_batch(self.scopes[:2])
            with self.assertRaises(ProviderDeferred):p.fetch(scope,'',10)
            self.assertFalse(p.responses);p.plan_batch(self.scopes[:2])
            self.assertEqual(p.fetch(scope,'',10).payload,dict(ticker=scope.ticker,candlesticks=[]))
            self.assertEqual(calls[-1].url.path,'/trade-api/v2'+scope.request('')[0])

    def test_batch_rate_limit_is_not_hidden_or_fanned_out(self):
        p=self.provider(lambda _:reply(status=429,headers={'Retry-After':'17'}));p.plan_batch(self.scopes[:2])
        with self.assertRaises(ProviderFailure) as caught:p.fetch(self.scopes[0],'',10)
        self.assertEqual(caught.exception.code,'provider_rate_limit');self.assertEqual(caught.exception.cooldown,17)
        self.assertFalse(p.responses)
    def test_manifest_cache_reuses_verified_receipt_without_crossing_identity(self):
        archive=Mock(wraps=self.archives);cache=ManifestCache(archive)
        scope=self.scopes[0];receipt=scope.manifest_receipt()
        self.assertEqual(cache.read(receipt),cache.read(receipt));archive.read.assert_called_once()
        changed={**receipt,'byte_length':receipt['byte_length']+1}
        with self.assertRaises(Exception):cache.read(changed)
        self.assertEqual(archive.read.call_count,2)

    def test_interleaved_campaigns_do_not_refetch_unconsumed_batch_members(self):
        calls=[]
        groups=[self.scopes[i:i+12] for i in range(0,96,12)]
        by_ticker={s.ticker:s for s in self.scopes}
        def handler(request):
            calls.append(request)
            if 'market_tickers' not in request.url.params:
                scope=by_ticker[request.url.path.split('/')[-2]]
                return reply(payload=dict(ticker=scope.ticker,candlesticks=[candle(scope)]))
            return reply(payload=dict(markets=[dict(market_ticker=t,candlesticks=[candle(by_ticker[t])])
                for t in request.url.params['market_tickers'].split(',')]))
        p=self.provider(handler)
        # The scheduler rotates among eight loads after each bounded step.
        # Every batch response must survive other campaigns fetching a batch.
        for offset in range(12):
            for scopes in groups:
                scope=scopes[offset]
                p.plan_batch(scopes[offset:])
                value=p.cached(scope,'')
                if value is None:value=p.fetch(scope,'',10)
                self.assertEqual(value.payload['candlesticks'],[candle(scope)])
                if 'batch_receipt' in value.payload:
                    self.assertEqual(self.archives.read(value.payload['batch_receipt'])['format'],'candle-batch-v1')
                p.acknowledge(scope)
        self.assertEqual(len(calls),8)

    def test_retained_projections_are_bounded_isolated_and_restart_is_a_cache_miss(self):
        from services.research.cache import ByteCache
        scopes=self.scopes[:2]
        def handler(_):return reply(payload=dict(markets=[dict(market_ticker=s.ticker,candlesticks=[candle(s)]) for s in scopes]))
        p=self.provider(handler);p.plan_batch(scopes);p.fetch(scopes[0],'',10)
        value=p.cached(scopes[0],'');value.payload['candlesticks'].clear()
        self.assertEqual(p.cached(scopes[0],'').payload['candlesticks'],[candle(scopes[0])])
        self.assertLessEqual(p.responses.size,8*1024*1024)
        before=p.responses.size;p.acknowledge(scopes[0]);self.assertLess(p.responses.size,before)
        self.assertIsNotNone(p.cached(scopes[1],''))
        self.assertIsNone(self.provider(handler).cached(scopes[1],''))
        # Oversized projections fall back individually without another batch loop.
        p=self.provider(handler);p.responses=ByteCache(1);p.plan_batch(scopes)
        with self.assertRaises(ProviderDeferred):p.fetch(scopes[0],'',10)
        p.plan_batch(scopes);self.assertFalse(p.batch);self.assertFalse(p.responses)

    def test_other_batch_failure_does_not_discard_verified_unused_projections(self):
        calls=[];scopes=self.scopes[:2]
        def handler(request):
            calls.append(request)
            if len(calls)>1:return reply(status=429,headers={'Retry-After':'17'})
            return reply(payload=dict(markets=[dict(market_ticker=s.ticker,candlesticks=[candle(s)]) for s in scopes]))
        p=self.provider(handler);p.plan_batch(scopes);p.fetch(scopes[0],'',10)
        p.plan_batch(self.scopes[2:4])
        with self.assertRaises(ProviderFailure):p.fetch(self.scopes[2],'',10)
        self.assertEqual(p.cached(scopes[1],'').payload['candlesticks'],[candle(scopes[1])])
