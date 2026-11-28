from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timezone
from threading import Barrier,Lock
import time
import unittest
from unittest.mock import patch

from services.research.archive import ArchiveStore,ArchiveInvalid
from services.research.availability import eligible_series
from services.research.cache import ByteCache
from services.research.normalize import normalize_inventory,batch_from_dict
from services.research.evidence import build_scopes
from services.research.datasets import prepare_dataset
from services.research.queue import EvidenceConflict
from services.research.projections import archive_evidence
from services.research.inventory import Scope,page_key
from services.research.evidence import build_scopes
from test_datasets import Fixture
from test_evidence import trade
from test_shared_projections import batch_response,checkpoint
from test_archives import MemoryObjects
import test_normalize as norm
from test_normalize import RECENT,HISTORY,MARKET,DAY,GENERATION

class CollectionSpeedTests(unittest.TestCase):
    def test_bounded_archive_reads_overlap_and_keep_exact_dataset(self):
        fixture=Fixture();objects=fixture.archives.objects
        fixture.archives=ArchiveStore(objects)
        baseline=fixture.prepare(archive_parallelism=1)
        evidence_keys={page['object_key'] for _,pages in fixture.attempts for page in pages}
        original_get=objects.get;gate=Barrier(2,timeout=3);lock=Lock();active=peak=0;first=[]
        def get(key,max_bytes):
            nonlocal active,peak
            if key not in evidence_keys:return original_get(key,max_bytes)
            with lock:
                active+=1;peak=max(peak,active)
                if len(first)<2:first.append(key);wait=len(first)<=2
                else:wait=False
            if wait:gate.wait()
            time.sleep(.005)
            try:return original_get(key,max_bytes)
            finally:
                with lock:active-=1
        fixture.archives=ArchiveStore(objects)
        with patch.object(objects,'get',side_effect=get):
            parallel=fixture.prepare(archive_parallelism=2)
        self.assertGreaterEqual(peak,2)
        self.assertEqual((parallel.fingerprint,parallel.payload_json),(baseline.fingerprint,baseline.payload_json))
        with self.assertRaises(ValueError):fixture.prepare(archive_parallelism=9)

    def test_shared_batch_pages_are_read_together_without_changing_dataset(self):
        import services.research.datasets as datasets
        fixture=Fixture();objects=fixture.archives.objects
        markets=[{**MARKET,'ticker':f'KXBTC15M-LOCAL-{i}',
                  'event_ticker':f'LOCAL-E-{i}'} for i in range(12)]
        fixture.inventory={}
        for source in ('recent','historical'):
            scope=Scope('KXBTC15M',source,DAY if source=='recent' else None,GENERATION)
            attempt=fixture.attempt(scope,{'markets':markets,'cursor':''},len(markets),jid='inventory-'+source)
            fixture.inventory[attempt[0]['id']]=attempt
        fixture.batch=normalize_inventory(['KXBTC15M'],DAY,GENERATION,list(fixture.inventory.values()),fixture.archives)
        fixture.plan=build_scopes(fixture.batch,fixture.archives,lookback_seconds=60)
        recent=[s for s in fixture.plan.scopes if (s.resource,s.source)==('candles','recent')]
        _,receipt,responses=batch_response(fixture.archives,recent)
        fixture.attempts=[]
        for scope in fixture.plan.scopes:
            if (scope.resource,scope.source)==('candles','recent'):
                response=responses[scope.key]
                shared,cp=archive_evidence(scope,checkpoint(scope,1),response,fixture.archives)
                self.assertEqual(shared,receipt)
                page=dict(page_key=page_key(scope,0),object_key=shared['object_key'],receipt=shared,checkpoint=cp)
                fixture.attempts.append((dict(id=scope.key,parameters=scope.parameters(),status='succeeded'),[page]))
            elif scope.resource=='candles':
                payload=dict(ticker=scope.ticker,candlesticks=[dict(end_period_ts=scope.end_ts,yes_bid={'close':'0.8800'})])
                fixture.attempts.append(fixture.attempt(scope,payload,1,jid=scope.key))
            else:fixture.attempts.append(fixture.attempt(scope,dict(trades=[trade(scope)],cursor=''),1,jid=scope.key))
        # A cache holding the batch but not all the other objects exposes the
        # repeated R2 GETs caused by hash-ordered, interleaved scopes.
        capacity=max(p[0]['receipt']['byte_length'] for _,p in fixture.attempts)
        original=lambda selected:[(s,j,p) for s,j,pages in selected for p in sorted(pages,key=lambda p:p['page_key'])]
        fixture.archives=ArchiveStore(objects,cache_bytes=capacity)
        fixture.archives.batch_indexes=ByteCache(0)
        before=objects.gets
        with patch.object(datasets,'_ordered_evidence_pages',side_effect=original):
            old=fixture.prepare()
        old_gets=objects.gets-before
        fixture.archives=ArchiveStore(objects,cache_bytes=capacity)
        fixture.archives.batch_indexes=ByteCache(0)
        before=objects.gets
        grouped=fixture.prepare()
        grouped_gets=objects.gets-before
        self.assertEqual((grouped.fingerprint,grouped.payload_json),(old.fingerprint,old.payload_json))
        self.assertLess(grouped_gets,old_gets)

    def test_verified_prelaunch_proofs_skip_only_certified_series_and_preserve_boundary(self):
        utc=timezone.utc
        included,proof=eligible_series(['KXTEMPNYCH','KXTEMPNYCHS','KXTEMPLAH'],datetime(2025,12,22,tzinfo=utc))
        self.assertEqual(included,['KXTEMPLAH']);self.assertEqual(len(proof),2)
        included,_=eligible_series(['KXTEMPNYCH'],datetime(2026,3,5,0,1,tzinfo=utc))
        self.assertEqual(included,['KXTEMPNYCH'])
        archives=ArchiveStore(MemoryObjects(),cache_bytes=100000)
        window=('2025-12-01T00:00:00+00:00','2025-12-02T00:00:00+00:00')
        batch=normalize_inventory(['KXTEMPNYCH'], '2025-12-01','proof',[],archives,window=window,prelaunch=True)
        self.assertTrue(batch.ready);self.assertEqual(batch.inputs,());self.assertEqual(batch.candidates,())
        plan=build_scopes(batch,archives,lookback_seconds=1020)
        prepared=prepare_dataset(plan,[],archives,lambda _:self.fail('No fake inventory jobs required'))
        self.assertEqual(batch,batch_from_dict(asdict(batch)));self.assertIn('certification_sha256',prepared.payload_json)
        unknown=normalize_inventory(['KXTEMPLAH'],'2025-12-01','unknown',[],archives,window=window,prelaunch=True)
        self.assertFalse(unknown.ready)
        # Forged proof cannot become a valid prepared publication.
        raw=asdict(batch);raw['exclusions'][0]['not_before']='2027-01-01T00:00:00Z'
        forged=batch_from_dict(raw);plan=build_scopes(forged,archives,lookback_seconds=1020)
        with self.assertRaises(EvidenceConflict):prepare_dataset(plan,[],archives,lambda _:None)

    def test_bounded_caches_preserve_fingerprints_provenance_and_mutation_isolation(self):
        fixture=norm.NormalizeTests();fixture.setUp()
        fixture.archives=ArchiveStore(MemoryObjects(),cache_bytes=1000000)
        attempts=[fixture.attempt(RECENT,[MARKET]),fixture.attempt(HISTORY,[MARKET])]
        archives=fixture.archives
        before=normalize_inventory(['KXBTC15M'],DAY,GENERATION,attempts,archives)
        gets=archives.objects.gets
        with patch.object(archives,'read',side_effect=AssertionError('Verified inventory should be reused')):
            after=normalize_inventory(['KXBTC15M'],DAY,GENERATION,deepcopy(attempts),archives)
            self.assertEqual(before,after)
            # Drop only whole-batch memo: compact verified page projections still
            # avoid reading/decompressing full raw pages again.
            archives.normalized_cache=ByteCache(1000000)
            self.assertEqual(before,normalize_inventory(['KXBTC15M'],DAY,GENERATION,attempts,archives))
        self.assertEqual(gets,archives.objects.gets)
        changed=deepcopy(attempts);changed[0][1][0]['checkpoint']['items']=2
        with self.assertRaises(EvidenceConflict):normalize_inventory(['KXBTC15M'],DAY,GENERATION,changed,archives)
        receipt=attempts[0][1][0]['receipt'];value=archives.read(receipt);value['response']['markets'].clear()
        self.assertEqual(len(archives.read(receipt)['response']['markets']),1)
        with self.assertRaises(ArchiveInvalid):archives.read({**receipt,'byte_length':1})
        new=ArchiveStore(archives.objects,cache_bytes=1000000)
        self.assertEqual(before,normalize_inventory(['KXBTC15M'],DAY,GENERATION,attempts,new))

    def test_lru_bytes_and_entry_budget(self):
        cache=ByteCache(5);cache.put('one',b'123');cache.put('two',b'45');self.assertEqual(cache.size,5)
        cache.get('one');cache.put('three',b'67');self.assertIsNone(cache.get('two'));self.assertLessEqual(cache.size,5)
        cache.put('huge',b'123456');self.assertIsNone(cache.get('huge'))
