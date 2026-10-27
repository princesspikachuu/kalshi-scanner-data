"""Batch reads preserve per-market evidence, bounds and explicit fallback gaps."""
from dataclasses import replace
from unittest.mock import Mock
import unittest
import httpx

from services.research.archive import ArchiveStore
from services.research.evidence import KalshiEvidence,build_scopes,ManifestCache
from services.research.inventory import ProviderFailure
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
        with self.assertRaises(ProviderFailure):p.fetch(s,'',10)
        self.assertIsNone(p.cached(s,''));p.plan_batch(self.scopes[:2])
        self.assertEqual(p.fetch(s,'',10).payload['candlesticks'],[candle(s)])
        self.assertEqual(calls[-1].url.path,'/trade-api/v2'+s.request('')[0])
    def test_explicit_truncation_does_not_publish_partial_market(self):
        scopes=self.scopes[:2]
        p=self.provider(lambda _:reply(payload={'markets':[dict(market_ticker=s.ticker,candlesticks=[candle(s)]) for s in scopes], 'adjusted_end_ts':scopes[0].end_ts-60}))
        p.plan_batch(scopes)
        with self.assertRaises(ProviderFailure):p.fetch(scopes[0],'',10)
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
    def test_rejected_batch_falls_back_to_existing_per_market_route(self):
        for status in (400,404,422):
            calls=[];scope=self.scopes[0]
            def handler(request):
                calls.append(request)
                return reply(status=status) if len(calls)==1 else reply(payload=dict(ticker=scope.ticker,candlesticks=[]))
            p=self.provider(handler);p.plan_batch(self.scopes[:2])
            with self.assertRaises(ProviderFailure):p.fetch(scope,'',10)
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
