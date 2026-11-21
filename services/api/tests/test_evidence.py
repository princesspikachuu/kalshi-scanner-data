"""Raw evidence plans/adapters: stub HTTP and immutable in-memory objects only."""
from dataclasses import replace
from datetime import datetime, timezone
import unittest

import httpx

from services.research.archive import ArchiveInvalid, ArchiveStore
from services.research.evidence import (build_scopes,scope_for_job,EvidenceScope,KalshiEvidence,evidence_page)
from services.research.inventory import ProviderFailure, inspect_pages, page_key
from services.research.normalize import Candidate, CandidateBatch, Evidence, Input
from services.research.queue import EvidenceConflict
from test_normalize import MemoryObjects
from test_kalshi import reply, Chunks

CANDIDATE = Candidate('KXBTC15M-TEST','KXBTC15M-EVENT','KXBTC15M','2026-10-25T12:00:00Z','yes',
    (Evidence('inventory-job','a'*64,'recent','inventory/page',0,'raw/ref','b'*64,100),))
BATCH = CandidateBatch('2026-10-25','generation',('KXBTC15M',),
    (Input('a'*64,'inventory-job','complete',1,1),), (CANDIDATE,),1)


def trade(scope,**patch):
    return {'trade_id':'trade-one','ticker':scope.ticker,
            'created_time':datetime.fromtimestamp(scope.start_ts+1,timezone.utc).isoformat(),
            'yes_price_dollars':'0.8800','no_price_dollars':'0.1200','count_fp':'1.00',
            'taker_outcome_side':'no','is_block_trade':False,**patch}


