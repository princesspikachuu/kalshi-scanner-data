"""Actual PostgreSQL handoffs, concurrent collection, cancellation and restart."""
import os
import time
import unittest
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from psycopg.types.json import Jsonb
import test_campaigns as fixtures
from services.research.campaigns import CampaignWorker
from services.research.processing import ProcessingWorker
from services.research.queue import LeaseLost
from services.research.datasets import prepare_dataset


@unittest.skipUnless(os.environ.get('POCKET_TEST_DATABASE_URL'),'Requires disposable pocket_test PostgreSQL')
class ProcessingPostgresTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.CampaignPostgresTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.CampaignPostgresTests.tearDownClass.__func__)
    make_worker=fixtures.CampaignPostgresTests.make_worker
    available=fixtures.CampaignPostgresTests.available
    create=fixtures.CampaignPostgresTests.create

    def setUp(self):
        fixtures.CampaignPostgresTests.setUp(self)
        self.worker.role='collector'
        self.processor=ProcessingWorker(self.db.pool,self.archives)

    def queued(self,kind='prices'):
        with self.db.pool.connection() as c:
            return c.execute("""SELECT * FROM research_job WHERE parameters->>'collector'='campaign-assembly-v1'
                AND parameters->>'kind'=%s ORDER BY created_at,id""",(kind,)).fetchall()

    def collect_until(self,predicate,limit=180):
        with patch('services.research.campaigns.prepare_dataset',side_effect=AssertionError('collector expanded evidence')), \
             patch('services.research.reports.ReportStore.publish_campaign',side_effect=AssertionError('collector built report')):
            for _ in range(limit):
                if predicate():return
                self.available();self.worker.run_once(deadline=time.monotonic()+30)
        self.fail('Collector failed to make durable handoff')

    def finish(self,identifier,limit=450):
        for _ in range(limit):
            self.available()
            self.worker.run_once(deadline=time.monotonic()+30)
            self.processor.run_once(deadline=time.monotonic()+30)
            state=self.store.get(identifier)
            if state['status']=='succeeded':return state
            self.assertNotEqual(state['status'],'failed',state)
        self.fail('Split did not finish bounded fixture')

    def test_collection_advances_while_processing_is_blocked_and_merges_latest_progress(self):
        identifier=self.create(start='2026-10-25',end='2026-10-27')
        self.collect_until(lambda:len(self.queued())==1)
        job=self.processor._claim_assembly();entered=Event();release=Event()
        def blocked(*args,**kwargs):
            entered.set()
            if not release.wait(10):raise AssertionError('processing release timed out')
            return prepare_dataset(*args,**kwargs)
        with patch('services.research.processing.prepare_dataset',side_effect=blocked),ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(self.processor._publish,job)
            try:
                self.assertTrue(entered.wait(5))
                # No processor completion is required to start the next date.
                self.collect_until(lambda:len(self.queued())>=2)
                self.assertEqual(self.queue.get(job['id'])['status'],'running')
                with self.db.pool.connection() as c:
                    parent=c.execute('SELECT job_id FROM research_campaign WHERE id=%s',(identifier,)).fetchone()['job_id']
                    c.execute('UPDATE research_job SET progress=progress||%s WHERE id=%s',(Jsonb({'concurrent_collector_marker':True}),parent))
            finally:release.set()
            future.result(timeout=10)
        self.assertTrue(self.queue.get(parent)['progress']['concurrent_collector_marker'])
        self.assertEqual(len(self.queue.get(parent)['progress']['candle_previews']),1)
        state=self.finish(identifier)
        self.assertEqual(state['completed_sections'],3)
        self.assertEqual(state['reported_sections'],3)

    def test_pause_resume_cancels_assembly_without_losing_saved_pages(self):
        identifier=self.create(end='2026-10-25')
        self.collect_until(lambda:bool(self.queued()))
        job=self.processor._claim_assembly()
        pages=self.store.get(identifier)['saved_pages']
        self.assertTrue(self.store.control(identifier,'pause'))
        self.assertEqual(self.queue.get(job['id'])['status'],'cancelled')
        with self.assertRaises(LeaseLost):self.processor._publish(job)
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM research_dataset').fetchone()['n'],0)
        self.assertTrue(self.store.control(identifier,'resume'))
        self.assertEqual(self.queue.get(job['id'])['status'],'queued')
        self.assertEqual(self.store.get(identifier)['saved_pages'],pages)
        self.processor=ProcessingWorker(self.db.pool,self.archives)
        self.assertEqual(self.finish(identifier)['completed_sections'],1)

    def test_expired_processor_cannot_publish_over_replacement(self):
        identifier=self.create(end='2026-10-25')
        self.collect_until(lambda:bool(self.queued()))
        stale=self.processor._claim_assembly()
        with self.db.pool.connection() as c:
            c.execute("UPDATE research_job SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",(stale['id'],))
        replacement=self.processor._claim_assembly()
        self.assertEqual(stale['id'],replacement['id'])
        self.assertNotEqual(stale['lease_token'],replacement['lease_token'])
        with self.assertRaises(LeaseLost):self.processor._publish(stale)
        self.processor._publish(replacement)
        self.assertEqual(self.queue.get(stale['id'])['status'],'succeeded')
        self.assertEqual(self.finish(identifier)['completed_sections'],1)

    def test_failed_handoff_is_visible_and_resume_reuses_it(self):
        identifier=self.create(end='2026-10-25')
        self.collect_until(lambda:bool(self.queued()))
        job=self.processor._claim_assembly()
        self.queue.fail(job['id'],job['lease_token'],'campaign_assembly_blocked',retry=False)
        self.collect_until(lambda:self.store.get(identifier)['status']=='failed')
        self.store.control(identifier,'resume')
        self.assertEqual(len(self.queued()),1)
        self.assertEqual(self.finish(identifier)['completed_sections'],1)

    def test_sample_handoff_does_not_block_full_candle_collection(self):
        from services.research.inventory import ProviderPage
        markets=[dict(ticker=f'KXBTC15M-SAMPLE-{i:03d}',event_ticker=f'EV-{i:03d}',series_ticker='KXBTC15M',
            close_time='2026-10-25T12:00:00Z',result='yes') for i in range(300)]
        self.inventory.fetch=lambda scope,cursor,timeout:ProviderPage(dict(markets=markets,cursor=''))
        self.worker.parallelism=12
        identifier=self.create(end='2026-10-25')
        self.collect_until(lambda:bool(self.queued('sample')),limit=180)
        self.collect_until(lambda:bool(self.queued('prices')),limit=350)
        self.assertEqual(self.queued('sample')[0]['status'],'queued')
        chosen=self.processor._claim_assembly()
        self.assertEqual(chosen['parameters']['kind'],'prices')
        self.processor._publish(chosen)
        with self.db.pool.connection() as c:
            parent=c.execute('SELECT j.progress FROM research_campaign r JOIN research_job j ON j.id=r.job_id WHERE r.id=%s',(identifier,)).fetchone()
        self.assertEqual(len(parent['progress']['candle_previews']),1)
        self.assertEqual(len(parent['progress']['sample_tickers']['2026-10-25']),100)

    def test_empty_day_passes_price_lane_before_enrichment(self):
        self.inventory.empty=True
        identifier=self.create(end='2026-10-25')
        self.collect_until(lambda:bool(self.queued('prices')))
        self.assertEqual(self.evidence.calls,[])
        state=self.finish(identifier)
        self.assertEqual(state['completed_sections'],1)
        self.assertEqual(state['reported_sections'],1)

    def test_oldest_request_holds_both_roles_through_waits_and_releases_on_pause(self):
        first=self.create(key='fifo-first',end='2026-10-25')
        newer=self.create(key='fifo-newer',end='2026-10-25')
        self.collect_until(lambda:bool(self.queued('prices')))
        oldest_job=self.queued('prices')[0]
        newer_job=self.queue.enqueue('btc',dict(collector='campaign-assembly-v1',campaign_id=str(newer),
            day='2026-10-25',kind='prices',tickers=[]),f'assembly/{newer}/2026-10-25/prices')
        claimed=self.processor._claim_assembly()
        self.assertEqual(claimed['id'],oldest_job['id'])
        self.queue.yield_job(claimed['id'],claimed['lease_token'],60)
        self.assertIsNone(self.processor._claim_assembly())
        parent=self.worker._claim_parent()
        self.assertEqual(parent['parameters']['campaign_id'],str(first))
        self.queue.yield_job(parent['id'],parent['lease_token'],60)
        self.assertIsNone(self.worker._claim_parent())
        self.store.control(first,'pause')
        next_parent=self.worker._claim_parent()
        self.assertEqual(next_parent['parameters']['campaign_id'],str(newer))
        self.queue.yield_job(next_parent['id'],next_parent['lease_token'])
        self.assertEqual(self.processor._claim_assembly()['id'],newer_job['id'])

    def test_child_lease_loss_releases_parent_without_advancing_to_newer_request(self):
        first=self.create(key='child-lease-first',end='2026-10-25')
        newer=self.create(key='child-lease-newer',end='2026-10-26')
        with patch.object(self.worker,'step',side_effect=LeaseLost('Child lease replaced')):
            with self.assertRaises(LeaseLost):
                self.worker.run_once(deadline=time.monotonic()+30)
        self.assertEqual(self.store.get(first)['status'],'queued')
        self.available()
        parent=self.worker._claim_parent()
        self.assertEqual(parent['parameters']['campaign_id'],str(first))
        self.assertEqual(parent['attempts'],1)
        self.assertEqual(self.store.get(newer)['saved_pages'],0)
        self.queue.yield_job(parent['id'],parent['lease_token'])

    def test_planning_batches_commit_and_recover_without_marking_partial_plan_complete(self):
        identifier=self.create(key='bounded-plan',end='2026-10-25')
        parent=self.worker._claim_parent()
        with self.db.pool.connection() as c:
            campaign=c.execute('SELECT * FROM research_campaign WHERE id=%s',(identifier,)).fetchone()
            day=c.execute('SELECT * FROM research_campaign_day WHERE campaign_id=%s',(identifier,)).fetchone()
        scopes=[SimpleNamespace(key=f'bounded-scope-{i}',parameters=lambda i=i:dict(collector='planner-fixture',item=i)) for i in range(150)]
        original=self.worker._insert_job_batch;batch_sizes=[]
        def interrupted(*args):
            batch_sizes.append(len(args[3]))
            if len(batch_sizes)==2:raise RuntimeError('Simulated database interruption')
            return original(*args)
        with patch.object(self.worker,'_insert_job_batch',side_effect=interrupted):
            with self.assertRaises(RuntimeError):self.worker._jobs(campaign,day,'evidence',scopes,parent)
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM research_campaign_work WHERE campaign_id=%s',(identifier,)).fetchone()['n'],64)
            self.assertFalse(c.execute('SELECT evidence_planned FROM research_campaign_day WHERE campaign_id=%s',(identifier,)).fetchone()['evidence_planned'])
        with patch.object(self.worker,'_insert_job_batch',wraps=original) as saved:
            self.worker._jobs(campaign,day,'evidence',scopes,parent)
            self.assertEqual([len(call.args[3]) for call in saved.call_args_list],[64,64,22])
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM research_campaign_work WHERE campaign_id=%s',(identifier,)).fetchone()['n'],150)
            self.assertTrue(c.execute('SELECT evidence_planned FROM research_campaign_day WHERE campaign_id=%s',(identifier,)).fetchone()['evidence_planned'])
        self.queue.yield_job(parent['id'],parent['lease_token'])

    def test_expired_coordinator_does_not_exhaust_oldest_request(self):
        first=self.create(key='expired-oldest',end='2026-10-25')
        newer=self.create(key='waiting-newer',end='2026-10-26')
        parent=self.worker._claim_parent()
        with self.db.pool.connection() as c:
            c.execute("UPDATE research_job SET attempts=max_attempts,lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",(parent['id'],))
        # Even another role's claim must not terminally fail the coordinator.
        self.queue.claim(collector='campaign-preview-v1')
        self.assertEqual(self.store.get(first)['status'],'queued')
        reclaimed=self.worker._claim_parent()
        self.assertEqual(reclaimed['id'],parent['id'])
        self.assertNotEqual(reclaimed['lease_token'],parent['lease_token'])
        with self.assertRaises(LeaseLost):self.queue.yield_job(parent['id'],parent['lease_token'])
        self.queue.yield_job(reclaimed['id'],reclaimed['lease_token'])
        with self.db.pool.connection() as c:
            c.execute("UPDATE research_job SET status='failed',error_code='attempts_exhausted' WHERE id=%s",(parent['id'],))
        self.queue.enqueue('btc',dict(collector='campaign-assembly-v1',campaign_id=str(newer),
            day='2026-10-26',kind='prices',tickers=[]),f'assembly/{newer}/2026-10-26/prices')
        self.assertEqual(str(self.worker.oldest_request()['id']),first)
        self.assertIsNone(self.worker._claim_parent())
        self.assertIsNone(self.processor._claim_assembly())
        self.store.control(first,'remove')
        self.assertEqual(str(self.worker.oldest_request()['id']),newer)

    def test_finishes_and_publishes_a_date_before_opening_the_eighth_unfinished_date(self):
        identifier=self.create(key='bounded-window',start='2026-10-20',end='2026-10-27')
        self.worker.preview_limit=300
        for _ in range(600):
            self.available();self.worker.run_once(deadline=time.monotonic()+30)
            self.processor.run_once(deadline=time.monotonic()+30)
            state=self.store.get(identifier)
            self.assertNotEqual(state['status'],'failed',state)
            if state['completed_sections']:break
        else:self.fail('A date never finished within the bounded window')
        with self.db.pool.connection() as c:
            oldest=c.execute("SELECT manifest FROM research_campaign_day WHERE campaign_id=%s AND day='2026-10-20'",(identifier,)).fetchone()
            finished=c.execute('SELECT dataset_id FROM research_campaign_day WHERE campaign_id=%s AND dataset_id IS NOT NULL',(identifier,)).fetchone()['dataset_id']
        self.assertIsNone(oldest['manifest'])
        # The next full campaign/category publications precede more assembly.
        for _ in range(3):self.available();self.processor.run_once(deadline=time.monotonic()+30)
        with self.db.pool.connection() as c:
            report=c.execute("SELECT report FROM research_result WHERE stream_key='category-btc' ORDER BY id DESC LIMIT 1").fetchone()['report']
        self.assertIn(finished,[d['id'] for d in report['datasets']])

    def test_oldest_finishes_enrichment_and_final_report_while_newer_waits(self):
        first=self.create(key='finish-oldest',end='2026-10-25')
        newer=self.create(key='hold-newer',end='2026-10-26')
        self.assertEqual(self.finish(first)['status'],'succeeded')
        waiting=self.store.get(newer)
        self.assertEqual(waiting['status'],'queued')
        self.assertEqual(waiting['saved_pages'],0)
        self.assertEqual(waiting['completed_sections'],0)

    def test_three_hundred_market_preview_publishes_with_explicit_limit(self):
        from services.research.inventory import ProviderPage
        from services.research.sample_reports import SampleReports
        markets=[dict(ticker=f'KXBTC15M-FAST-{i:03d}',event_ticker=f'EV-{i:03d}',series_ticker='KXBTC15M',
            close_time='2026-10-25T12:00:00Z',result='yes') for i in range(450)]
        self.inventory.fetch=lambda scope,cursor,timeout:ProviderPage(dict(markets=markets,cursor=''))
        self.worker.preview_limit=300;self.worker.parallelism=12
        identifier=self.create(end='2026-10-25')
        self.collect_until(lambda:bool(self.queued('sample')),limit=450)
        job=self.processor._claim_assembly()
        self.assertEqual(len(job['parameters']['tickers']),300)
        self.processor._publish(job)
        self.assertTrue(SampleReports(self.db.pool).run_once(campaign_id=identifier))
        state=self.store.get(identifier)
        self.assertEqual(state['completed_sections'],0)
        self.assertEqual(state['sample_reported_sections'],1)
        with self.db.pool.connection() as c:
            report=c.execute('SELECT report FROM research_result WHERE id=%s',(state['sample_result_id'],)).fetchone()['report']
        self.assertTrue(report['publication']['sampled_preview'])
        self.assertEqual(report['publication']['sample_limit'],300)
        self.assertEqual(report['historical']['candidate_count'],300)
