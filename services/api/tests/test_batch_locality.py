"""Batch locality is applied before the bounded SQL neighbor selection."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import os
import time
import unittest
from unittest.mock import Mock
from urllib.parse import urlsplit

from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.archive import ArchiveStore
from services.research.campaigns import CampaignStore,CampaignWorker
from services.research.evidence import EvidenceScope,KalshiEvidence,build_scopes
from services.research.queue import ResearchQueue
from test_evidence import BATCH,CANDIDATE
from test_normalize import MemoryObjects

URL=os.environ.get('POCKET_TEST_DATABASE_URL');UTC=timezone.utc


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class BatchLocalityPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL);cls.db=PostgresStore(URL);cls.db.open()
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def setUp(self):
        with self.db.pool.connection() as c:
            c.execute('TRUNCATE research_refresh,research_job,research_dataset,research_result,research_artifact,research_read_budget CASCADE')
        self.queue=ResearchQueue(self.db.pool);self.archives=ArchiveStore(MemoryObjects())

    def test_anchor_nearby_windows_win_before_limit_99_without_claiming_or_dropping_others(self):
        store=CampaignStore(self.db.pool)
        identifier=store.create('btc','2026-10-25','2026-10-25','batch-locality',
            now=datetime(2026,10,27,12,tzinfo=UTC))
        anchor=replace(CANDIDATE,ticker='KXBTC15M-ANCHOR',event_ticker='E-ANCHOR')
        near=[replace(CANDIDATE,ticker='KXBTC15M-NEAR-'+str(i),event_ticker='E-NEAR-'+str(i)) for i in range(100)]
        distant_close=(datetime.fromisoformat(CANDIDATE.close_time.replace('Z','+00:00'))+timedelta(hours=6)).isoformat().replace('+00:00','Z')
        far=[replace(CANDIDATE,ticker='KXBTC15M-FAR-'+str(i),event_ticker='E-FAR-'+str(i),close_time=distant_close) for i in range(120)]
        plan=build_scopes(replace(BATCH,candidates=tuple([anchor]+far+near)),self.archives,
            lookback_seconds=1020,resources=('candles',))
        scopes=[s for s in plan.scopes if s.source=='recent']
        with self.db.pool.connection() as c:
            campaign=c.execute('SELECT * FROM research_campaign WHERE id=%s',(identifier,)).fetchone()
            day=c.execute('SELECT * FROM research_campaign_day WHERE campaign_id=%s',(identifier,)).fetchone()
        parent=self.queue.claim(seconds=600,job_id=campaign['job_id'])
        worker=CampaignWorker(self.db.pool,self.archives,Mock(),Mock())
        worker._jobs(campaign,day,'evidence',scopes,parent)
        # Force the old available_at/UUID-only LIMIT99 to select far distractors.
        # Anchor is still the oldest fairly selected job; locality affects only
        # its compatible neighbors, never the campaign's primary claim order.
        with self.db.pool.connection() as c:
            c.execute("""UPDATE research_job SET available_at=clock_timestamp()-
                CASE WHEN parameters->'scope'->>'ticker'='KXBTC15M-ANCHOR' THEN interval '3 hours'
                     WHEN parameters->'scope'->>'ticker' LIKE 'KXBTC15M-FAR-%%' THEN interval '2 hours'
                     ELSE interval '1 hour' END
                WHERE id IN (SELECT job_id FROM research_campaign_work WHERE campaign_id=%s)""",(identifier,))
        provider=KalshiEvidence(archives=self.archives);self.addCleanup(provider.close)
        provider._read=Mock(side_effect=AssertionError('Selecting a batch must not fetch'))
        evidence=Mock();evidence.provider=provider;evidence.scope_loader=lambda job:EvidenceScope(**job['parameters']['scope'])
        prepared=[]
        def prepare(jobs):
            prepared.extend(jobs);provider.plan_batch([evidence.scope_loader(job) for job in jobs])
        evidence.prepare_batch.side_effect=prepare
        def finish(job,*,deadline):
            self.assertEqual(job['parameters']['scope']['ticker'],'KXBTC15M-ANCHOR')
            self.queue.finish(job['id'],job['lease_token']);return dict(state='complete',retry_after=0)
        evidence.step.side_effect=finish
        worker._one(campaign,day,'evidence',evidence,time.monotonic()+30)
        self.assertEqual(len(prepared),100);self.assertEqual(len(provider.batch),100)
        self.assertEqual(prepared[0]['parameters']['scope']['ticker'],'KXBTC15M-ANCHOR')
        self.assertTrue(all('NEAR-' in job['parameters']['scope']['ticker'] for job in prepared[1:]))
        with self.db.pool.connection() as c:
            counts=c.execute("""SELECT j.status,count(*) AS n FROM research_campaign_work w
                JOIN research_job j ON j.id=w.job_id WHERE w.campaign_id=%s GROUP BY j.status""",(identifier,)).fetchall()
        self.assertEqual({row['status']:row['n'] for row in counts},{'succeeded':1,'queued':220})
        provider._read.assert_not_called()
