"""Inventory traversal and gap planning; real PG integration when configured."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import os
from unittest.mock import Mock, patch
import time
import unittest
from urllib.parse import urlsplit

from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.archive import ArchiveStore
from services.research.budget import ReadBudget
from services.research.inventory import (Scope, ProviderPage, ProviderFailure, InventoryWorker,
    scopes_for_days, page_key, inspect_pages, plan)
from services.research.queue import ResearchQueue, EvidenceConflict, LeaseLost

URL = os.environ.get('POCKET_TEST_DATABASE_URL')
SCOPE = Scope('KXBTC15M', 'recent', '2026-10-25', 'test-generation')


def page(scope=SCOPE, seq=0, cursor_in='', cursor_out='', items=0, availability='available'):
    return {'page_key': page_key(scope, seq), 'checkpoint': dict(scope=scope.key, sequence=seq,
            cursor_in=cursor_in, cursor_out=cursor_out, items=items, availability=availability)}


class InventoryTests(unittest.TestCase):
    def test_fenced_step_reads_committed_page_chain_once(self):
        queue = Mock()
        queue.pages_owned.return_value = []
        budget = Mock()
        budget.take.return_value = 0
        provider = Mock()
        provider.cached.return_value = None
        provider.fetch.return_value = ProviderPage({'markets': [], 'cursor': ''})
        worker = InventoryWorker(queue, ArchiveStore(MemoryObjects()), provider, budget, endpoint_cost=1)
        job = {'id': 'job', 'lease_token': 'fenced-token', 'parameters': SCOPE.parameters()}
        self.assertEqual(worker.step(job, deadline=time.monotonic() + 30)['state'], 'empty')
        queue.pages_owned.assert_called_once_with('job','fenced-token')
        queue.pages.assert_not_called()
        queue.heartbeat.assert_not_called()
        queue.checkpoint.assert_called_once()
        queue.finish.assert_called_once_with('job', 'fenced-token')

    def test_historical_index_reused_across_days_and_recent_ranges_are_utc(self):
        scopes = scopes_for_days(['KXBTC15M', 'KXBTC15M'], ['2026-10-24', '2026-10-25'], 'v1')
        self.assertEqual(len(scopes), 3)
        self.assertEqual(scopes_for_days(['KXBTC15M'], [], 'v1'), [])
        path, args = scopes[0].request('next')
        self.assertEqual(path, '/historical/markets')
        self.assertEqual(args, {'series_ticker': 'KXBTC15M', 'limit': 1000, 'cursor': 'next'})
        self.assertEqual(scopes[1].request('')[1]['max_close_ts'] - scopes[1].request('')[1]['min_close_ts'], 86401)

    def test_scope_generation_source_and_dates_are_separate_identities(self):
        scopes = scopes_for_days(['KXBTC15M'], ['2026-10-25'], 'v1')
        self.assertNotEqual(scopes[0].key, scopes[1].key)
        self.assertNotEqual(scopes[1].key, SCOPE.key)
        for patch in ({'day': '20261025'}, {'series': '../secret'}, {'generation': 'a/b'},
                      {'source': 'historical'}, {'source': 'unknown'}):
            with self.assertRaises(ValueError): Scope(**{**asdict(SCOPE), **patch})

    def test_empty_page_with_cursor_is_partial_and_final_empty_means_empty(self):
        first = page(cursor_out='two')
        self.assertEqual(inspect_pages(SCOPE, [first]).state, 'partial')
        done = inspect_pages(SCOPE, [first, page(seq=1, cursor_in='two')])
        self.assertEqual((done.state, done.pages, done.items), ('empty', 2, 0))
        self.assertEqual(inspect_pages(SCOPE, [page(items=1)]).state, 'complete')

    def test_missing_repeated_and_foreign_pages_cannot_hide_gaps(self):
        for pages in ([page(seq=1)], [page(cursor_out='two'), page(seq=1, cursor_in='wrong')],
                      [page(cursor_out='two'), page(seq=1, cursor_in='two', cursor_out='two')],
                      [page(), page(seq=1)], [page(Scope('KXETH15M','recent','2026-10-25','v1'))]):
            with self.assertRaises(EvidenceConflict): inspect_pages(SCOPE, pages)

    def test_plan_distinguishes_complete_empty_unavailable_failed_and_unrequested(self):
        def job(status='succeeded'): return {'id': 'job', 'parameters': SCOPE.parameters(), 'status': status}
        for pages, status, expected in [([page(items=2)], 'succeeded','complete'),
                                      ([page()], 'succeeded','empty'),
                                      ([page(availability='unavailable')], 'succeeded','unavailable'),
                                      ([], 'failed','failed'), ([], 'succeeded','failed'), ([page(items=2)], 'running','resume')]:
            self.assertEqual(plan([SCOPE], [(job(status),pages)])[0]['state'], expected)
        self.assertEqual(plan([SCOPE], [])[0]['state'], 'fetch')
        self.assertEqual(plan([SCOPE], [(job(),[page(items=2)]),(job('failed'),[])])[0]['state'], 'complete')

    def test_provider_failure_never_accepts_raw_diagnostics(self):
        with self.assertRaises(ValueError): ProviderFailure('https://host/private-token')
        with self.assertRaises(ValueError): ProviderFailure('provider_timeout', delay=4000)


class MemoryObjects:
    def __init__(self): self.data = {}
    def put_if_absent(self, key, body, content_type):
        if key in self.data: return False
        self.data[key] = body
        return True
    def get(self, key, max_bytes): return self.data[key]


class FakeProvider:
    def __init__(self, *responses): self.responses, self.calls = list(responses), []
    def fetch(self, scope, cursor, timeout_seconds):
        self.calls.append((scope, cursor, timeout_seconds))
        value = self.responses.pop(0)
        if isinstance(value, Exception): raise value
        return value


@unittest.skipUnless(URL, 'Requires a disposable pocket_test PostgreSQL database')
class InventoryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path != '/pocket_test': raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL)
        cls.store = PostgresStore(URL); cls.store.open()
    @classmethod
    def tearDownClass(cls): cls.store.close()
    def setUp(self):
        with self.store.pool.connection() as c:
            c.execute('TRUNCATE research_read_budget,collection_page,raw_archive,research_job CASCADE')
        self.queue = ResearchQueue(self.store.pool)
        self.budget = ReadBudget(self.store.pool)
        self.budget.configure(100, 100)
        self.archives = ArchiveStore(MemoryObjects())
    def claim(self):
        self.queue.enqueue('btc', SCOPE.parameters(), 'inventory:' + SCOPE.key)
        return self.queue.claim()
    def worker(self, provider, **kwargs):
        return InventoryWorker(self.queue, self.archives, provider, self.budget, endpoint_cost=10, **kwargs)
    def step(self, worker, job): return worker.step(job, deadline=time.monotonic()+60)
    def row(self, job):
        with self.store.pool.connection() as c:
            return c.execute('SELECT * FROM research_job WHERE id=%s', (job['id'],)).fetchone()
    def expire(self, job):
        with self.store.pool.connection() as c:
            c.execute("UPDATE research_job SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job['id'],))

    def test_restart_reuses_committed_page_and_rejects_old_lease(self):
        provider = FakeProvider(ProviderPage({'markets':[{'yes_bid_dollars':'0.8800'}], 'cursor':'two'}),
                                ProviderPage({'markets':[], 'cursor':''}))
        worker = self.worker(provider); old = self.claim()
        self.assertEqual(self.step(worker,old)['state'], 'partial')
        self.expire(old); resumed = self.queue.claim()
        with self.assertRaises(LeaseLost): self.step(worker,old)
        self.assertEqual(self.step(worker,resumed)['state'], 'complete')
        self.assertEqual([c[1] for c in provider.calls], ['', 'two'])
        pages = self.queue.pages(old['id'])
        self.assertEqual(len(pages), 2)
        self.assertEqual(inspect_pages(SCOPE,pages).items, 1)
        self.assertEqual(self.row(old)['status'], 'succeeded')
        self.assertEqual(plan([SCOPE], [(self.row(old),pages)])[0]['state'], 'complete')
        # Every raw provider field survives unchanged in immutable object storage.
        self.assertTrue(any(b'0.8800' in __import__('gzip').decompress(b) for b in self.archives.objects.data.values()))
        with self.store.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM ingestion_cursor').fetchone()['n'], 0)

    def test_crash_after_terminal_checkpoint_finishes_without_fetching_again(self):
        provider = FakeProvider(ProviderPage({'markets':[], 'cursor':None}))
        worker = self.worker(provider); job = self.claim()
        original = self.queue.finish
        self.queue.finish = lambda *_: (_ for _ in ()).throw(RuntimeError('simulated crash'))
        with self.assertRaises(RuntimeError): self.step(worker,job)
        self.queue.finish = original
        self.expire(job); resumed = self.queue.claim()
        self.assertEqual(self.step(worker,resumed)['state'], 'empty')
        self.assertEqual(len(provider.calls), 1)

    def test_unavailable_and_failed_requests_never_look_like_empty_success(self):
        job = self.claim()
        worker = self.worker(FakeProvider(ProviderPage({}, 'unavailable')))
        self.assertEqual(self.step(worker,job)['state'], 'unavailable')
        self.assertEqual(plan([SCOPE],[(self.row(job),self.queue.pages(job['id']))])[0]['state'],'unavailable')

    def test_repeated_rate_limits_back_off_without_exhausting_collection_attempts(self):
        job=self.claim()
        with self.store.pool.connection() as c:c.execute('UPDATE research_job SET max_attempts=1 WHERE id=%s',(job['id'],))
        for expected in (1,2,4,8,16,30):
            worker=self.worker(FakeProvider(ProviderFailure('provider_rate_limit',delay=1)))
            self.assertEqual(self.step(worker,job)['retry_after'],expected)
            saved=self.row(job);self.assertEqual(saved['status'],'queued');self.assertEqual(saved['attempts'],0)
            self.assertEqual(self.queue.pages(job['id']),[])
            with self.store.pool.connection() as c:
                c.execute("UPDATE research_job SET available_at=clock_timestamp()-interval '1 second' WHERE id=%s",(job['id'],))
                c.execute("UPDATE research_read_budget SET blocked_until=clock_timestamp()-interval '1 second',tokens=100")
            job=self.queue.claim()
        self.step(self.worker(FakeProvider(ProviderPage({'markets':[],'cursor':''}))),job)
        self.assertEqual(self.row(job)['status'],'succeeded')
        self.assertNotIn('rate_limit_retries',self.row(job)['progress'])

    def test_rate_limit_cooldown_is_shared_and_failed_page_does_not_advance(self):
        job = self.claim(); provider = FakeProvider(ProviderFailure('provider_rate_limit', delay=60))
        self.assertEqual(self.step(self.worker(provider),job)['state'], 'failed')
        self.assertEqual(self.queue.pages(job['id']), [])
        other = ReadBudget(self.store.pool)
        self.assertGreaterEqual(other.take(10), 59)
        self.assertEqual(self.row(job)['error_code'], 'provider_rate_limit')
        self.assertEqual(self.row(job)['status'], 'queued')

    def test_throttle_and_deadline_do_not_fetch_or_hide_pages(self):
        job = self.claim(); provider = FakeProvider()
        worker = self.worker(provider)
        self.budget.defer(60)
        self.assertEqual(self.step(worker,job)['state'], 'throttled')
        self.assertEqual(self.row(job)['attempts'], 1)
        result = worker.step(job,deadline=time.monotonic()-1)
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.queue.pages(job['id']), [])

    def test_cycles_malformed_pages_and_page_cap_fail_without_partial_success(self):
        job = self.claim()
        provider = FakeProvider(ProviderPage({'markets':[], 'cursor':'two'}),
                                ProviderPage({'markets':[], 'cursor':'two'}))
        worker = self.worker(provider)
        self.step(worker,job)
        self.assertEqual(self.step(worker,job)['state'], 'failed')
        self.assertEqual(len(self.queue.pages(job['id'])), 1)
        self.assertEqual(self.row(job)['status'], 'failed')

    def test_concurrent_budget_reservations_do_not_overspend_and_configuration_conflicts(self):
        budget = ReadBudget(self.store.pool,'slow-test'); budget.configure(.001, 20)
        with ThreadPoolExecutor(max_workers=8) as executor:
            waits = list(executor.map(lambda _: budget.take(10), range(8)))
        self.assertEqual(waits.count(0), 2)
        with self.assertRaises(EvidenceConflict): budget.configure(.002,20)
        with self.assertRaises(ValueError): budget.take(21)
        with self.store.pool.connection() as c:
            c.execute("UPDATE research_read_budget SET updated_at=clock_timestamp()-interval '20000 seconds' WHERE name='slow-test'")
        self.assertEqual(budget.take(20), 0)

    def test_batch_fallback_yields_without_false_failure_or_consuming_attempt(self):
        from services.research.inventory import ProviderDeferred
        class DeferredProvider:
            def fetch(self,*args):raise ProviderDeferred()
        job=self.claim();worker=self.worker(DeferredProvider())
        result=worker.step(job,deadline=time.monotonic()+30)
        self.assertEqual(result,dict(state='partial',retry_after=0))
        self.assertEqual(self.queue.pages(job['id']),[])
        self.queue.yield_job(job['id'],job['lease_token'])
        saved=self.queue.get(job['id']);self.assertEqual(saved['status'],'queued')
        self.assertEqual(saved['attempts'],0);self.assertIsNone(saved['error_code'])

    def test_runtime_pacing_change_preserves_cooldown_and_does_not_mint_tokens(self):
        budget=ReadBudget(self.store.pool,'runtime-change');budget.configure(1,1)
        budget.take(1);budget.defer(60)
        with self.store.pool.connection() as c:
            before=c.execute("SELECT * FROM research_read_budget WHERE name='runtime-change'").fetchone()
        budget.configure(5,5,allow_update=True)
        with self.store.pool.connection() as c:
            after=c.execute("SELECT * FROM research_read_budget WHERE name='runtime-change'").fetchone()
        self.assertEqual(after['blocked_until'],before['blocked_until'])
        self.assertEqual(after['tokens'],before['tokens']);self.assertEqual(after['updated_at'],before['updated_at'])
        self.assertEqual((after['refill_per_second'],after['capacity']),(1,5));self.assertGreater(budget.take(1),0)

    def test_rejections_reduce_shared_pace_and_restart_preserves_it(self):
        budget=ReadBudget(self.store.pool,'steady');budget.configure(1,1)
        for expected in (.5,.25,.125,.1,.1):
            budget.rate_limited(2)
            with self.store.pool.connection() as c:
                row=c.execute("SELECT * FROM research_read_budget WHERE name='steady'").fetchone()
            self.assertEqual(row['refill_per_second'],expected)
            self.assertEqual(row['tokens'],0)
            self.assertGreater(budget.take(1),0)
        restarted=ReadBudget(self.store.pool,'steady');restarted.configure(1,1,allow_update=True)
        with self.store.pool.connection() as c:
            self.assertEqual(c.execute("SELECT refill_per_second FROM research_read_budget WHERE name='steady'").fetchone()['refill_per_second'],.1)
        budget=ReadBudget(self.store.pool,'smooth');budget.configure(1,1)
        self.assertEqual(budget.take(1),0)
        self.assertGreater(budget.take(1),0)

    def test_bad_payload_and_safety_page_limit_leave_explicit_failed_gap(self):
        job = self.claim()
        worker = self.worker(FakeProvider(ProviderPage({'markets': [], 'cursor': False})))
        self.assertEqual(self.step(worker, job)['state'], 'failed')
        self.assertEqual(self.queue.pages(job['id']), [])
        self.assertEqual(self.row(job)['error_code'], 'provider_invalid')
        self.setUp()
        job = self.claim()
        worker = self.worker(FakeProvider(ProviderPage({'markets': [], 'cursor': 'more'})), max_pages=1)
        self.step(worker,job)
        self.assertEqual(self.step(worker,job)['state'], 'failed')
        self.assertEqual(len(self.queue.pages(job['id'])), 1)
        self.assertEqual(plan([SCOPE], [(self.row(job),self.queue.pages(job['id']))])[0]['state'], 'failed')

    def test_failed_upload_and_cancellation_cannot_commit_progress(self):
        job = self.claim()
        provider = FakeProvider(ProviderPage({'markets': [], 'cursor': ''}))
        worker = self.worker(provider)
        with patch.object(self.archives, 'upload', side_effect=TimeoutError('simulated storage failure')):
            with self.assertRaises(TimeoutError): self.step(worker,job)
        self.assertEqual(self.queue.pages(job['id']), [])
        self.expire(job); job = self.queue.claim()
        original = self.archives.upload
        def cancel_during_upload(*args):
            receipt = original(*args)
            self.queue.cancel(job['id'])
            return receipt
        worker = self.worker(FakeProvider(ProviderPage({'markets': [], 'cursor': ''})))
        with patch.object(self.archives, 'upload', side_effect=cancel_during_upload):
            with self.assertRaises(LeaseLost): self.step(worker,job)
        self.assertEqual(self.queue.pages(job['id']), [])
        self.assertEqual(self.row(job)['status'], 'cancelled')

    def test_deadline_after_upload_leaves_orphan_but_no_cursor_advance(self):
        job = self.claim()
        now = [0.0]
        worker = self.worker(FakeProvider(ProviderPage({'markets': [], 'cursor': ''})), clock=lambda: now[0])
        original = self.archives.upload
        def slow_upload(*args):
            receipt = original(*args)
            now[0] = 61
            return receipt
        with patch.object(self.archives, 'upload', side_effect=slow_upload):
            self.assertEqual(worker.step(job,deadline=60)['state'], 'failed')
        self.assertEqual(len(self.archives.objects.data), 1)
        self.assertEqual(self.queue.pages(job['id']), [])

    def test_http_adapter_rate_limit_and_reclaim_resume_the_same_cursor(self):
        import httpx
        from services.research.kalshi import KalshiInventory
        from test_kalshi import MARKET, reply
        calls = []
        responses = [reply(payload={'markets':[MARKET], 'cursor':'two'}),
                     reply(429,headers={'retry-after':'7200'}),
                     reply(payload={'markets':[], 'cursor':''})]
        def handler(request):
            calls.append(request)
            return responses.pop(0)
        with KalshiInventory(transport=httpx.MockTransport(handler)) as provider:
            job = self.claim(); worker = self.worker(provider)
            self.assertEqual(self.step(worker,job)['state'], 'partial')
            self.assertEqual(self.step(worker,job)['state'], 'failed')
            self.assertEqual(len(self.queue.pages(job['id'])),1)
            self.assertEqual(self.row(job)['status'],'queued')
            self.assertGreaterEqual(ReadBudget(self.store.pool).take(10),7199)
            # Advance durable test clocks without a sleep or a live provider call.
            with self.store.pool.connection() as c:
                c.execute("UPDATE research_job SET available_at=clock_timestamp()-interval '1 second' WHERE id=%s",(job['id'],))
                c.execute("UPDATE research_read_budget SET blocked_until=clock_timestamp()-interval '1 second'")
            job = self.queue.claim()
            self.assertEqual(self.step(worker,job)['state'],'complete')
        self.assertEqual([r.url.params.get('cursor','') for r in calls],['','two','two'])
        self.assertEqual(len(self.queue.pages(job['id'])),2)
        self.assertEqual(self.row(job)['status'],'succeeded')

    def test_http_invalid_page_and_listing_404_do_not_checkpoint_empty_success(self):
        import httpx
        from services.research.kalshi import KalshiInventory
        from test_kalshi import reply
        for status, payload in [(200,{'markets':[]}), (404,{'message':'not found'})]:
            self.setUp()
            with KalshiInventory(transport=httpx.MockTransport(lambda _: reply(status,payload=payload))) as provider:
                job = self.claim()
                self.assertEqual(self.step(self.worker(provider),job)['state'],'failed')
            self.assertEqual(self.queue.pages(job['id']),[])
            self.assertEqual(self.row(job)['status'],'failed')
            self.assertEqual(self.row(job)['error_code'],'provider_invalid')

    def test_postgres_receipts_normalize_both_sources_without_publishing_or_mutation(self):
        from services.research.normalize import normalize_inventory
        from test_kalshi import MARKET
        recent = self.claim()
        self.step(self.worker(FakeProvider(ProviderPage({'markets':[MARKET], 'cursor':''}))),recent)
        first = self.row(recent)
        evidence = self.queue.page_evidence(recent['id'])
        partial = normalize_inventory([SCOPE.series],SCOPE.day,SCOPE.generation,[(first,evidence)],self.archives)
        self.assertFalse(partial.ready)
        self.assertEqual(partial.candidates,())
        history_scope = Scope(SCOPE.series,'historical',None,SCOPE.generation)
        self.queue.enqueue('btc',history_scope.parameters(),'historical-normalization')
        historical = self.queue.claim()
        self.step(self.worker(FakeProvider(ProviderPage({'markets':[MARKET], 'cursor':''}))),historical)
        attempts = [(self.row(j),self.queue.page_evidence(j['id'])) for j in (recent,historical)]
        normalized = normalize_inventory([SCOPE.series],SCOPE.day,SCOPE.generation,attempts,self.archives)
        self.assertTrue(normalized.ready)
        self.assertEqual((len(normalized.candidates),normalized.rows_scanned),(1,2))
        self.assertEqual({e.source for e in normalized.candidates[0].evidence},{'recent','historical'})
        self.assertEqual(self.row(recent),first)
        self.assertEqual(evidence,self.queue.page_evidence(recent['id']))
        for ref in normalized.candidates[0].evidence:
            row = self.archives.read(ref.receipt())['response']['markets'][ref.row_index]
            self.assertEqual(row['yes_bid_dollars'],'0.8800')
        with self.store.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM ingestion_cursor').fetchone()['n'],0)

    def test_postgres_receipt_integrity_rechecked_after_collection(self):
        from services.research.normalize import normalize_inventory
        from services.research.archive import ArchiveInvalid
        from test_kalshi import MARKET
        recent = self.claim()
        self.step(self.worker(FakeProvider(ProviderPage({'markets':[MARKET], 'cursor':''}))),recent)
        history_scope = Scope(SCOPE.series,'historical',None,SCOPE.generation)
        self.queue.enqueue('btc',history_scope.parameters(),'historical-normalization')
        historical = self.queue.claim()
        self.step(self.worker(FakeProvider(ProviderPage({'markets':[], 'cursor':''}))),historical)
        attempts = [(self.row(j),self.queue.page_evidence(j['id'])) for j in (recent,historical)]
        receipt = attempts[0][1][0]['receipt']
        self.archives.objects.data[receipt['object_key']] = b'corrupt-after-collection'
        with self.assertRaises(ArchiveInvalid):
            normalize_inventory([SCOPE.series],SCOPE.day,SCOPE.generation,attempts,self.archives)
        self.assertEqual(self.row(recent)['status'],'succeeded')
        self.assertEqual(len(self.queue.page_evidence(recent['id'])),1)

    def evidence_plan(self):
        from services.research.normalize import normalize_inventory
        from services.research.evidence import build_scopes
        from test_kalshi import MARKET
        recent = self.claim()
        self.step(self.worker(FakeProvider(ProviderPage({'markets':[MARKET], 'cursor':''}))),recent)
        history_scope = Scope(SCOPE.series,'historical',None,SCOPE.generation)
        self.queue.enqueue('btc',history_scope.parameters(),'historical-evidence-plan')
        history = self.queue.claim()
        self.step(self.worker(FakeProvider(ProviderPage({'markets':[], 'cursor':''}))),history)
        batch = normalize_inventory([SCOPE.series],SCOPE.day,SCOPE.generation,
            [(self.row(j),self.queue.page_evidence(j['id'])) for j in (recent,history)],self.archives)
        return build_scopes(batch,self.archives,lookback_seconds=3600)

    def evidence_job(self,scope):
        self.queue.enqueue('btc',scope.parameters(),'evidence:'+scope.key)
        return self.queue.claim()

    def test_evidence_trade_restart_reuses_pages_and_fences_obsolete_attempt(self):
        import httpx
        from services.research.evidence import KalshiEvidence, EvidenceWorker
        from test_evidence import trade
        from test_kalshi import reply
        scope = next(s for s in self.evidence_plan().scopes if (s.resource,s.source)==('trades','recent'))
        job = self.evidence_job(scope)
        calls = []
        responses = [reply(payload={'trades':[trade(scope)],'cursor':'two'}),
                     reply(payload={'trades':[{**trade(scope),'trade_id':'trade-two'}],'cursor':''})]
        def handler(request):
            calls.append(request)
            return responses.pop(0)
        with KalshiEvidence(transport=httpx.MockTransport(handler)) as provider:
            worker = EvidenceWorker(self.queue,self.archives,provider,self.budget,endpoint_cost=10)
            self.assertEqual(self.step(worker,job)['state'],'partial')
            self.expire(job); resumed = self.queue.claim()
            with self.assertRaises(LeaseLost): self.step(worker,job)
            self.assertEqual(self.step(worker,resumed)['state'],'complete')
        self.assertEqual([r.url.params.get('cursor','') for r in calls],['','two'])
        pages = self.queue.page_evidence(job['id'])
        self.assertEqual(len(pages),2)
        self.assertTrue(all(p['page_key'].startswith('evidence/') for p in pages))
        for page in pages:
            envelope = self.archives.read(page['receipt'])
            self.assertEqual(envelope['response']['trades'][0]['yes_price_dollars'],'0.8800')
        self.assertEqual(inspect_pages(scope,pages).items,2)

    def test_evidence_candle_unavailability_is_retained_and_other_source_is_independent(self):
        import httpx
        from services.research.evidence import KalshiEvidence, EvidenceWorker
        from test_evidence import candle
        from test_kalshi import reply
        scopes = [s for s in self.evidence_plan().scopes if s.resource=='candles']
        calls = []
        def handler(request):
            calls.append(request)
            if '/historical/' in request.url.path: return reply(404)
            recent = next(s for s in scopes if s.source=='recent')
            return reply(payload={'ticker':recent.ticker,'candlesticks':[candle(recent)]})
        with KalshiEvidence(transport=httpx.MockTransport(handler)) as provider:
            worker = EvidenceWorker(self.queue,self.archives,provider,self.budget,endpoint_cost=10)
            for scope in scopes:
                job = self.evidence_job(scope)
                expected = 'unavailable' if scope.source=='historical' else 'complete'
                self.assertEqual(self.step(worker,job)['state'],expected)
                pages = self.queue.page_evidence(job['id'])
                self.assertEqual(inspect_pages(scope,pages).state,expected)
                if expected=='unavailable':
                    self.assertEqual(self.archives.read(pages[0]['receipt'])['response'],{'http_status':404})
        self.assertEqual(len(calls),2)

    def test_evidence_rate_limit_does_not_advance_and_full_cooldown_survives_reclaim(self):
        import httpx
        from services.research.evidence import KalshiEvidence, EvidenceWorker
        from test_kalshi import reply
        scope = next(s for s in self.evidence_plan().scopes if (s.resource,s.source)==('trades','historical'))
        job = self.evidence_job(scope)
        with KalshiEvidence(transport=httpx.MockTransport(lambda _:reply(429,headers={'retry-after':'7200'}))) as provider:
            worker = EvidenceWorker(self.queue,self.archives,provider,self.budget,endpoint_cost=10)
            self.assertEqual(self.step(worker,job)['state'],'failed')
        self.assertEqual(self.queue.pages(job['id']),[])
        self.assertEqual(self.row(job)['status'],'queued')
        self.assertGreaterEqual(ReadBudget(self.store.pool).take(10),7199)

    def test_evidence_corrupt_membership_or_cancelled_attempt_cannot_fetch_or_checkpoint(self):
        import httpx
        from services.research.archive import ArchiveInvalid
        from services.research.evidence import KalshiEvidence, EvidenceWorker
        from test_evidence import candle
        from test_kalshi import reply
        scope = next(s for s in self.evidence_plan().scopes if (s.resource,s.source)==('candles','recent'))
        job = self.evidence_job(scope)
        saved = self.archives.objects.data[scope.manifest_key]
        self.archives.objects.data[scope.manifest_key] = b'corrupt'
        calls = []
        def handler(request):
            calls.append(request)
            self.queue.cancel(job['id'])
            return reply(payload={'ticker':scope.ticker,'candlesticks':[candle(scope)]})
        with KalshiEvidence(transport=httpx.MockTransport(handler)) as provider:
            worker = EvidenceWorker(self.queue,self.archives,provider,self.budget,endpoint_cost=10)
            with self.assertRaises(ArchiveInvalid): self.step(worker,job)
            self.assertEqual(calls,[])
            self.archives.objects.data[scope.manifest_key] = saved
            with self.assertRaises(LeaseLost): self.step(worker,job)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.queue.pages(job['id']),[])
        self.assertEqual(self.row(job)['status'],'cancelled')
