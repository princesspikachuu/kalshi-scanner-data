"""Empty namespace probes must not scan unrelated history or hide outliers."""
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from services.demo import shadow_prefix_boundary_guard as guard
from services.demo.shadow_history_pages import PACKED_PREFIX
from services.api.tests import test_demo_postgres as fixture


class RetentionBoundaryTests(unittest.TestCase):
    def connection(self, locale='en_US.UTF8', provider='c', found=None):
        c=MagicMock()
        def execute(query,args=None):
            result=MagicMock()
            result.fetchone.return_value = dict(locale=locale,provider=provider) if query==guard.KEY_COLLATION_SQL else found
            return result
        c.execute.side_effect=execute
        return c

    def test_empty_probe_bounds_both_sides_after_verifying_column_collation(self):
        c=self.connection()
        guard.assert_no_hidden_prefix_keys(c,[PACKED_PREFIX],bounded=True)
        self.assertEqual(c.execute.call_count,3)
        self.assertEqual(c.execute.call_args.args,(guard.BOUNDED_ABOVE_UPPER_SQL,
            (PACKED_PREFIX+'zzzz','demo/shadow/event-batci',PACKED_PREFIX+'%')))

    def test_unknown_and_icu_collations_fail_before_namespace_probe(self):
        for locale,provider in (('en_US.UTF8','i'),('cs_CZ.UTF8','c'),('','d'),('unknown','b')):
            c=self.connection(locale,provider)
            with self.subTest(locale=locale,provider=provider),self.assertRaises(ValueError):
                guard.assert_no_hidden_prefix_keys(c,[PACKED_PREFIX],bounded=True)
            self.assertEqual(c.execute.call_count,1)

    def test_byte_collations_are_supported(self):
        for locale,provider in (('C','c'),('C.UTF-8','b'),('POSIX','c')):
            with self.subTest(locale=locale):
                self.assertTrue(guard.assert_no_hidden_prefix_keys(
                    self.connection(locale,provider),[PACKED_PREFIX],bounded=True))

    def test_bare_prefix_still_rejected(self):
        c=self.connection(found=dict(present=1))
        with self.assertRaisesRegex(ValueError,'Bare index prefix'):
            guard.assert_no_hidden_prefix_keys(c,[PACKED_PREFIX],bounded=True)
        self.assertEqual(c.execute.call_count,2)

    def test_upper_outlier_still_rejected(self):
        c=self.connection()
        c.execute.side_effect=[MagicMock(fetchone=lambda:dict(locale='en_US.UTF8',provider='c')),
                              MagicMock(fetchone=lambda:None),MagicMock(fetchone=lambda:dict(present=1))]
        with self.assertRaisesRegex(ValueError,'Out-of-range'):
            guard.assert_no_hidden_prefix_keys(c,[PACKED_PREFIX],bounded=True)


@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL pocket_test required')
class RealRetentionBoundary(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_each_namespace_retains_detection_of_high_and_unicode_suffixes(self):
        # The new upper fence must not turn a previously detected malformed
        # key into a successful namespace-completion claim.
        from psycopg.types.json import Jsonb
        for prefix in guard.ALLOWED_PREFIXES:
            for suffix in ('zzzz','zzzzzzzz','zzzz\uffff','zzzz\U0010ffff'):
                key=prefix+suffix
                with self.subTest(prefix=prefix,suffix=suffix):
                    with self.store.pool.connection() as c:
                        c.execute("INSERT INTO research_job (id,asset,parameters,progress,idempotency_key,status) VALUES (%s,'crypto',%s,%s,%s,'succeeded')",
                                  (uuid4(),Jsonb({}),Jsonb({}),key))
                    try:
                        with self.store.pool.connection() as c:
                            with c.transaction():
                                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                                with self.assertRaisesRegex(ValueError,'Out-of-range'):
                                    guard.assert_no_hidden_prefix_keys(c,[prefix],bounded=True)
                    finally:
                        with self.store.pool.connection() as c:
                            c.execute('DELETE FROM research_job WHERE idempotency_key=%s',(key,))

    def test_empty_packed_namespace_does_not_report_other_namespace_as_hidden(self):
        with self.store.pool.connection() as c:
            with c.transaction():
                c.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                self.assertTrue(guard.assert_no_hidden_prefix_keys(c,[PACKED_PREFIX],bounded=True))
