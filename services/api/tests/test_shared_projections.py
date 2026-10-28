"""Shared candle archives retain exact source selectors and legacy publication."""
from copy import deepcopy
from dataclasses import replace
import json
import os
import time
import unittest
from urllib.parse import urlsplit
from unittest.mock import Mock

from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.archive import ArchiveInvalid,ArchiveStore
from services.research.budget import ReadBudget
from services.research.evidence import build_scopes,EvidenceWorker
from services.research.inventory import ProviderPage,ProviderFailure,digest,page_key
from services.research.projections import archive_evidence,resolve_evidence
from services.research.queue import ResearchQueue,EvidenceConflict
from services.research.reports import prepare_report
from test_datasets import Fixture
from test_evidence import BATCH,CANDIDATE,candle
from test_normalize import MemoryObjects

URL=os.environ.get('POCKET_TEST_DATABASE_URL')


class CountingObjects(MemoryObjects):
    def __init__(self):super().__init__();self.puts=0;self.gets=0
    def put_if_absent(self,key,body,content_type):
        self.puts+=1;return super().put_if_absent(key,body,content_type)
    def get(self,key,max_bytes):return super().get(key,max_bytes)


def checkpoint(scope,items):
    return dict(scope=scope.key,sequence=0,cursor_in='',cursor_out='',items=items,availability='available')


def batch_response(archives,scopes,*,extra_bars=False):
    # Deliberately reverse market order; source selectors cannot assume sort order.
    args=dict(market_tickers=','.join(s.ticker for s in scopes),start_ts=min(s.start_ts for s in scopes)-60,
              end_ts=max(s.end_ts for s in scopes)+60,period_interval=1)
    entries=[]
    for scope in reversed(scopes):
        bars=[candle(scope)]
        if extra_bars:
            bars=[{**candle(scope),'end_period_ts':scope.start_ts-60},candle(scope),
                  {**candle(scope),'end_period_ts':scope.end_ts+60}]
        entries.append(dict(market_ticker=scope.ticker,candlesticks=bars))
    raw=dict(format='candle-batch-v1',request=args,response=dict(markets=entries))
    receipt=archives.upload('kalshi',raw)
    pages={s.key:ProviderPage(dict(ticker=s.ticker,candlesticks=[candle(s)],batch_receipt=receipt)) for s in scopes}
    return raw,receipt,pages


