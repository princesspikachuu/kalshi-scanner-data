"""Status sections preserve exact views and avoid cold-document rewrites."""
import copy
import os
import shutil
import unittest
from unittest.mock import Mock, patch

from services.paper_demo.shadow import status_sections as sections
from services.paper_demo.shadow.checkpoint_codec import pack_checkpoint
from services.paper_demo.shadow.storage import HostedAudit


def status(at=1):
    return dict(at=at, accounting=dict(cash='1000.0001'), orders=[], positions=[],
                experiments=dict(scalper=dict(bots=dict(one=dict(scalper=dict(
                    research=[dict(price=str(i), outcome=i%2) for i in range(3000)]),
                    net_realized_pnl='1.0002')))))


def stored(parts):
    return {sections.ROOT+'-section/'+s: v['payload'] for s, v in parts.items()}


class StatusSectionsTests(unittest.TestCase):
    def test_exact_roundtrip_and_small_hot_document(self):
        data = status(); original = copy.deepcopy(data)
        hot, parts = sections.prepare(data)
        self.assertEqual(set(parts), {'scalper'})
        self.assertEqual(sections.restore(hot, stored(parts)), data)
        self.assertEqual(data, original)
        self.assertLess(len(str(hot)), len(str(data))/10)
        later, unchanged = sections.prepare(status(2))
        self.assertEqual(unchanged, parts)
        self.assertNotEqual(later, hot)

    def test_legacy_and_small_status_and_corruption_fail_closed(self):
        data = dict(at=1, positions=[dict(quantity='2.87')])
        self.assertEqual(sections.restore(data, {}), data)
        self.assertEqual(sections.restore(pack_checkpoint(data, threshold=0), {}), data)
        self.assertEqual(sections.prepare(data)[1], {})
        hot, parts = sections.prepare(status())
        with self.assertRaises(KeyError):
            sections.restore(hot, {})
        bad = copy.deepcopy(hot); bad['sections'][0]['sha256'] = '0'*64
        with self.assertRaises(ValueError):
            sections.restore(bad, stored(parts))
        bad = copy.deepcopy(hot); bad['sections'] *= 2
        with self.assertRaises(ValueError):
            sections.restore(bad, stored(parts))


URL = os.environ.get('POCKET_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'Disposable PostgreSQL required')
class StatusSectionsDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from urllib.parse import urlsplit
        from services.api.manage import migrate
        from services.api.store import PostgresStore
        from services.demo.store import DemoStore
        if urlsplit(URL).path != '/pocket_test':
            raise RuntimeError('Use disposable pocket_test only')
        migrate(URL)
        cls.store = PostgresStore(URL); cls.store.open()
        cls.demo = DemoStore(cls.store.pool)

    @classmethod
    def tearDownClass(cls):
        cls.store.close()

    def setUp(self):
        with self.store.pool.connection() as c:
            c.execute('DELETE FROM research_job WHERE idempotency_key=ANY(%s::text[])', (list(sections.KEYS),))
        self.audit = HostedAudit(self.demo, lambda: None)
        self.addCleanup(shutil.rmtree, self.audit.path)
        self.flag = patch.dict(os.environ, MT_SHADOW_SPLIT_STATUS_ENABLED='true')
        self.flag.start(); self.addCleanup(self.flag.stop)

    def fingerprints(self):
        with self.store.pool.connection() as c:
            return {r['idempotency_key']:r['version'] for r in c.execute(
                "SELECT idempotency_key,xmin::text AS version FROM research_job WHERE idempotency_key=ANY(%s::text[])",
                (list(sections.KEYS),)).fetchall()}

    def test_cold_rows_unchanged_while_hot_status_and_money_update(self):
        first = status()
        self.audit.publish_status(first)
        self.assertEqual(self.demo.get('shadow/status')['progress'], first)
        before = self.fingerprints()
        next_status = status(2); next_status['accounting']['cash'] = '999.1234'
        # A new publisher must use live DB digests, not an in-memory cache.
        second = HostedAudit(self.demo, lambda: None)
        self.addCleanup(shutil.rmtree, second.path)
        second.publish_status(next_status)
        after = self.fingerprints()
        self.assertEqual(self.demo.get('shadow/status')['progress'], next_status)
        self.assertEqual(before[sections.KEYS[1]], after[sections.KEYS[1]])
        self.assertNotEqual(before[sections.ROOT], after[sections.ROOT])
        next_status['experiments']['scalper']['bots']['one']['scalper']['research'][0]['outcome'] = 3
        second.publish_status(next_status)
        self.assertNotEqual(after[sections.KEYS[1]], self.fingerprints()[sections.KEYS[1]])
        self.assertEqual(self.demo.get('shadow/status')['progress'], next_status)
        # Switching off the feature keeps old stored sections bounded/reusable.
        with patch.dict(os.environ, MT_SHADOW_SPLIT_STATUS_ENABLED='false'):
            second.publish_status(first)
        self.assertEqual(self.demo.get('shadow/status')['progress'], first)
        self.assertLessEqual(len(self.fingerprints()), 5)

    def test_failed_publication_rolls_back_sections_and_hot_document(self):
        self.audit.publish_status(status())
        before = self.fingerprints()
        changed = status(2)
        changed['experiments']['scalper']['bots']['one']['scalper']['research'][0]['outcome'] = 3
        from services.paper_demo.shadow import storage
        original = storage.put
        def fail_main(c, key, parameters, progress):
            if key == sections.ROOT:
                raise RuntimeError('simulated publication failure')
            return original(c, key, parameters, progress)
        with patch.object(storage, 'put', side_effect=fail_main), self.assertRaises(RuntimeError):
            self.audit.publish_status(changed)
        self.assertEqual(before, self.fingerprints())
        self.assertEqual(self.demo.get('shadow/status')['progress'], status())
