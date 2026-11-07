"""Verified evidence ingestion plus real-PG atomic immutable publication tests."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, replace
import json
import os
import unittest
from urllib.parse import urlsplit

import psycopg
from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.archive import ArchiveInvalid, ArchiveStore
from services.research.datasets import (prepare_dataset,DatasetStore,CoverageIncomplete)
from services.research.evidence import build_scopes
from services.research.inventory import Scope,digest,page_key
from services.research.normalize import normalize_inventory
from services.research.queue import EvidenceConflict
from test_normalize import MemoryObjects,MARKET,DAY,GENERATION
from test_evidence import trade

URL = os.environ.get('POCKET_TEST_DATABASE_URL')


class Fixture:
    def __init__(self,*,price='0.8800',empty=False):
        self.archives = ArchiveStore(MemoryObjects()); self.inventory = {}
        inv = []
        for source in ('recent','historical'):
            scope = Scope('KXBTC15M',source,DAY if source=='recent' else None,GENERATION)
            rows = [] if empty else [MARKET]
            attempt = self.attempt(scope,{'markets':rows,'cursor':''},len(rows),jid='inventory-'+source)
            self.inventory[attempt[0]['id']] = attempt; inv.append(attempt)
        self.batch = normalize_inventory(['KXBTC15M'],DAY,GENERATION,inv,self.archives)
        self.plan = build_scopes(self.batch,self.archives,lookback_seconds=60)
        self.attempts = []
        for scope in self.plan.scopes:
            if scope.resource=='candles':
                key = 'close_dollars' if scope.source=='recent' else 'close'
                payload = {'ticker':scope.ticker,'candlesticks':[{'end_period_ts':scope.end_ts,'yes_bid':{key:price}}]}
            else: payload = {'trades':[trade(scope)],'cursor':''}
            self.attempts.append(self.attempt(scope,payload,1,jid=scope.key))
    def attempt(self,scope,payload,count,*,jid,availability='available',status='succeeded',cursor=''):
        cp = dict(scope=scope.key,sequence=0,cursor_in='',cursor_out=cursor,items=count,availability=availability)
        receipt = self.archives.upload('kalshi',dict(scope=asdict(scope),checkpoint=cp,response=payload))
        page = dict(page_key=page_key(scope,0),object_key=receipt['object_key'],receipt=receipt,checkpoint=cp)
        return dict(id=jid,parameters=scope.parameters(),status=status),[page]
    def prepare(self,**kwargs):
        return prepare_dataset(self.plan,self.attempts,self.archives,self.inventory.__getitem__,**kwargs)


class ArchiveReadWaveTests(unittest.TestCase):
    def test_wave_bounds_decoded_bytes_unknown_inputs_and_shared_objects(self):
        from services.research.datasets import _evidence_wave
        def group(key,size=None):
            return (key,[(None,None,{'receipt':{'metadata':{} if size is None else {'decoded_bytes':size}}})])
        small=[group(str(i),1024) for i in range(10)]
        self.assertEqual(len(_evidence_wave(small,0,8)),8)
        self.assertEqual(len(_evidence_wave([group('a',6*1024*1024),group('b',6*1024*1024)],0,8)),1)
        self.assertEqual(len(_evidence_wave([group('a'),group('b',1024)],0,8)),1)
        self.assertEqual(len(_evidence_wave([group('a',1024),group('a',1024)],0,8)),1)

    def test_parallel_archive_reads_preserve_exact_dataset_and_all_provenance(self):
        import services.research.datasets as model
        from threading import Barrier
        from unittest.mock import patch
        f=Fixture();serial=f.prepare(archive_parallelism=1)
        barrier=Barrier(len(f.attempts));original=model._resolve_evidence_group
        def overlapping(pages,archives):
            barrier.wait(timeout=5)
            return original(pages,archives)
        with patch.object(model,'_resolve_evidence_group',side_effect=overlapping):
            parallel=f.prepare(archive_parallelism=8)
        self.assertEqual(serial,parallel)


class DatasetTests(unittest.TestCase):
    def test_merge_both_sources_keeps_provenance_and_full_cohort_separate_from_trade_counts(self):
        f = Fixture(); prepared = f.prepare()
        payload,summary = json.loads(prepared.payload_json),json.loads(prepared.summary_json)
        self.assertEqual((summary['candidate_count'],summary['candle_records'],summary['trade_records']),(1,1,1))
        self.assertEqual(summary['raw_rows_scanned'],4)
        self.assertTrue(all(len(r['provenance'])==2 for r in payload['records']))
        candle = next(r for r in payload['records'] if r['resource']=='candles')
        self.assertEqual(candle['record']['yes_bid']['close'],'0.88')
        self.assertEqual(len(payload['artifacts']),7)
        self.assertNotIn('roi',summary)
        self.assertEqual(prepared.fingerprint,digest(payload))
        f.attempts.reverse()
        self.assertEqual(f.prepare().fingerprint,prepared.fingerprint)

    def test_partial_or_missing_jobs_block_entire_dataset(self):
        f = Fixture(); f.attempts.pop()
        with self.assertRaises(CoverageIncomplete): f.prepare()
        f = Fixture(); f.attempts[0][0]['status']='failed'
        with self.assertRaises(CoverageIncomplete): f.prepare()
        f = Fixture(); job,pages = f.attempts[0]
        pages[0]['checkpoint']['cursor_out']='unfinished'
        with self.assertRaises(CoverageIncomplete): f.prepare()

    def test_ambiguous_successful_membership_is_not_silently_merged(self):
        f = Fixture(); job,pages = deepcopy(f.attempts[0]);job['id']='second-complete'
        f.attempts.append((job,pages))
        with self.assertRaises(EvidenceConflict): f.prepare()

    def test_conflicting_quotes_or_trade_records_fail_instead_of_picking_a_source(self):
        for resource in ('candles','trades'):
            f = Fixture()
            scope = next(s for s in f.plan.scopes if s.resource==resource and s.source=='historical')
            payload = ({'ticker':scope.ticker,'candlesticks':[{'end_period_ts':scope.end_ts,'yes_bid':{'close':'0.70'}}]}
                       if resource=='candles' else {'trades':[{**trade(scope),'count_fp':'2.00'}],'cursor':''})
            f.attempts = [(j,p) for j,p in f.attempts if j['id']!=scope.key]
            f.attempts.append(f.attempt(scope,payload,1,jid=scope.key))
            with self.assertRaises(EvidenceConflict): f.prepare()

    def test_transitive_inventory_and_evidence_corruption_are_rechecked(self):
        for kind in ('inventory','evidence'):
            f = Fixture()
            attempt = next(iter(f.inventory.values())) if kind=='inventory' else f.attempts[0]
            key = attempt[1][0]['object_key']
            f.archives.objects.data[key]=b'corrupt-after-collection'
            with self.assertRaises(ArchiveInvalid): f.prepare()

    def test_hash_valid_wrong_envelope_or_altered_plan_is_rejected(self):
        f = Fixture(); job,pages = f.attempts[0]
        cp = pages[0]['checkpoint']
        receipt = f.archives.upload('kalshi',dict(scope={},checkpoint=cp,response={}))
        pages[0].update(object_key=receipt['object_key'],receipt=receipt)
        with self.assertRaises(EvidenceConflict): f.prepare()
        f = Fixture(); f.plan = replace(f.plan,scopes=f.plan.scopes[:-1])
        with self.assertRaises(EvidenceConflict): f.prepare()

    def test_empty_and_unavailable_sources_are_explicit_not_zero_fill_estimates(self):
        f = Fixture()
        for scope in f.plan.scopes:
            if scope.resource=='trades':
                f.attempts = [(j,p) for j,p in f.attempts if j['id']!=scope.key]
                f.attempts.append(f.attempt(scope,{'http_status':404},0,jid=scope.key,availability='unavailable'))
        summary = json.loads(f.prepare().summary_json)
        self.assertEqual((summary['candidate_count'],summary['candle_records'],summary['trade_records']),(1,1,0))
        self.assertEqual(summary['scope_states']['unavailable'],2)
        self.assertEqual(summary['candidates_without_trades'],1)
        self.assertEqual(json.loads(Fixture(empty=True).prepare().summary_json)['candidate_count'],0)

    def test_limits_fail_without_publishing_a_subset(self):
        with self.assertRaises(ValueError): Fixture().prepare(max_rows=3)


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class DatasetPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test': raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL); cls.store=PostgresStore(URL);cls.store.open();cls.datasets=DatasetStore(cls.store.pool)
    @classmethod
    def tearDownClass(cls): cls.store.close()
    def setUp(self):
        with self.store.pool.connection() as c:
            c.execute('TRUNCATE research_dataset_artifact,research_summary,research_dataset,research_artifact CASCADE')
        self.prepared=Fixture().prepare()
    def counts(self):
        with self.store.pool.connection() as c:
            return tuple(c.execute('SELECT count(*) AS n FROM '+t).fetchone()['n'] for t in
                ('research_dataset','research_summary','research_artifact','research_dataset_artifact'))

    def test_publish_is_idempotent_and_history_reads_precomputed_summary(self):
        first=self.datasets.publish('btc-day',self.prepared)
        self.assertEqual(self.datasets.publish('btc-day',self.prepared),first)
        history=self.datasets.history('btc-day')
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['summary']['candidate_count'],1)
        self.assertNotIn('payload',history[0])
        self.assertEqual(self.counts(),(1,1,7,7))

    def test_refresh_preserves_old_version_and_retry_cannot_move_latest_backwards(self):
        old=self.datasets.publish('btc-day',self.prepared)
        new=self.datasets.publish('btc-day',Fixture(price='0.8700').prepare())
        self.assertGreater(new,old)
        self.assertEqual(self.datasets.publish('btc-day',self.prepared),old)
        self.assertEqual([r['id'] for r in self.datasets.history('btc-day',limit=1)],[new])
        self.assertEqual([r['id'] for r in self.datasets.history('btc-day',before=new)],[old])
        self.datasets.publish('other-stream',self.prepared)
        self.assertEqual(len(self.datasets.history('btc-day')),2)
        self.assertEqual(len(self.datasets.history('other-stream')),1)

    def test_concurrent_publish_creates_one_version_with_all_references(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            ids=list(executor.map(lambda _:self.datasets.publish('btc-day',self.prepared),range(8)))
        self.assertEqual(len(set(ids)),1)
        self.assertEqual(self.counts(),(1,1,7,7))

    def test_history_tables_reject_update_and_delete(self):
        self.datasets.publish('btc-day',self.prepared)
        for table in ('research_dataset','research_summary','research_artifact','research_dataset_artifact'):
            for sql in (f'DELETE FROM {table}',f'UPDATE {table} SET '+('object_key=object_key' if table in ('research_artifact','research_dataset_artifact') else 'dataset_id=dataset_id' if table=='research_summary' else 'stream_key=stream_key')):
                with self.assertRaises(psycopg.Error):
                    with self.store.pool.connection() as c: c.execute(sql)
        self.assertEqual(self.counts(),(1,1,7,7))

    def test_failure_rolls_back_artifact_registry_and_version_together(self):
        payload=json.loads(self.prepared.payload_json);payload['day']='not-a-date'
        broken=replace(self.prepared,payload_json=json.dumps(payload),fingerprint=digest(payload))
        with self.assertRaises(psycopg.Error): self.datasets.publish('btc-day',broken)
        self.assertEqual(self.counts(),(0,0,0,0))
        self.assertEqual(self.datasets.history('btc-day'),[])

    def test_prepared_reference_or_summary_tampering_fails_before_write(self):
        for patch in (dict(artifacts_json='[]'),dict(summary_json='{}')):
            with self.assertRaises(EvidenceConflict): self.datasets.publish('btc-day',replace(self.prepared,**patch))
        self.assertEqual(self.counts(),(0,0,0,0))

    def test_registry_conflict_rolls_back_new_references_without_overwriting_history(self):
        artifacts=json.loads(self.prepared.artifacts_json)
        poisoned={**artifacts[-1],'sha256':'f'*64}
        with self.store.pool.connection() as c:
            c.execute('INSERT INTO research_artifact(object_key,sha256,provider,content_type,byte_length) VALUES(%s,%s,%s,%s,%s)',
                tuple(poisoned[k] for k in ('object_key','sha256','provider','content_type','byte_length')))
        with self.assertRaises(EvidenceConflict): self.datasets.publish('btc-day',self.prepared)
        self.assertEqual(self.counts(),(0,0,1,0))


class VerifiedNormalizationCacheTests(unittest.TestCase):
    def test_repeated_preparation_reuses_proof_but_changed_membership_revalidates(self):
        import services.research.datasets as model
        from unittest.mock import patch
        f=Fixture()
        with patch.object(model,'normalize_inventory',wraps=model.normalize_inventory) as rebuild:
            first=f.prepare();second=f.prepare()
            self.assertEqual(first,second);self.assertEqual(rebuild.call_count,1)
            job,pages=next(iter(f.inventory.values()))
            job['status']='failed'
            with self.assertRaises(EvidenceConflict):f.prepare()
            self.assertEqual(rebuild.call_count,2)
