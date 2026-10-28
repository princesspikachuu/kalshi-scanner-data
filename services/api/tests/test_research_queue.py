"""Queue crash/retry/idempotency tests against an explicit disposable Postgres DB."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.queue import ResearchQueue, LeaseLost, EvidenceConflict, bounded_json, lease_seconds

URL = os.environ.get('POCKET_TEST_DATABASE_URL')


class QueueValidationTests(unittest.TestCase):
    def test_unbounded_or_non_json_payloads_are_rejected(self):
        for value in ([], {'v': float('nan')}, {'v': 'x' * 17000}):
            with self.assertRaises(ValueError): bounded_json(value)
        for value in (True, 0, 9, 601, 20.5):
            with self.assertRaises(ValueError): lease_seconds(value)


@unittest.skipUnless(URL, 'Requires a disposable pocket_test PostgreSQL database')
class QueuePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path != '/pocket_test':
            raise RuntimeError('Integration tests require the disposable pocket_test database')
        migrate(URL)
        cls.store = PostgresStore(URL)
        cls.store.open()
        cls.queue = ResearchQueue(cls.store.pool)

    @classmethod
    def tearDownClass(cls): cls.store.close()

    def setUp(self):
        with self.store.pool.connection() as c:
            c.execute('TRUNCATE collection_page,raw_archive,research_job CASCADE')

    def job(self, key='test', max_attempts=5):
        return self.queue.enqueue('sports', {'start': '2026-01-01'}, key, max_attempts)

    def expire(self, job):
        with self.store.pool.connection() as c:
            c.execute("UPDATE research_job SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job['id'],))

    def row(self, job):
        with self.store.pool.connection() as c:
            return c.execute('SELECT * FROM research_job WHERE id=%s', (job['id'],)).fetchone()

    def archive(self, key='raw/test.json.gz', digest='a' * 64):
        return {'object_key': key, 'sha256': digest, 'provider': 'kalshi', 'byte_length': 123,
                'content_type': 'application/gzip'}

    def test_concurrent_enqueue_returns_one_job_and_conflicts_fail(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            jobs = list(executor.map(lambda _: self.job(), range(8)))
        self.assertEqual(len({j['id'] for j in jobs}), 1)
        with self.assertRaises(EvidenceConflict):
            self.queue.enqueue('weather', {'start': '2026-01-01'}, 'test')
        with self.assertRaises(EvidenceConflict): self.job(max_attempts=2)

    def test_concurrent_workers_claim_each_job_once(self):
        expected = {self.job(str(i))['id'] for i in range(12)}
        with ThreadPoolExecutor(max_workers=8) as executor:
            claimed = list(executor.map(lambda _: self.queue.claim(), range(20)))
        jobs = [j for j in claimed if j]
        self.assertEqual(len(jobs), 12)
        self.assertEqual({j['id'] for j in jobs}, expected)
        self.assertTrue(all(j['attempts'] == 1 for j in jobs))
        self.assertEqual(len({j['lease_token'] for j in jobs}), 12)

    def test_crash_reclaims_with_new_token_and_rejects_old_worker(self):
        self.job()
        old = self.queue.claim()
        self.expire(old)
        new = self.queue.claim()
        self.assertEqual(new['id'], old['id'])
        self.assertEqual(new['attempts'], 2)
        self.assertNotEqual(old['lease_token'], new['lease_token'])
        for operation in (
            lambda: self.queue.heartbeat(old['id'], old['lease_token']),
            lambda: self.queue.finish(old['id'], old['lease_token']),
            lambda: self.queue.fail(old['id'], old['lease_token'], 'network_error'),
            lambda: self.queue.checkpoint(old['id'], old['lease_token'], 'page', self.archive(), {}),
        ):
            with self.assertRaises(LeaseLost): operation()
        self.queue.heartbeat(new['id'], new['lease_token'])
        self.queue.finish(new['id'], new['lease_token'])
        self.assertEqual(self.row(new)['status'], 'succeeded')
        self.assertIsNone(self.queue.claim())

    def test_expired_worker_cannot_write_even_before_reclaim(self):
        self.job()
        job = self.queue.claim()
        self.expire(job)
        with self.assertRaises(LeaseLost): self.queue.heartbeat(job['id'], job['lease_token'])
        with self.assertRaises(LeaseLost): self.queue.finish(job['id'], job['lease_token'])

    def test_exhausted_crashes_become_terminal(self):
        self.job(max_attempts=1)
        job = self.queue.claim()
        self.expire(job)
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.row(job)['error_code'], 'attempts_exhausted')
        self.assertEqual(self.row(job)['status'], 'failed')
        self.assertIsNone(self.row(job)['lease_token'])

    def test_delayed_retry_then_final_failure(self):
        self.job(max_attempts=2)
        job = self.queue.claim()
        self.queue.fail(job['id'], job['lease_token'], 'provider_timeout', delay_seconds=3600)
        self.assertIsNone(self.queue.claim())
        with self.store.pool.connection() as c:
            c.execute("UPDATE research_job SET available_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job['id'],))
        job = self.queue.claim()
        self.queue.fail(job['id'], job['lease_token'], 'provider_timeout')
        self.assertEqual(self.row(job)['status'], 'failed')
        self.assertIsNone(self.queue.claim())

    def test_checkpoints_survive_retry_and_duplicate_pages_do_not_inflate_progress(self):
        self.job()
        job = self.queue.claim()
        args = (job['id'], job['lease_token'], 'series/one/page/1', self.archive(), {'next_cursor': 'opaque-page-2'})
        self.queue.checkpoint(*args)
        self.queue.checkpoint(*args)
        self.assertEqual(self.row(job)['progress'], {'completed_pages': 1})
        self.expire(job)
        retry = self.queue.claim()
        pages = self.queue.pages(retry['id'])
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]['checkpoint'], {'next_cursor': 'opaque-page-2'})
        self.assertEqual(retry['progress'], {'completed_pages': 1})

    def test_page_and_archive_conflicts_rollback_all_writes(self):
        self.job()
        job = self.queue.claim()
        self.queue.checkpoint(job['id'], job['lease_token'], 'page1', self.archive(), {'cursor': 1})
        with self.assertRaises(EvidenceConflict):
            self.queue.checkpoint(job['id'], job['lease_token'], 'page2', self.archive(digest='b' * 64), {})
        with self.assertRaises(EvidenceConflict):
            self.queue.checkpoint(job['id'], job['lease_token'], 'page1', self.archive('raw/another'), {})
        with self.assertRaises(EvidenceConflict):
            self.queue.checkpoint(job['id'], job['lease_token'], 'page1', self.archive(), {'cursor': 2})
        with self.store.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM raw_archive').fetchone()['n'], 1)
            self.assertEqual(c.execute('SELECT count(*) AS n FROM collection_page').fetchone()['n'], 1)
        self.assertEqual(self.row(job)['progress'], {'completed_pages': 1})

    def test_cancel_fences_worker_and_preserves_pages(self):
        job = self.job()
        self.assertTrue(self.queue.cancel(job['id']))
        self.assertIsNone(self.queue.claim())
        self.job('second')
        job = self.queue.claim()
        self.queue.checkpoint(job['id'], job['lease_token'], 'page', self.archive(), {})
        self.assertTrue(self.queue.cancel(job['id']))
        self.assertFalse(self.queue.cancel(job['id']))
        self.assertEqual(len(self.queue.pages(job['id'])), 1)
        with self.assertRaises(LeaseLost): self.queue.finish(job['id'], job['lease_token'])

    def test_success_is_terminal_and_does_not_advance_global_coverage(self):
        self.job()
        job = self.queue.claim()
        self.queue.finish(job['id'], job['lease_token'])
        self.assertFalse(self.queue.cancel(job['id']))
        with self.store.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM ingestion_cursor').fetchone()['n'], 0)
        with self.assertRaises(LeaseLost): self.queue.finish(job['id'], job['lease_token'])


    def test_grouped_cached_checkpoint_is_atomic_and_fences_cancelled_member(self):
        jobs=[self.job('bulk-'+str(i)) for i in range(3)]
        claimed=self.queue.claim_many([j['id'] for j in jobs])
        self.assertEqual(len({j['lease_token'] for j in claimed}),3)
        def entry(j):
            return dict(job=j,page_key='one',receipt=self.archive(),checkpoint=dict(sequence=0,cursor_in='',cursor_out='',availability='available',items=0,projection={'format':'candle-batch-projection-v1'}))
        entries=[entry(j) for j in claimed]
        self.queue.cancel(claimed[0]['id'])
        with self.assertRaises(LeaseLost):self.queue.complete_cached(entries)
        self.assertTrue(all(not self.queue.pages(j['id']) for j in claimed))
        self.queue.complete_cached(entries[1:])
        self.assertTrue(all(self.row(j)['status']=='succeeded' for j in claimed[1:]))
        self.assertTrue(all(len(self.queue.pages(j['id']))==1 for j in claimed[1:]))
