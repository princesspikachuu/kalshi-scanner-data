"""Lossless scope encoding, evidence reconstruction and fenced metadata updates."""
import json,os,unittest
from dataclasses import asdict
from unittest.mock import patch
from urllib.parse import urlsplit
from services.research.scope_storage import encode_scope,decode_scope
from services.research.evidence import scope_for_job
from services.research.storage_compaction import ScopeCompaction,KEY
from services.research.queue import ResearchQueue
from services.api.manage import migrate
from services.api.store import PostgresStore
from test_datasets import Fixture

class ScopeStorage(unittest.TestCase):
    def test_compact_manifest_restores_exact_scope_identity_and_complete_dataset(self):
        fixture=Fixture();before=fixture.prepare()
        saved=[]
        for job,pages in fixture.attempts:
            original=job['parameters']['scope'];compact=encode_scope(original)
            self.assertEqual(decode_scope(compact),original)
            self.assertLess(len(json.dumps(compact)),len(json.dumps(original)))
            updated=dict(job,parameters=dict(job['parameters'],scope=compact))
            self.assertEqual(asdict(scope_for_job(updated,fixture.archives)),original)
            saved.append((updated,pages))
        fixture.attempts=saved
        self.assertEqual(fixture.prepare(),before)
    def test_compact_writes_keep_sql_routing_and_reject_ambiguous_metadata(self):
        scope=Fixture().plan.scopes[0]
        with patch('services.research.scope_storage._WRITE_COMPACT',True):stored=scope.parameters()['scope']
        for field in ('resource','source','series','ticker','start_ts','end_ts'):self.assertEqual(stored[field],getattr(scope,field))
        with self.assertRaises(ValueError):decode_scope(dict(stored,manifest_bytes=1))
        with self.assertRaises(ValueError):decode_scope(dict(stored,manifest_v1=['bad',1]))
    def test_rollout_grace_period_does_not_change_metadata_or_writes(self):
        pool=__import__('unittest.mock',fromlist=['MagicMock']).MagicMock()
        with patch('services.research.scope_storage._WRITE_COMPACT',False):
            job=ScopeCompaction(pool,clock=lambda:0);job.tick()
            pool.connection.assert_not_called()
            import services.research.scope_storage as module
            self.assertFalse(module._WRITE_COMPACT)

URL=os.environ.get('POCKET_TEST_DATABASE_URL')
@unittest.skipUnless(URL,'Disposable PostgreSQL is required')
class StoragePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Use disposable pocket_test only')
        migrate(URL);cls.store=PostgresStore(URL);cls.store.open()
    @classmethod
    def tearDownClass(cls):cls.store.close()
    def setUp(self):
        with self.store.pool.connection() as c:c.execute('TRUNCATE research_job CASCADE')
    def test_completed_records_compact_resume_and_preserve_queued_work_and_identity(self):
        fixture=Fixture();scope=fixture.plan.scopes[0];queue=ResearchQueue(self.store.pool)
        with patch('services.research.scope_storage._WRITE_COMPACT',False):parameters=scope.parameters()
        completed=queue.enqueue('btc',parameters,'storage-completed')
        pending=queue.enqueue('btc',parameters,'storage-pending')
        with self.store.pool.connection() as c:
            c.execute("UPDATE research_job SET status='succeeded',progress='{}' WHERE id=%s",(completed['id'],))
        compactor=ScopeCompaction(self.store.pool);compactor.step(500)
        after=queue.get(completed['id']);self.assertEqual(decode_scope(after['parameters']['scope']),parameters['scope'])
        self.assertEqual(after['progress'],{});self.assertEqual(after['status'],'succeeded')
        self.assertEqual(queue.get(pending['id'])['parameters'],parameters)
        self.assertEqual(scope_for_job(after,fixture.archives).key,scope.key)
        self.assertEqual(queue.enqueue('btc',parameters,'storage-completed')['id'],completed['id'])
        with self.store.pool.connection() as c:state=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(KEY,)).fetchone()['progress']
        self.assertEqual(state['rows'],1);self.assertGreater(state['logical_bytes_saved'],0)
        ScopeCompaction(self.store.pool).step(600)
        with self.store.pool.connection() as c:state=c.execute('SELECT progress FROM research_job WHERE idempotency_key=%s',(KEY,)).fetchone()['progress']
        self.assertEqual(state['rows'],1);self.assertTrue(state['complete'])
