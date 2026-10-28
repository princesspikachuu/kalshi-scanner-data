"""Exact cross-campaign reads retain independently fenced immutable evidence."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.archive import ArchiveStore, ArchiveInvalid
from services.research.budget import ReadBudget
from services.research.campaigns import CampaignStore
from services.research.evidence import build_scopes
from services.research.inventory import InventoryWorker, ProviderPage, Scope, page_key
from services.research.normalize import _payload
from services.research.projections import archive_evidence, resolve_evidence
from services.research.queue import EvidenceConflict, ResearchQueue
from services.research.reuse import VerifiedReads
from services.research.weather_calendar import snapshot as weather_snapshot
from test_evidence import BATCH, CANDIDATE, candle
from test_normalize import MemoryObjects
from test_shared_projections import batch_response, checkpoint

URL = os.environ.get('POCKET_TEST_DATABASE_URL')
UTC = timezone.utc


class WeatherCalendarTests(unittest.TestCase):
    def test_exact_series_snapshot_expires_and_unknown_series_gets_no_calendar(self):
        weather = Scope('KXTEMPLAH', 'recent', '2025-12-01', 'generation')
        first = weather_snapshot(weather, datetime(2026, 10, 27, 23, 59, tzinfo=UTC))
        later = weather_snapshot(weather, datetime(2026, 10, 28, 0, 1, tzinfo=UTC))
        self.assertEqual(first['expires_utc'], later['snapshot_utc'])
        self.assertNotEqual(first, later)
        self.assertIsNone(weather_snapshot(replace(weather, series='UNKNOWN'), datetime.now(UTC)))


@unittest.skipUnless(URL, 'Requires disposable pocket_test PostgreSQL')
class VerifiedReadPostgresTests(unittest.TestCase):
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
        with self.db.pool.connection() as c:
            c.execute('TRUNCATE research_refresh,research_job,research_dataset,research_result,research_artifact,research_read_budget CASCADE')
        self.archives = ArchiveStore(MemoryObjects(), cache_bytes=1024 * 1024)
        self.queue = ResearchQueue(self.db.pool)
        self.store = CampaignStore(self.db.pool)
        self.reuse = VerifiedReads(self.db.pool, self.archives)
        self.budget = ReadBudget(self.db.pool)
        self.budget.configure(100, 100)
        self.day = (datetime.now(UTC).date() - timedelta(days=2)).isoformat()

    def attach(self, asset, name, scope, *, refresh=False, rolling=False):
        now = datetime.now(UTC)
        if rolling:
            start = datetime.fromisoformat(self.day).replace(tzinfo=UTC)
            with self.db.pool.connection() as c:
                identifier = self.store._create(c, asset, start, start + timedelta(days=1), name, 'rolling', {'day': self.day})
        else:
            identifier = self.store.create(asset, self.day, self.day, name, now=now, refresh_existing=refresh)
        job = self.queue.enqueue(asset, scope.parameters(), name + '/read')
        with self.db.pool.connection() as c:
            c.execute('INSERT INTO research_campaign_work(campaign_id,day,phase,job_id) VALUES(%s,%s,%s,%s)',
                      (identifier, self.day, 'evidence' if hasattr(scope, 'resource') else 'inventory', job['id']))
        return job

    def test_exact_read_reused_after_restart_with_new_scope_and_its_own_checkpoint(self):
        source = Scope('KXBTC15M', 'recent', self.day, 'first-generation')
        target = replace(source, generation='second-generation')
        first = self.attach('btc', 'source-exact', source)
        provider = Mock()
        provider.cached.return_value = None
        provider.fetch.return_value = ProviderPage({'markets': [], 'cursor': ''})
        worker = InventoryWorker(self.queue, self.archives, provider, self.budget, endpoint_cost=1)
        worker.reuse = self.reuse
        self.assertEqual(worker.step(self.queue.claim(job_id=first['id']), deadline=time.monotonic() + 30)['state'], 'empty')
        self.assertEqual(provider.fetch.call_count, 1)
        second = self.attach('crypto', 'target-exact', target)
        restarted = ArchiveStore(self.archives.objects, cache_bytes=1024 * 1024)
        provider2 = Mock()
        provider2.cached.return_value = None
        provider2.fetch.side_effect = AssertionError('Exact verified request must be reused')
        worker2 = InventoryWorker(self.queue, restarted, provider2, self.budget, endpoint_cost=1)
        worker2.reuse = VerifiedReads(self.db.pool, restarted)
        self.assertEqual(worker2.step(self.queue.claim(job_id=second['id']), deadline=time.monotonic() + 30)['state'], 'empty')
        provider2.fetch.assert_not_called()
        pages1, pages2 = self.queue.page_evidence(first['id']), self.queue.page_evidence(second['id'])
        self.assertEqual(pages1[0]['object_key'], pages2[0]['object_key'])
        self.assertNotEqual(pages1[0]['page_key'], pages2[0]['page_key'])
        self.assertEqual(pages2[0]['checkpoint']['projection']['format'], 'provider-page-reference-v1')
        self.assertEqual(_payload(target, pages2[0], restarted), [])
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM raw_archive').fetchone()['n'], 1)
            self.assertEqual(c.execute('SELECT count(*) AS n FROM collection_page').fetchone()['n'], 2)

    def test_refresh_rolling_and_current_day_never_read_stale_index(self):
        scope = Scope('KXBTC15M', 'recent', self.day, 'old')
        source = self.attach('btc', 'safety-source', scope)
        response = ProviderPage({'markets': [], 'cursor': ''})
        provider = Mock(fetch=Mock(return_value=response))
        provider.cached.return_value = None
        worker = InventoryWorker(self.queue, self.archives, provider, self.budget, endpoint_cost=1)
        worker.reuse = self.reuse
        worker.step(self.queue.claim(job_id=source['id']), deadline=time.monotonic() + 30)
        for name, kwargs in [('explicit-refresh', {'refresh': True}), ('rolling', {'rolling': True})]:
            job = self.attach('crypto', name, replace(scope, generation=name), **kwargs)
            self.assertIsNone(self.reuse.lookup(job, replace(scope, generation=name), ''))
        today = datetime.now(UTC).date().isoformat()
        current = Scope('KXBTC15M', 'recent', today, 'current')
        identifier = self.store.create('btc', today, today, 'current-day', now=datetime.now(UTC))
        job = self.queue.enqueue('btc', current.parameters(), 'current-day/read')
        with self.db.pool.connection() as c:
            c.execute('INSERT INTO research_campaign_work(campaign_id,day,phase,job_id) VALUES(%s,%s,%s,%s)',
                      (identifier, today, 'inventory', job['id']))
        self.assertIsNone(self.reuse.lookup(job, current, ''))

    def test_corrupt_or_mismatched_reuse_cannot_checkpoint(self):
        source = Scope('KXBTC15M', 'recent', self.day, 'source')
        first = self.attach('btc', 'integrity-source', source)
        provider = Mock()
        provider.cached.return_value = None
        provider.fetch.return_value = ProviderPage({'markets': [], 'cursor': ''})
        worker = InventoryWorker(self.queue, self.archives, provider, self.budget, endpoint_cost=1)
        worker.reuse = self.reuse
        worker.step(self.queue.claim(job_id=first['id']), deadline=time.monotonic() + 30)
        target = replace(source, generation='target')
        second = self.attach('crypto', 'integrity-target', target)
        receipt = self.queue.page_evidence(first['id'])[0]['receipt']
        body = self.archives.objects.data[receipt['object_key']]
        self.archives.objects.data[receipt['object_key']] = b'corrupt'
        fresh = ArchiveStore(self.archives.objects)
        with self.assertRaises(ArchiveInvalid):
            VerifiedReads(self.db.pool, fresh).lookup(second, target, '')
        self.archives.objects.data[receipt['object_key']] = body
        # A valid receipt for an unrelated request cannot satisfy the index.
        other = Scope('KXETH15M', 'recent', self.day, 'other')
        unrelated = self.archives.upload('kalshi', {'scope': other.__dict__,
            'checkpoint': {**self.queue.page_evidence(first['id'])[0]['checkpoint'], 'scope': other.key},
            'response': {'markets': [], 'cursor': ''}})
        with self.db.pool.connection() as c:
            c.execute("UPDATE research_job SET progress=jsonb_set(progress,'{receipt}',%s::jsonb) WHERE idempotency_key=%s",
                      (self._json(unrelated), self.reuse._key(second, target, '')[0]))
        with self.assertRaises(EvidenceConflict):
            VerifiedReads(self.db.pool, ArchiveStore(self.archives.objects)).lookup(second, target, '')
        self.assertEqual(self.queue.pages(second['id']), [])

    @staticmethod
    def _json(value):
        import json
        return json.dumps(value)

    def test_reused_batch_retains_original_entry_and_row_selectors(self):
        candidate = replace(CANDIDATE, ticker='KXBTC15M-REUSED', event_ticker='REUSED-E')
        plan = build_scopes(replace(BATCH, candidates=(candidate,)), self.archives,
                            lookback_seconds=1020, resources=('candles',))
        source = next(s for s in plan.scopes if s.source == 'recent')
        target = replace(source, candidate_key='a' * 64)
        first = self.attach('btc', 'batch-reuse-source', source)
        _, receipt, responses = batch_response(self.archives, [source], extra_bars=True)
        archived, cp = archive_evidence(source, checkpoint(source, 1), responses[source.key], self.archives)
        self.assertEqual(archived, receipt)
        claimed = self.queue.claim(job_id=first['id'])
        self.queue.checkpoint(first['id'], claimed['lease_token'], page_key(source, 0), receipt, cp)
        self.queue.finish(first['id'], claimed['lease_token'])
        self.reuse.remember(first, source, cp, receipt)
        second = self.attach('crypto', 'batch-reuse-target', target)
        reconstructed = VerifiedReads(self.db.pool, ArchiveStore(self.archives.objects))
        reused = reconstructed.lookup(second, target, '')
        self.assertEqual(reused.origin_receipt, receipt)
        archived2, cp2 = archive_evidence(target, checkpoint(target, 1), reused, reconstructed.archives)
        page = dict(page_key=page_key(target, 0), object_key=archived2['object_key'],
                    receipt=archived2, checkpoint=cp2)
        rows, cursor, selectors = resolve_evidence(target, page, reconstructed.archives)
        self.assertEqual(rows, [candle(source)])
        self.assertEqual(cursor, '')
        self.assertEqual(selectors, [{'format': 'candle-batch-projection-v1', 'entry_index': 0, 'row_index': 1}])

    def test_weather_calendar_reuses_only_exact_verified_request_until_next_snapshot(self):
        first = datetime(2026, 10, 27, 12, tzinfo=UTC)
        next_day = first + timedelta(days=1)
        scope = Scope('KXTEMPLAH', 'recent', self.day, 'weather-one')
        source = self.attach('weather', 'calendar-source', scope)
        provider = Mock()
        provider.cached.return_value = None
        provider.fetch.return_value = ProviderPage({'markets': [], 'cursor': ''})
        worker = InventoryWorker(self.queue, self.archives, provider, self.budget, endpoint_cost=1)
        worker.reuse = self.reuse
        with patch('services.research.reuse.weather_snapshot', side_effect=lambda s: weather_snapshot(s, first)):
            worker.step(self.queue.claim(job_id=source['id']), deadline=time.monotonic() + 30)
            target_scope = replace(scope, generation='weather-two')
            target = self.attach('weather', 'calendar-target', target_scope)
            self.assertIsNotNone(self.reuse.lookup(target, target_scope, ''))
            self.assertIsNone(self.reuse.lookup(target, replace(target_scope, day=(datetime.fromisoformat(self.day).date() - timedelta(days=1)).isoformat()), ''))
            self.assertIsNone(self.reuse.lookup(target, replace(target_scope, series='KXTEMPMIAH'), ''))
        with patch('services.research.reuse.weather_snapshot', side_effect=lambda s: weather_snapshot(s, next_day)):
            self.assertIsNone(self.reuse.lookup(target, target_scope, ''))
        self.assertEqual(provider.fetch.call_count, 1)