def candle(scope): return dict(end_period_ts=scope.end_ts,yes_bid={'close_dollars':'0.8800'},yes_ask={'close_dollars':'0.8900'})


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.archives = ArchiveStore(MemoryObjects())
        self.plan = build_scopes(BATCH,self.archives,lookback_seconds=3600)
    def scope(self,resource='trades',source='recent'):
        return next(s for s in self.plan.scopes if (s.resource,s.source)==(resource,source))
    def job(self,scope): return dict(parameters=scope.parameters())

    def test_plan_binds_every_candidate_both_resources_and_sources_to_immutable_membership(self):
        self.assertEqual(len(self.plan.scopes),4)
        self.assertEqual({(s.source,s.resource) for s in self.plan.scopes},
                         {('recent','candles'),('historical','candles'),('recent','trades'),('historical','trades')})
        for s in self.plan.scopes:
            self.assertEqual(scope_for_job(self.job(s),self.archives),s)
            self.assertEqual(s.end_ts-s.start_ts,3600)
        manifest = self.archives.read(self.plan.manifest_receipt())
        self.assertEqual(manifest['fingerprint'],BATCH.fingerprint)
        self.assertEqual(manifest['batch']['candidates'][0]['evidence'][0]['object_key'],'raw/ref')

    def test_day_lookback_is_windowed_and_trade_resource_selection_does_not_change_membership(self):
        plan = build_scopes(BATCH,self.archives,lookback_seconds=86400)
        self.assertEqual(len(plan.scopes),16)
        candles = [s for s in plan.scopes if (s.resource,s.source)==('candles','recent')]
        self.assertEqual(sum(s.end_ts-s.start_ts for s in candles),86400)
        self.assertEqual(candles[0].start_ts,candles[-1].end_ts-86400)
        only = build_scopes(BATCH,self.archives,lookback_seconds=3600,resources=('candles',))
        self.assertEqual(only.batch_fingerprint,self.plan.batch_fingerprint)
        self.assertEqual(len(only.scopes),2)
        self.assertEqual(only.manifest_key,self.plan.manifest_key)

    def test_incomplete_membership_or_invalid_horizon_is_rejected_and_ready_empty_is_preserved(self):
        with self.assertRaises(ValueError): build_scopes(replace(BATCH,inputs=(Input('x',None,'fetch',0,0),)),self.archives,lookback_seconds=3600)
        for seconds in (True,0,86401):
            with self.assertRaises(ValueError): build_scopes(BATCH,self.archives,lookback_seconds=seconds)
        empty = build_scopes(replace(BATCH,candidates=()),self.archives,lookback_seconds=3600)
        self.assertEqual(empty.scopes,())
        self.assertEqual(self.archives.read(empty.manifest_receipt())['batch']['candidates'],[])

    def test_manifest_mismatch_corruption_and_wrong_candidate_fail_before_provider_work(self):
        scope = self.scope()
        with self.assertRaises(EvidenceConflict): scope_for_job(self.job(replace(scope,candidate_key='c'*64)),self.archives)
        with self.assertRaises(EvidenceConflict): scope_for_job(self.job(replace(scope,result='no')),self.archives)
        self.archives.objects.data[scope.manifest_key] = b'corrupt'
        with self.assertRaises(ArchiveInvalid): scope_for_job(self.job(scope),self.archives)

    def test_path_identity_window_and_resource_guardrails(self):
        scope = self.scope()
        for patch in ({'ticker':'../orders'},{'ticker':'..'},{'resource':'orders'},
                      {'end_ts':scope.end_ts+1},{'start_ts':scope.end_ts-21601},{'result':''}):
            with self.assertRaises(ValueError): replace(scope,**patch)
        with self.assertRaises(ValueError): self.scope('candles').request('next')
        self.assertTrue(page_key(scope,0).startswith('evidence/'))

    def test_all_four_read_routes_and_original_price_fields(self):
        calls = []
        def handler(r):
            calls.append(r)
            scope = self.scope('candles' if r.url.path.endswith('candlesticks') else 'trades',
                               'historical' if r.url.path.startswith('/trade-api/v2/historical') else 'recent')
            payload = ({'ticker':scope.ticker,'candlesticks':[candle(scope)]} if scope.resource=='candles'
                       else {'trades':[trade(scope)],'cursor':''})
            return reply(payload=payload)
        with KalshiEvidence(transport=httpx.MockTransport(handler)) as provider:
            for scope in self.plan.scopes:
                response = provider.fetch(scope,'',10)
                self.assertEqual(response.availability,'available')
                self.assertEqual(evidence_page(scope,response.payload,'available')[1],'')
        self.assertEqual(len(calls),4)
        self.assertTrue(all(r.method=='GET' and r.url.host=='external-api.kalshi.com' for r in calls))
        self.assertTrue(all('authorization' not in r.headers for r in calls))
        self.assertEqual(self.scope().request('opaque+/=')[1]['cursor'],'opaque+/=')

    def test_404_is_explicit_unavailable_not_empty_and_error_body_is_not_read(self):
        stream = Chunks([b'private diagnostic'])
        with KalshiEvidence(transport=httpx.MockTransport(lambda _:reply(404,stream=stream))) as provider:
            response = provider.fetch(self.scope('candles'),'',10)
        self.assertEqual(response.availability,'unavailable')
        self.assertEqual(response.payload,{'http_status':404})
        self.assertEqual(stream.reads,0)
        self.assertTrue(stream.closed)
        self.assertEqual(evidence_page(self.scope('candles'),response.payload,'unavailable'),([],''))
        self.assertEqual(evidence_page(self.scope(),{'trades':[],'cursor':''},'available'),([],''))

    def test_trade_schema_units_market_and_timestamps_are_not_guessed(self):
        scope = self.scope()
        original = trade(scope)
        rows,cursor = evidence_page(scope,{'trades':[original],'cursor':'next'},'available')
        self.assertEqual(rows[0]['yes_price_dollars'],'0.8800')
        self.assertEqual(cursor,'next')
        for patch in ({'ticker':'wrong'},{'created_time':'2026-10-01T00:00:00Z'},
                      {'yes_price_dollars':88},{'yes_price_dollars':'88'},{'count_fp':'0'},{'is_block_trade':'false'}):
            with self.assertRaises(ProviderFailure): evidence_page(scope,{'trades':[{**original,**patch}],'cursor':''},'available')
        with self.assertRaises(ProviderFailure): evidence_page(scope,{'trades':[original,original],'cursor':''},'available')

    def test_candle_forms_null_quotes_and_incomplete_minute_coverage_stay_raw_evidence(self):
        scope = self.scope('candles')
        for quotes in ({'close':'0.8800'},{'close_dollars':'0.8800'},{'close_dollars':None}):
            row = {**candle(scope),'yes_bid':quotes}
            self.assertEqual(evidence_page(scope,{'ticker':scope.ticker,'candlesticks':[row]},'available')[0],[row])
        for patch in ({'end_period_ts':scope.end_ts+60},{'end_period_ts':True},{'yes_bid':{'close':88}}):
            with self.assertRaises(ProviderFailure): evidence_page(scope,{'ticker':scope.ticker,'candlesticks':[{**candle(scope),**patch}]},'available')
        with self.assertRaises(ProviderFailure): evidence_page(scope,{'ticker':'wrong','candlesticks':[]},'available')
