"""Date ranges, exact rolling windows and credential-free full-pipeline recovery."""
from datetime import datetime,timedelta,timezone
from dataclasses import asdict
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.archive import ArchiveStore
from services.research.budget import ReadBudget
from services.research.campaigns import CampaignStore,CampaignWorker,sections,configuration
from services.research.evidence import EvidenceWorker
from services.research.inventory import InventoryWorker,ProviderPage,ProviderFailure,Scope
from services.research.normalize import normalize_inventory
from services.research.queue import ResearchQueue,LeaseLost,EvidenceConflict
from services.research.reports import prepare_report,prepare_report_stream
from test_archives import MemoryObjects
from test_reports import dataset

URL=os.environ.get('POCKET_TEST_DATABASE_URL');UTC=timezone.utc
NOW=datetime(2026,10,27,12,30,tzinfo=UTC)


class RangeTests(unittest.TestCase):
    def test_long_range_leap_day_and_exact_rolling_midnight_boundaries(self):
        days=sections(datetime(2024,1,1,tzinfo=UTC),datetime(2025,1,1,tzinfo=UTC))
        self.assertEqual(len(days),366);self.assertEqual(days[59]['day'],'2024-02-29')
        rolling=sections(NOW-timedelta(hours=24),NOW)
        self.assertEqual(len(rolling),2)
        self.assertEqual(sum((s['end_at']-s['start_at']).total_seconds() for s in rolling),86400)
        self.assertEqual(rolling[0]['end_at'],rolling[1]['start_at'])
        self.assertEqual(len(sections(NOW.replace(hour=0,minute=0)-timedelta(days=1),NOW.replace(hour=0,minute=0))),1)
        for a,b in ((NOW,NOW),(NOW,NOW-timedelta(days=1)),(NOW,NOW+timedelta(days=3661)),(NOW.replace(tzinfo=None),NOW)):
            with self.assertRaises(ValueError):sections(a,b)

    def test_lookback_covers_every_entry_without_expanding_market_window(self):
        self.assertEqual(configuration('btc')['lookback_seconds'],1020)
        self.assertEqual(configuration('sports')['lookback_seconds'],21720)
        with self.assertRaises(ValueError):configuration('financial_daily')

    def test_streamed_report_is_byte_identical_with_full_cohort_and_latest_policy(self):
        inputs=[dataset(i,day=i,won=i%2==0) for i in range(1,21)]
        full=prepare_report('btc',inputs,latest_ids=[19,20])
        streamed=prepare_report_stream('btc',(d for d in inputs),latest_ids=[19,20])
        self.assertEqual(full,streamed)
        # Golden computed using the unmodified e63e093 model, before the streaming refactor.
        self.assertEqual(streamed.fingerprint,'bc634c20ca1daf3ad8fcf0e6d6c378b4c6e8beea6296c75a993c6fe54ae6466a')
        self.assertEqual(json.loads(streamed.payload_json)['historical']['candidate_count'],20)
        with self.assertRaises(ValueError):prepare_report_stream('btc',iter(reversed(inputs)),latest_ids=[])


class InventoryProvider:
    def __init__(self,*,empty=False):self.calls=[];self.empty=empty;self.rate_limit=False;self.fail=False
    def fetch(self,scope,cursor,timeout):
        self.calls.append((scope.source,scope.day,cursor))
        if self.rate_limit:self.rate_limit=False;raise ProviderFailure('provider_rate_limit',delay=1)
        if self.fail:raise ProviderFailure('provider_invalid',retry=False)
        # Historical index spans every date. Recent daily traversals have TWO pages.
        days=['2026-10-25','2026-10-26','2026-10-27'] if scope.source=='historical' else [scope.day]
        rows=[] if self.empty or cursor else [dict(ticker='KXBTC15M-'+d,event_ticker='E-'+d,series_ticker='KXBTC15M',
            close_time=d+'T12:00:00Z',result='yes') for d in days]
        return ProviderPage(dict(markets=rows,cursor='next' if scope.source=='recent' and not cursor else ''))


