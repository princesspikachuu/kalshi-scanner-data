"""Draft strategy definitions and immutable version storage, never execution."""
from copy import deepcopy
import os
import unittest
from urllib.parse import urlsplit

import psycopg

from services.api.manage import migrate
from services.api.store import PostgresStore
from services.strategies.definitions import BANDS,VERSION,validate,fingerprint
from services.strategies.store import DraftStore,VersionConflict

URL=os.environ.get('POCKET_TEST_DATABASE_URL')


def rules():
    return dict(version=VERSION,asset='btc',series=['KXBTC15M'],
        entry=dict(minutes_before_close=15,side='yes',max_bid_cents=85,maker_offset_cents=1,
                   contracts=2,wait_seconds=15,replace_limit=1),
        exit=dict(loss_reduction_enabled=False,decision_minutes_before_close=5,
                  thresholds_cents={band:None for band in BANDS},research_result_id=None),
        limits=dict(per_trade_cents=170,category_open_cents=500,strategy_open_cents=500,
                    global_open_cents=1000,daily_spend_cents=1000))


class DefinitionTests(unittest.TestCase):
    def test_exact_units_canonical_series_and_fingerprint(self):
        original=rules();canonical=validate(original)
        self.assertEqual(canonical,original)
        self.assertEqual(fingerprint(canonical),fingerprint(original))
        self.assertEqual(len(fingerprint(canonical)),64)
        self.assertIsNot(canonical['entry'],original['entry'])

    def test_exit_threshold_requires_provenance_and_preserves_hold_option(self):
        choice=rules();choice['exit']['loss_reduction_enabled']=True
        choice['exit']['thresholds_cents']['80-90']=70
        choice['exit']['research_result_id']=42
        self.assertEqual(validate(choice)['exit']['thresholds_cents']['80-90'],70)
        self.assertNotEqual(fingerprint(choice),fingerprint(rules()))
        for change in (lambda x:x['exit'].update(research_result_id=None),
                       lambda x:x['exit']['thresholds_cents'].update({'80-90':91}),
                       lambda x:x['exit'].update(decision_minutes_before_close=15)):
            invalid=deepcopy(choice);change(invalid)
            with self.assertRaises(ValueError):validate(invalid)

    def test_rejects_float_boolean_units_extras_and_limits_below_order_size(self):
        alterations=(lambda x:x['entry'].update(max_bid_cents=85.0),
            lambda x:x['entry'].update(contracts=True),
            lambda x:x['limits'].update(per_trade_cents=169),
            lambda x:x['limits'].update(global_open_cents=100),
            lambda x:x['entry'].update(side='auto'),
            lambda x:x['entry'].update(extra=1),
            lambda x:x.update(asset='financial_daily'),
            lambda x:x.update(asset=[]),
            lambda x:x.update(series=['KXETH15M']),
            lambda x:x['exit']['thresholds_cents'].update({'90-100':50}))
        for change in alterations:
            invalid=rules();change(invalid)
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):validate(invalid)


@unittest.skipUnless(URL,'Requires disposable pocket_test PostgreSQL')
class DraftPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path!='/pocket_test':raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL);cls.db=PostgresStore(URL);cls.db.open()
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def setUp(self):
        with self.db.pool.connection() as c:c.execute('TRUNCATE strategy_version,strategy_draft CASCADE')
        self.store=DraftStore(self.db.pool)

    def test_create_revise_and_read_old_fingerprint_without_activation(self):
        first=rules();identifier=self.store.create('Morning BTC',first)
        saved=self.store.get(identifier)
        self.assertEqual((saved['state'],saved['revision'],saved['current_revision']),('draft',1,1))
        self.assertEqual(saved['fingerprint'],fingerprint(first))
        revised=rules();revised['entry']['max_bid_cents']=80
        self.assertEqual(self.store.revise(identifier,1,revised),2)
        self.assertEqual(self.store.get(identifier,1)['fingerprint'],fingerprint(first))
        self.assertEqual(self.store.get(identifier)['fingerprint'],fingerprint(revised))
        with self.assertRaises(VersionConflict):self.store.revise(identifier,1,revised)
        with self.db.pool.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) AS n FROM strategy_version').fetchone()['n'],2)

    def test_database_blocks_version_mutation_and_unversioned_pointer_or_state(self):
        identifier=self.store.create('BTC draft',rules())
        for statement in ('UPDATE strategy_version SET fingerprint=%s WHERE strategy_id=%s',
                          'DELETE FROM strategy_version WHERE strategy_id=%s',
                          'UPDATE strategy_draft SET state=%s WHERE id=%s',
                          'UPDATE strategy_draft SET current_revision=3 WHERE id=%s'):
            args=('0'*64,identifier) if statement.startswith('UPDATE strategy_version') else \
                 ('paper',identifier) if 'SET state' in statement else (identifier,)
            with self.subTest(statement=statement),self.assertRaises(psycopg.Error):
                with self.db.pool.connection() as c:c.execute(statement,args)
        self.assertEqual(self.store.get(identifier)['current_revision'],1)

    def test_database_rejects_out_of_order_or_foreign_version_insert(self):
        identifier=self.store.create('BTC draft',rules())
        for revision,asset in ((3,'btc'),(2,'eth')):
            invalid=rules();invalid['asset']=asset
            with self.subTest(revision=revision,asset=asset),self.assertRaises(psycopg.Error):
                with self.db.pool.connection() as c:
                    c.execute('INSERT INTO strategy_version(strategy_id,revision,definition,fingerprint) VALUES(%s,%s,%s,%s)',
                              (identifier,revision,psycopg.types.json.Jsonb(invalid),'0'*64))

    def test_stale_write_never_appends_a_version(self):
        identifier=self.store.create('BTC draft',rules())
        second=rules();second['entry']['wait_seconds']=30
        self.store.revise(identifier,1,second)
        with self.assertRaises(VersionConflict):self.store.revise(identifier,1,rules())
        self.assertEqual(self.store.get(identifier)['revision'],2)
