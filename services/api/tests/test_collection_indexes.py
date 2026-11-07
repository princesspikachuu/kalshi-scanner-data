"""Operator index syntax and actual queue selection on disposable PostgreSQL."""
import os
from pathlib import Path
from urllib.parse import urlsplit
import unittest
import psycopg
from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.queue import ResearchQueue

URL=os.environ.get('POCKET_TEST_DATABASE_URL')


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class CollectionIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL)
        source=(Path(__file__).resolve().parents[3]/'infra/collection-query-indexes.sql').read_text()
        with psycopg.connect(URL,autocommit=True) as c:
            for statement in source.split(';'):
                if statement.strip():c.execute(statement,prepare=False)
        cls.db=PostgresStore(URL);cls.db.open()
    @classmethod
    def tearDownClass(cls):cls.db.close()

    def test_report_claim_uses_collector_index_among_unrelated_ready_jobs(self):
        with self.db.pool.connection() as c:
            c.execute('TRUNCATE research_job CASCADE')
            c.execute("""INSERT INTO research_job(id,asset,parameters,idempotency_key)
                SELECT gen_random_uuid(),'btc','{"collector":"evidence-v1"}'::jsonb,'index-noise/'||i
                FROM generate_series(1,2000) AS t(i)""")
            c.execute('ANALYZE research_job')
        queue=ResearchQueue(self.db.pool)
        target=queue.enqueue('btc',{'collector':'campaign-preview-v1'},'index-report')
        with self.db.pool.connection() as c:
            plan=c.execute("""EXPLAIN(FORMAT JSON) SELECT id FROM research_job
                WHERE parameters->>'collector'='campaign-preview-v1' AND status='queued'
                    AND available_at<=clock_timestamp() AND attempts<max_attempts
                ORDER BY available_at,created_at,id LIMIT 1""").fetchone()['QUERY PLAN']
            valid=c.execute("""SELECT bool_and(indisvalid) AS ready FROM pg_index
                WHERE indexrelid IN ('research_job_ready_collector'::regclass,
                    'research_job_expired_collector'::regclass,'research_campaign_work_job'::regclass)""").fetchone()['ready']
        self.assertTrue(valid)
        self.assertIn('research_job_ready_collector',str(plan))
        claimed=queue.claim(collector='campaign-preview-v1')
        self.assertEqual(claimed['id'],target['id'])
        queue.finish(claimed['id'],claimed['lease_token'])
        self.assertIsNone(queue.claim(collector='campaign-preview-v1'))