class EvidenceProvider:
    def __init__(self):self.calls=[]
    def fetch(self,scope,cursor,timeout):
        self.calls.append(scope.key)
        if scope.resource=='trades':return ProviderPage({'trades':[],'cursor':''})
        close=int(datetime.fromisoformat(scope.close_time.replace('Z','+00:00')).timestamp())
        bars=[dict(end_period_ts=t,yes_bid={'close':'0.88'}) for t in (close-900,close-600,close-300,close-180,close-60) if scope.start_ts<=t<=scope.end_ts]
        return ProviderPage(dict(ticker=scope.ticker,candlesticks=bars))


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class CampaignPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL);cls.db=PostgresStore(URL);cls.db.open()
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def setUp(self):
        with self.db.pool.connection() as c:
            c.execute('TRUNCATE research_refresh,research_job,research_dataset,research_result,research_artifact,research_read_budget CASCADE')
        self.store=CampaignStore(self.db.pool);self.queue=ResearchQueue(self.db.pool)
        self.archives=ArchiveStore(MemoryObjects());self.inventory=InventoryProvider();self.evidence=EvidenceProvider()
        self.budget=ReadBudget(self.db.pool);self.budget.configure(100000,100000)
        self.worker=self.make_worker()
    def make_worker(self):
        return CampaignWorker(self.db.pool,self.archives,
            InventoryWorker(self.queue,self.archives,self.inventory,self.budget,endpoint_cost=1),
            EvidenceWorker(self.queue,self.archives,self.evidence,self.budget,endpoint_cost=1))
    def create(self,key='range',start='2026-10-25',end='2026-10-26'):
        return self.store.create('btc',start,end,key,now=NOW)
    def drive(self,identifier,limit=150):
        for _ in range(limit):
            if self.store.get(identifier)['status'] in ('failed','succeeded','cancelled'):return
            self.worker.run_once(deadline=time.monotonic()+30)
        self.fail('Campaign did not finish within bounded fixture steps')
    def available(self):
        with self.db.pool.connection() as c:
            c.execute("UPDATE research_job SET available_at=clock_timestamp() WHERE status='queued'")
            c.execute("UPDATE research_read_budget SET blocked_until=clock_timestamp()")

    def test_batched_recent_candles_publish_full_cohort_and_survive_cache_loss(self):
        import httpx
        from unittest.mock import Mock
        from services.research.evidence import KalshiEvidence
        from test_kalshi import reply
        from threading import Barrier,Lock
        calls=[];gate=Barrier(4);lock=Lock();entered=0
        self.worker.parallelism=4
        original=self.inventory.fetch
        def many(scope,cursor,timeout):
            page=original(scope,cursor,timeout)
            page.payload['markets']=[{**m,'ticker':m['ticker']+'-'+str(i),'event_ticker':m['event_ticker']+'-'+str(i)}
                                     for m in page.payload['markets'] for i in range(3)]
            return page
        self.inventory.fetch=many
        def handler(request):
            nonlocal entered
            calls.append(request)
            if request.url.path!='/trade-api/v2/markets/candlesticks' and not request.url.path.startswith('/trade-api/v2/series/'):
                with lock:
                    entered+=1;ordinal=entered
                if ordinal<=4:gate.wait(timeout=5)  # Proves four overlapping reads, no sleeps.
            if request.url.path.endswith('/trades'):return reply(payload={'trades':[],'cursor':''})
            start=int(request.url.params['start_ts']);end=int(request.url.params['end_ts'])
            bars=[dict(end_period_ts=end-m*60,yes_bid={'close':'0.88'}) for m in (15,10,5,3,1) if end-m*60>=start]
            if request.url.path=='/trade-api/v2/markets/candlesticks':
                tickers=request.url.params['market_tickers'].split(',')
                return reply(payload={'markets':[dict(market_ticker=t,candlesticks=bars) for t in tickers]})
            return reply(payload=dict(ticker=request.url.path.split('/')[-2],candlesticks=bars))
        def install():
            provider=KalshiEvidence(archives=self.archives,transport=httpx.MockTransport(handler));self.addCleanup(provider.close)
            self.worker.evidence_worker=EvidenceWorker(self.queue,self.archives,provider,self.budget,endpoint_cost=1)
            return provider
        install();identifier=self.create(start='2026-10-25',end='2026-10-25')
        # Lose the process-local batch cache after its first child checkpoints.
        for _ in range(40):
            self.worker.run_once(deadline=time.monotonic()+30)
            if any(r.url.path=='/trade-api/v2/markets/candlesticks' for r in calls):break
        else:self.fail('Batch endpoint was not used')
        install();self.drive(identifier)
        state=self.store.get(identifier);self.assertEqual(state['status'],'succeeded')
        with self.db.pool.connection() as c:
            report=c.execute('SELECT report FROM research_result WHERE id=%s',(state['result_id'],)).fetchone()['report']
            n=c.execute('SELECT count(*) AS n FROM research_observation WHERE result_id=%s',(state['result_id'],)).fetchone()['n']
        self.assertGreaterEqual(entered,4)
        self.assertEqual(report['historical']['candidate_count'],3);self.assertEqual(n,15)
        self.assertEqual(sum(cell['hold']['sampled_markets'] for cell in report['historical']['cells']),15)
        self.assertTrue(all(cell['hold']['sampled_markets']==cell['loss_prevention']['sampled_markets'] for cell in report['historical']['cells']))

    def test_candle_reports_arrive_before_trade_enrichment_and_grow_across_days(self):
        original=self.evidence.fetch;trade_pages=0
        def streaming(scope,cursor,timeout):
            nonlocal trade_pages
            if scope.resource=='trades':
                trade_pages+=1
                return ProviderPage(dict(trades=[],cursor='trade-page-'+str(trade_pages)))
            return original(scope,cursor,timeout)
        self.evidence.fetch=streaming;identifier=self.create()
        for _ in range(120):
            self.worker.run_once(deadline=time.monotonic()+30)
            state=self.store.get(identifier)
            if state['reported_sections']==2:break
        else:self.fail('Candle-complete sections were not published while enrichment continued')
        self.assertFalse(state['report_complete']);self.assertLess(state['completed_sections'],2)
        self.assertIn(state['status'],('queued','running'))
        with self.db.pool.connection() as c:
            report=c.execute('SELECT report FROM research_result WHERE id=%s',(state['result_id'],)).fetchone()['report']
            observations=c.execute('SELECT count(*) AS n FROM research_observation WHERE result_id=%s',(state['result_id'],)).fetchone()['n']
        self.assertEqual(report['historical']['candidate_count'],2)
        self.assertEqual(report['historical']['observation_count'],10)
        self.assertEqual(sum(x['hold']['sampled_markets'] for x in report['historical']['cells']),10)
        self.assertEqual(observations,0)  # Raw immutable inputs retain every row; no quadratic preview copies.
        before=state['result_id'];self.evidence.fetch=original
        self.worker=self.make_worker();self.drive(identifier,limit=250)
        final=self.store.get(identifier);self.assertTrue(final['report_complete'])
        self.assertNotEqual(final['result_id'],before)
        with self.db.pool.connection() as c:
            full=c.execute('SELECT report FROM research_result WHERE id=%s',(final['result_id'],)).fetchone()['report']
            n=c.execute('SELECT count(*) AS n FROM research_observation WHERE result_id=%s',(final['result_id'],)).fetchone()['n']
            old=c.execute('SELECT report FROM research_result WHERE id=%s',(before,)).fetchone()['report']
        self.assertEqual(full['historical']['cells'],report['historical']['cells'])
        self.assertEqual(n,10);self.assertEqual(old,report)

    def test_campaign_history_keyset_is_category_scoped_and_survives_new_inserts(self):
        ids=[self.create(key='history-'+str(i)) for i in range(4)]
        other=self.store.create('eth','2026-10-25','2026-10-26','history-other',now=NOW)
        first=self.store.list('btc',limit=2)
        self.assertEqual([r['id'] for r in first],list(reversed(ids[2:])))
        inserted=self.create(key='history-after-page')
        second=self.store.list('btc',before=first[-1]['id'],limit=2)
        self.assertEqual([r['id'] for r in second],list(reversed(ids[:2])))
        self.assertNotIn(inserted,[r['id'] for r in second])
        self.assertEqual(first[0]['total_sections'],2);self.assertEqual(first[0]['completed_sections'],0)
        self.assertEqual(self.store.list('btc',before=other),[])
        self.assertEqual(self.store.list('weather'),[])

    def test_saved_page_progress_uses_distinct_child_jobs_and_does_not_read_raw_objects(self):
        identifier=self.create();self.worker.run_once(deadline=time.monotonic()+30)
        progress=self.store.get(identifier)
        self.assertGreater(progress['work_items'],0)
        self.assertGreaterEqual(progress['saved_pages'],1)
        self.assertLessEqual(progress['completed_work_items'],progress['work_items'])
        self.assertIsNone(progress['last_work_error'])

    def test_category_publication_deduplicates_rechecks_and_preserves_old_reports(self):
        from services.research.cumulative import CategoryReports
        first=self.create(key='category-first');self.drive(first)
        category=CategoryReports(self.db.pool);self.assertTrue(category.run_once())
        with self.db.pool.connection() as c:
            old=c.execute("SELECT id,report,fingerprint FROM research_result WHERE stream_key='category-btc' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(old['report']['historical']['candidate_count'],2)
        second=self.store.create('btc','2026-10-25','2026-10-25','category-recheck',now=NOW,refresh_existing=True)
        self.drive(second);self.assertTrue(category.run_once())
        with self.db.pool.connection() as c:
            new=c.execute("SELECT id,report FROM research_result WHERE stream_key='category-btc' ORDER BY id DESC LIMIT 1").fetchone()
            retained=c.execute('SELECT fingerprint FROM research_result WHERE id=%s',(old['id'],)).fetchone()
        self.assertGreater(new['id'],old['id']);self.assertEqual(new['report']['historical']['candidate_count'],2)
        self.assertEqual(retained['fingerprint'],old['fingerprint'])
        self.assertEqual(len(new['report']['datasets']),2)

    def test_frozen_category_retry_cannot_replace_a_newer_publication(self):
        from services.research.cumulative import CategoryReports
        first=self.create(key='stale-first');self.drive(first)
        category=CategoryReports(self.db.pool)
        job=self.queue.claim(seconds=600,collector='category-report-v1')
        with patch('services.research.cumulative.prepare_category',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):category.step(job)
        second=self.store.create('btc','2026-10-25','2026-10-25','stale-recheck',now=NOW,refresh_existing=True)
        self.drive(second);self.assertTrue(category.run_once())
        with self.db.pool.connection() as c:
            newest=c.execute("SELECT id FROM research_result WHERE stream_key='category-btc' ORDER BY id DESC LIMIT 1").fetchone()['id']
            c.execute("UPDATE research_job SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s",(job['id'],))
        self.assertTrue(category.run_once())
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute("SELECT id FROM research_result WHERE stream_key='category-btc' ORDER BY id DESC LIMIT 1").fetchone()['id'],newest)
        self.assertEqual(self.queue.get(job['id'])['status'],'succeeded')

    def test_multiple_days_finish_full_report_and_reuse_historical_index_once(self):
        identifier=self.create();self.drive(identifier)
        row=self.store.get(identifier);self.assertEqual((row['status'],row['completed_sections'],row['total_sections']),('succeeded',2,2))
        self.assertEqual(sum(source=='historical' for source,day,cursor in self.inventory.calls),1)
        self.assertEqual(sum(source=='recent' for source,day,cursor in self.inventory.calls),4)
        with self.db.pool.connection() as c:
            report=c.execute('SELECT report FROM research_result WHERE id=%s',(int(row['result_id']),)).fetchone()['report']
        self.assertEqual(report['historical']['candidate_count'],2)
        self.assertEqual(report['latest']['candidate_count'],2)
        for cell in report['historical']['cells']:
            self.assertEqual(cell['hold']['sampled_markets'],2)
            self.assertEqual(cell['loss_prevention']['sampled_markets'],2)
        self.assertEqual(len(self.store.days(identifier)),2)

    def test_restart_pause_resume_reuses_committed_page_and_fences_old_parent(self):
        identifier=self.create()
        parent=self.queue.claim(collector='campaign-v1',seconds=600)
        self.worker.step(parent,deadline=time.monotonic()+30)
        self.store.control(identifier,'pause')
        self.assertEqual(self.store.get(identifier)['status'],'cancelled')
        with self.assertRaises(LeaseLost):self.queue.yield_job(parent['id'],parent['lease_token'])
        self.store.control(identifier,'resume');self.worker=self.make_worker();self.drive(identifier)
        self.assertEqual(self.store.get(identifier)['status'],'succeeded')
        # Healthy page advances have not consumed the five-failure budget.
        self.assertLessEqual(max(self.queue.get(uuid)['attempts'] for uuid in self._ids()),1)
        self.assertEqual(len(self.inventory.calls),5)
    def _ids(self):
        with self.db.pool.connection() as c:return [r['id'] for r in c.execute('SELECT id FROM research_job').fetchall()]

    def test_rate_limit_waits_and_terminal_failure_resumes_without_false_publication(self):
        identifier=self.create();self.inventory.rate_limit=True
        self.worker.run_once(deadline=time.monotonic()+30)
        self.assertEqual(self.store.get(identifier)['completed_sections'],0)
        self.assertFalse(self.worker.run_once(deadline=time.monotonic()+30))
        self.available();self.inventory.fail=True
        self.drive(identifier);self.assertEqual(self.store.get(identifier)['status'],'failed')
        self.assertEqual(self.store.get(identifier)['completed_sections'],0)
        self.inventory.fail=False;self.store.control(identifier,'resume');self.drive(identifier)
        self.assertEqual(self.store.get(identifier)['status'],'succeeded')

    def test_duplicate_requests_and_overlapping_backfills_reuse_exact_completed_sections(self):
        identifier=self.create()
        self.assertEqual(self.create(),identifier)
        with self.assertRaises(EvidenceConflict):self.create(end='2026-10-25')
        self.drive(identifier);calls=(len(self.inventory.calls),len(self.evidence.calls))
        reused=self.create(key='reuse');self.drive(reused)
        self.assertEqual(self.store.get(reused)['status'],'succeeded')
        self.assertEqual(calls,(len(self.inventory.calls),len(self.evidence.calls)))
        self.assertEqual([r['dataset_id'] for r in self.store.days(identifier)],[r['dataset_id'] for r in self.store.days(reused)])
        fresh=self.store.create('btc','2026-10-25','2026-10-26','force-refresh',now=NOW,refresh_existing=True)
        self.drive(fresh)
        self.assertGreater(len(self.inventory.calls),calls[0])
        self.assertNotEqual(self.store.days(fresh)[0]['dataset_id'],self.store.days(identifier)[0]['dataset_id'])

    def test_opt_in_scheduler_concurrency_coalesces_and_exact_24h_filters_membership(self):
        self.assertFalse(self.store.refresh('btc')['enabled']);self.assertEqual(self.store.schedule_due(now=NOW),[])
        self.store.set_refresh('btc',True)
        with self.db.pool.connection() as c:c.execute('UPDATE research_refresh SET next_due=%s',(NOW-timedelta(days=1),))
        with ThreadPoolExecutor(max_workers=4) as executor:
            ids=[i for group in executor.map(lambda _:self.store.schedule_due(now=NOW),range(4)) for i in group]
        self.assertEqual(len(ids),1);identifier=ids[0]
        self.assertEqual(self.store.schedule_due(now=NOW+timedelta(hours=2)),[])
        row=self.store.get(identifier);self.assertEqual(row['end_at']-row['start_at'],timedelta(hours=24))
        self.drive(identifier);self.assertEqual(self.store.get(identifier)['status'],'succeeded')
        # Oct 26 closes at noon, before the 12:30 start, so it MUST be excluded.
        with self.db.pool.connection() as c:
            p=c.execute('SELECT report FROM research_result WHERE id=%s',(int(self.store.get(identifier)['result_id']),)).fetchone()['report']
        self.assertEqual(p['historical']['candidate_count'],1)
        self.store.set_refresh('btc',False)
        self.assertEqual(self.store.schedule_due(now=NOW+timedelta(days=2)),[])

    def test_current_day_idempotency_keeps_frozen_cutoff_and_sections_page_without_skip(self):
        identifier=self.create(key='today',start='2026-10-25',end='2026-10-27')
        retry=self.store.create('btc','2026-10-25','2026-10-27','today',now=NOW+timedelta(days=1))
        self.assertEqual(identifier,retry);self.assertEqual(self.store.get(identifier)['end_at'],NOW)
        first=self.store.days(identifier,limit=1)
        rest=self.store.days(identifier,after=first[-1]['day'])
        self.assertEqual([r['day'] for r in first+rest],['2026-10-25','2026-10-26','2026-10-27'])
        self.assertTrue(all(r['stage']=='pending' for r in first+rest))

    def test_empty_days_complete_without_inventing_observations_and_old_batch_hashes_unchanged(self):
        self.inventory.empty=True;identifier=self.create();self.drive(identifier)
        self.assertEqual(self.store.get(identifier)['status'],'succeeded')
        with self.db.pool.connection() as c:
            p=c.execute('SELECT report FROM research_result WHERE id=%s',(int(self.store.get(identifier)['result_id']),)).fetchone()['report']
        self.assertEqual(p['historical']['candidate_count'],0);self.assertEqual(p['historical']['cells'],[])
        from test_datasets import Fixture
        f=Fixture();original=f.batch.fingerprint
        rebuilt=normalize_inventory(f.batch.series,f.batch.day,f.batch.generation,list(f.inventory.values()),f.archives)
        self.assertEqual(rebuilt.fingerprint,original);self.assertNotIn('window_start',asdict(rebuilt))