class SharedProjectionTests(unittest.TestCase):
    def setUp(self):
        self.objects=CountingObjects();self.archives=ArchiveStore(self.objects,cache_bytes=1024*1024)
        candidates=tuple(replace(CANDIDATE,ticker='KXBTC15M-SHARED-'+str(i),event_ticker='SHARED-E'+str(i)) for i in range(5))
        plan=build_scopes(replace(BATCH,candidates=candidates),self.archives,lookback_seconds=1020,resources=('candles',))
        self.scopes=[s for s in plan.scopes if s.source=='recent']

    def page(self,scope,response):
        receipt,cp=archive_evidence(scope,checkpoint(scope,len(response.payload['candlesticks'])),response,self.archives)
        return dict(page_key=page_key(scope,0),object_key=receipt['object_key'],receipt=receipt,checkpoint=cp)

    def test_one_verified_batch_upload_serves_all_market_pages_with_original_row_selectors(self):
        before=self.objects.puts,self.objects.gets
        raw,receipt,responses=batch_response(self.archives,self.scopes,extra_bars=True)
        self.assertEqual((self.objects.puts-before[0],self.objects.gets-before[1]),(1,1))
        after=self.objects.puts,self.objects.gets
        for ordinal,scope in enumerate(self.scopes):
            page=self.page(scope,responses[scope.key]);rows,cursor,selectors=resolve_evidence(scope,page,self.archives)
            self.assertEqual(page['receipt'],receipt);self.assertEqual(rows,[candle(scope)]);self.assertEqual(cursor,'')
            expected=dict(format='candle-batch-projection-v1',entry_index=len(self.scopes)-1-ordinal,row_index=1)
            self.assertEqual(selectors,[expected])
            self.assertEqual(page['checkpoint']['projection']['request_sha256'],digest(raw['request']))
        self.assertEqual((self.objects.puts,self.objects.gets),after)

    def test_restart_resolves_committed_shared_receipt_without_another_upload(self):
        _,_,responses=batch_response(self.archives,self.scopes)
        pages=[self.page(scope,responses[scope.key]) for scope in self.scopes]
        self.archives=ArchiveStore(self.objects,cache_bytes=1024*1024);before=self.objects.puts,self.objects.gets
        for scope,page in zip(self.scopes,pages):
            self.assertEqual(resolve_evidence(scope,page,self.archives)[0],[candle(scope)])
        self.assertEqual(self.objects.puts,before[0]);self.assertEqual(self.objects.gets-before[1],1)

    def test_checkpoint_and_cached_response_tampering_are_rejected(self):
        _,_,responses=batch_response(self.archives,self.scopes);scope=self.scopes[0]
        page=self.page(scope,responses[scope.key])
        for mutation in ('scope','count','entry','request','availability'):
            bad=deepcopy(page)
            if mutation=='scope':bad['checkpoint']['scope']='a'*64
            elif mutation=='count':bad['checkpoint']['items']=2
            elif mutation=='entry':bad['checkpoint']['projection']['entry_index']=0
            elif mutation=='request':bad['checkpoint']['projection']['request_sha256']='a'*64
            else:bad['checkpoint']['availability']='unavailable'
            with self.subTest(mutation=mutation),self.assertRaises((ValueError,ProviderFailure)):
                resolve_evidence(scope,bad,self.archives)
        bad=deepcopy(responses[scope.key]);bad.payload['candlesticks'][0]['yes_bid']['close_dollars']='0.70'
        with self.assertRaises((ValueError,ProviderFailure)):self.page(scope,bad)

    def test_corrupt_or_missing_shared_object_cannot_reconstruct_a_page(self):
        _,receipt,responses=batch_response(self.archives,self.scopes);scope=self.scopes[0]
        page=self.page(scope,responses[scope.key]);body=self.objects.data.pop(receipt['object_key'])
        self.archives=ArchiveStore(self.objects)
        with self.assertRaises((KeyError,ArchiveInvalid,EvidenceConflict)):resolve_evidence(scope,page,self.archives)
        self.objects.data[receipt['object_key']]=b'corrupt'
        with self.assertRaises(ArchiveInvalid):resolve_evidence(scope,page,self.archives)
        self.objects.data[receipt['object_key']]=body

    def test_hash_valid_batch_with_bad_request_or_foreign_or_truncated_member_is_rejected(self):
        raw,_,_=batch_response(self.archives,self.scopes);scope=self.scopes[0]
        for mutation in ('period','start','ticker','duplicate','truncated','foreign'):
            bad=deepcopy(raw)
            if mutation=='period':bad['request']['period_interval']=5
            elif mutation=='start':bad['request']['start_ts']=scope.start_ts+1
            elif mutation=='ticker':bad['request']['market_tickers']=','.join(s.ticker for s in self.scopes[1:])
            elif mutation=='duplicate':bad['response']['markets'].append(deepcopy(bad['response']['markets'][0]))
            elif mutation=='foreign':bad['response']['markets'][0]['market_ticker']='FOREIGN'
            else:bad['response']['adjusted_end_ts']=bad['request']['end_ts']-60
            receipt=self.archives.upload('kalshi',bad)
            response=ProviderPage(dict(ticker=scope.ticker,candlesticks=[candle(scope)],batch_receipt=receipt))
            with self.subTest(mutation=mutation),self.assertRaises((ValueError,ProviderFailure)):self.page(scope,response)

    def test_mixed_legacy_and_shared_dataset_keeps_full_report_and_source_provenance(self):
        fixture=Fixture()
        for selected in fixture.plan.scopes:
            if selected.resource!='candles':continue
            old_job,pages=next((j,p) for j,p in fixture.attempts if j['id']==selected.key)
            payload=fixture.archives.read(pages[0]['receipt'])['response']
            payload['candlesticks'][0]['end_period_ts']=selected.start_ts
            replacement=fixture.attempt(selected,payload,1,jid=selected.key)
            fixture.attempts=[replacement if j['id']==selected.key else (j,p) for j,p in fixture.attempts]
        before=fixture.prepare();old_payload=json.loads(before.payload_json)
        scope=next(s for s in fixture.plan.scopes if (s.source,s.resource)==('recent','candles'))
        old_job,old_pages=next((j,p) for j,p in fixture.attempts if j['id']==scope.key)
        original=fixture.archives.read(old_pages[0]['receipt'])['response']
        # Use the exact legacy quote fields; only storage representation changes.
        raw=dict(format='candle-batch-v1',request=dict(market_tickers=scope.ticker,start_ts=scope.start_ts,
            end_ts=scope.end_ts,period_interval=1),response=dict(markets=[dict(market_ticker=scope.ticker,candlesticks=original['candlesticks'])]))
        receipt=fixture.archives.upload('kalshi',raw)
        response=ProviderPage({**original,'batch_receipt':receipt})
        receipt,cp=archive_evidence(scope,old_pages[0]['checkpoint'],response,fixture.archives)
        new_page={**old_pages[0],'object_key':receipt['object_key'],'receipt':receipt,'checkpoint':cp}
        fixture.attempts=[(j,[new_page] if j['id']==scope.key else p) for j,p in fixture.attempts]
        after=fixture.prepare();new_payload=json.loads(after.payload_json)
        self.assertEqual(new_payload['summary'],old_payload['summary'])
        self.assertEqual([r['record'] for r in new_payload['records']],[r['record'] for r in old_payload['records']])
        provenance=[p for r in new_payload['records'] for p in r['provenance'] if p['job_id']==scope.key]
        self.assertEqual(len(provenance),1);self.assertEqual(provenance[0]['projection']['entry_index'],0)
        reports=[]
        for payload,prepared in ((old_payload,before),(new_payload,after)):
            report=prepare_report('btc',[dict(id=1,fingerprint=prepared.fingerprint,payload=payload)],latest_ids=[1])
            reports.append(json.loads(report.payload_json))
        for key in ('historical','latest','coverage','risk_coverage'):self.assertEqual(reports[0][key],reports[1][key])
        self.assertEqual(reports[0]['historical']['observation_count'],1)
        legacy_scope=next(s for s in fixture.plan.scopes if (s.source,s.resource)==('historical','candles'))
        legacy_page=next(p[0] for j,p in fixture.attempts if j['id']==legacy_scope.key)
        self.assertEqual(resolve_evidence(legacy_scope,legacy_page,fixture.archives)[2],[None])


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class SharedProjectionPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL);cls.db=PostgresStore(URL);cls.db.open()
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def setUp(self):
        with self.db.pool.connection() as c:
            c.execute('TRUNCATE research_refresh,research_job,research_dataset,research_result,research_artifact,research_read_budget CASCADE')
        self.objects=CountingObjects();self.archives=ArchiveStore(self.objects,cache_bytes=1024*1024)
        candidates=tuple(replace(CANDIDATE,ticker='KXBTC15M-PGSHARED-'+str(i),event_ticker='PGSHARED-E'+str(i)) for i in range(5))
        plan=build_scopes(replace(BATCH,candidates=candidates),self.archives,lookback_seconds=1020,resources=('candles',))
        self.scopes=[s for s in plan.scopes if s.source=='recent']
        self.queue=ResearchQueue(self.db.pool);self.budget=ReadBudget(self.db.pool);self.budget.configure(100,100)

    def test_five_fenced_pages_share_one_archive_and_survive_worker_reconstruction(self):
        before=self.objects.puts,self.objects.gets
        raw,receipt,responses=batch_response(self.archives,self.scopes,extra_bars=True)
        provider=Mock();provider.cached.side_effect=lambda scope,cursor:responses.get(scope.key)
        provider.fetch.side_effect=AssertionError('A cached verified batch must not fetch again')
        worker=EvidenceWorker(self.queue,self.archives,provider,self.budget,endpoint_cost=1)
        jobs=[self.queue.enqueue('btc',scope.parameters(),'shared/'+scope.key) for scope in self.scopes]
        for index,job in enumerate(jobs):
            claimed=self.queue.claim(job_id=job['id'])
            self.assertEqual(worker.step(claimed,deadline=time.monotonic()+30)['state'],'complete')
            if index==0:
                # Fresh worker object proves metadata/receipt compatibility while
                # another process-local cache can safely miss after a real restart.
                worker=EvidenceWorker(self.queue,self.archives,provider,self.budget,endpoint_cost=1)
        self.assertEqual((self.objects.puts-before[0],self.objects.gets-before[1]),(1,1))
        provider.fetch.assert_not_called()
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM raw_archive').fetchone()['n'],1)
            self.assertEqual(c.execute('SELECT count(*) AS n FROM collection_page').fetchone()['n'],5)
            self.assertEqual(c.execute("SELECT count(*) AS n FROM research_job WHERE status='succeeded'").fetchone()['n'],5)
        reopened=ArchiveStore(self.objects,cache_bytes=1024*1024)
        for scope,job in zip(self.scopes,jobs):
            pages=self.queue.page_evidence(job['id']);self.assertEqual(len(pages),1)
            self.assertEqual(pages[0]['object_key'],receipt['object_key'])
            rows,cursor,selectors=resolve_evidence(scope,pages[0],reopened)
            self.assertEqual(rows,[candle(scope)]);self.assertEqual(selectors[0]['row_index'],1)
