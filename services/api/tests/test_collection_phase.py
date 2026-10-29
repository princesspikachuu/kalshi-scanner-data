"""The original-sized collection contract and independent saved-data analysis."""
import os,time,unittest
from unittest.mock import patch
import test_campaigns as f
import test_processing as processing_fixtures
from services.research.campaigns import CampaignStore
from services.research.processing import ProcessingWorker
from services.research.backlog import AnalysisBacklog
from services.research.inventory import ProviderPage
from services.research.report_inputs import report_dataset


@unittest.skipUnless(os.environ.get('POCKET_TEST_DATABASE_URL'),'Requires disposable pocket_test PostgreSQL')
class CollectionPhaseTests(unittest.TestCase):
    setUpClass=classmethod(f.CampaignPostgresTests.setUpClass.__func__)
    tearDownClass=classmethod(f.CampaignPostgresTests.tearDownClass.__func__)
    make_worker=f.CampaignPostgresTests.make_worker
    available=f.CampaignPostgresTests.available
    create=f.CampaignPostgresTests.create
    finish=processing_fixtures.ProcessingPostgresTests.finish

    def setUp(self):
        f.CampaignPostgresTests.setUp(self)
        self.store=CampaignStore(self.db.pool,collection_limit=300)
        self.worker.role='collector';self.worker.preview_limit=300
        self.processor=ProcessingWorker(self.db.pool,self.archives)

    def membership(self,identifier):
        with self.db.pool.connection() as c:
            row=c.execute('SELECT ds.id,ds.fingerprint,ds.payload FROM research_campaign_day d JOIN research_dataset ds ON ds.id=d.dataset_id WHERE d.campaign_id=%s',(identifier,)).fetchone()
        return {c['ticker'] for c in report_dataset(row)['payload']['candidates']}

    def test_three_hundred_completes_without_trades_and_rerun_adds_different_markets(self):
        markets=[dict(ticker=f'KXBTC15M-COHORT-{i:03d}',event_ticker=f'E-{i:03d}',series_ticker='KXBTC15M',
            close_time='2026-10-25T12:00:00Z',result='yes') for i in range(600)]
        self.inventory.fetch=lambda scope,cursor,timeout:ProviderPage(dict(markets=markets,cursor=''))
        self.worker.parallelism=12
        first=self.create(key='cohort-first',end='2026-10-25')
        self.assertEqual(self.finish(first,limit=700)['completed_sections'],1)
        a=self.membership(first);self.assertEqual(len(a),300)
        self.assertEqual(self.store.get(first)['analyzed_sections'],0)
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM research_job WHERE parameters->'scope'->>'resource'='trades' AND status='succeeded'").fetchone()['n'],0)
        self.store.control(first,'remove')
        second=self.create(key='cohort-second',end='2026-10-25')
        self.assertEqual(self.finish(second,limit=700)['completed_sections'],1)
        b=self.membership(second);self.assertEqual(len(b),300);self.assertFalse(a&b)
        with self.db.pool.connection() as c:
            report=c.execute("SELECT report FROM research_result WHERE stream_key='category-btc' ORDER BY id DESC LIMIT 1").fetchone()['report']
        self.assertEqual(report['historical']['candidate_count'],600)
        self.assertEqual(self.store.count('all','finished'),1)

    def test_saved_data_analysis_survives_removal_and_yields_to_new_requests(self):
        first=self.create(key='analyze-saved',end='2026-10-25')
        self.finish(first);self.store.control(first,'remove')
        backlog=AnalysisBacklog(self.worker);backlog.bootstrap()
        with self.db.pool.connection() as c:
            job=c.execute("SELECT * FROM research_job WHERE parameters->>'collector'='saved-analysis-v1' ORDER BY created_at LIMIT 1").fetchone()
        self.assertIsNotNone(job)
        next_run=self.create(key='analysis-preemption',end='2026-10-26')
        calls=len(self.evidence.calls)
        self.assertFalse(backlog.run_once(deadline=time.monotonic()+30));self.assertEqual(len(self.evidence.calls),calls)
        self.store.control(next_run,'pause')
        for _ in range(100):
            self.available();backlog.run_once(deadline=time.monotonic()+30)
            if self.queue.get(job['id'])['status']=='succeeded':break
        else:self.fail('Saved-data analysis did not finish after request removal')
        self.assertEqual(self.store.analysis_status()['categories'][0]['analyzed_days'],1)

    def test_clean_windows_raise_pace_only_to_configured_ceiling(self):
        self.budget.configure(4,1,allow_update=True)
        with self.db.pool.connection() as c:
            c.execute("UPDATE research_read_budget SET refill_per_second=1,tokens=0")
            c.execute("UPDATE research_job SET progress=progress||jsonb_build_object('adjusted_at',clock_timestamp()-interval '61 seconds') WHERE idempotency_key='pacing/kalshi-read'")
        self.budget.successful()
        with self.db.pool.connection() as c:
            self.assertAlmostEqual(c.execute('SELECT refill_per_second FROM research_read_budget').fetchone()['refill_per_second'],1.1)
        self.budget.rate_limited(1)
        with self.db.pool.connection() as c:
            self.assertAlmostEqual(c.execute('SELECT refill_per_second FROM research_read_budget').fetchone()['refill_per_second'],.55)

    def test_verified_authenticated_allowance_applies_once_and_preserves_backoff(self):
        self.budget.configure(18,1,allow_update=True);self.budget.authenticated(18,'test-key')
        self.budget.rate_limited(1)
        self.budget.configure(18,1,allow_update=True);self.budget.authenticated(18,'test-key')
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute('SELECT refill_per_second FROM research_read_budget').fetchone()['refill_per_second'],9)
