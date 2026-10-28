"""Sample previews publish only their own immutable report stream."""
from datetime import date, datetime, timezone
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.campaigns import CampaignStore
from services.research.queue import EvidenceConflict, ResearchQueue
from services.research.sample_reports import SampleReports, sample_snapshot
from test_reports import dataset

URL = os.environ.get('POCKET_TEST_DATABASE_URL')


class SampleMembershipTests(unittest.TestCase):
    def test_snapshot_requires_exact_days_and_dedicated_dataset_stream(self):
        stream = 'campaign-sample-' + 'a' * 32
        days = [date(2026, 10, 1), date(2026, 10, 2)]
        rows = [dict(id=4, day=days[0], stream_key=stream)]
        expected = sample_snapshot({'2026-10-01': 4}, days, rows, stream)
        self.assertEqual(expected['ids'], [4])
        self.assertEqual(expected['publication'], dict(complete=False, sampled_preview=True,
            sample_limit=100, reported_sections=1, total_sections=2, revision=4))
        for mapping, sources in [({'2026-10-03': 4}, rows), ({'2026-10-01': 4}, []),
                                 ({'2026-10-01': 4}, [{**rows[0], 'stream_key': 'campaign-full'}]),
                                 ({'2026-10-01': 4, '2026-10-02': 4}, rows)]:
            with self.subTest(mapping=mapping, sources=sources), self.assertRaises(EvidenceConflict):
                sample_snapshot(mapping, days, sources, stream)


@unittest.skipUnless(URL, 'Requires disposable pocket_test PostgreSQL')
class SampleReportPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path != '/pocket_test':
            raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL)
        cls.db = PostgresStore(URL)
        cls.db.open()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        self.pacing = patch('services.research.report_jobs.INTERVAL_SECONDS', 0)
        self.pacing.start()
        self.addCleanup(self.pacing.stop)
        with self.db.pool.connection() as c:
            c.execute('TRUNCATE research_refresh,research_job,research_dataset,research_result,research_artifact,research_read_budget CASCADE')
        self.queue = ResearchQueue(self.db.pool)
        self.reports = SampleReports(self.db.pool)
        self.campaign = CampaignStore(self.db.pool).create('btc', '2026-10-01', '2026-10-02',
            'sample-report-fixture', now=datetime(2026, 10, 27, tzinfo=timezone.utc))

    def add_preview(self, day):
        source = dataset(day=day)
        with self.db.pool.connection() as c:
            identifier = c.execute('''INSERT INTO research_dataset(stream_key,fingerprint,day,payload)
                VALUES(%s,%s,%s,%s) RETURNING id''',
                ('campaign-sample-' + self.campaign.replace('-', ''), source['fingerprint'],
                 source['payload']['day'], Jsonb(source['payload']))).fetchone()['id']
            c.execute('''UPDATE research_job SET progress=jsonb_set(progress,'{sample_previews}',
                coalesce(progress->'sample_previews','{}'::jsonb)||%s::jsonb,true)
                WHERE id=(SELECT job_id FROM research_campaign WHERE id=%s)''',
                (Jsonb({source['payload']['day']: identifier}), self.campaign))
            self.reports.enqueue(c, self.campaign, 'btc')
        return identifier

    def test_partial_sample_reports_advance_without_entering_full_or_category_streams(self):
        first = self.add_preview(1)
        self.assertTrue(self.reports.run_once())
        second = self.add_preview(2)
        self.assertTrue(self.reports.run_once())
        stream = 'campaign-sample-' + self.campaign.replace('-', '')
        with self.db.pool.connection() as c:
            latest = c.execute('''SELECT id,report FROM research_result WHERE stream_key=%s ORDER BY id DESC LIMIT 1''',
                               (stream,)).fetchone()
            members = c.execute('''SELECT dataset_id FROM research_result_dataset WHERE result_id=%s ORDER BY dataset_id''',
                                (latest['id'],)).fetchall()
            other = c.execute("SELECT count(*) AS n FROM research_result WHERE stream_key LIKE 'category-%' OR stream_key=%s",
                              ('campaign-' + self.campaign.replace('-', ''),)).fetchone()['n']
            category_jobs = c.execute("SELECT count(*) AS n FROM research_job WHERE parameters->>'collector'='category-report-v1'").fetchone()['n']
        self.assertEqual([r['dataset_id'] for r in members], [first, second])
        self.assertEqual(latest['report']['historical']['candidate_count'], 2)
        self.assertEqual(latest['report']['publication'], dict(complete=False, sampled_preview=True,
            sample_limit=100, reported_sections=2, total_sections=2, revision=second))
        self.assertEqual((other, category_jobs), (0, 0))
