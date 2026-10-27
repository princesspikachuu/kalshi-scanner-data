"""Real disposable-PG proof that runtime grants support work but cannot rewrite history."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from services.api.auth_policy import GoogleIdentity, new_session_material
from services.api.config import Settings
from services.api.manage import migrate
from services.api.store import PostgresStore
from services.research.acceptance import audit_database, HISTORY
from services.research.budget import ReadBudget
from services.research.campaigns import CampaignStore
from services.research.datasets import DatasetStore
from services.research.queue import ResearchQueue
from services.research.reports import ReportStore
from test_datasets import Fixture

URL = os.environ.get('POCKET_TEST_DATABASE_URL')
ROOT = Path(__file__).resolve().parents[3]


class ScopedPool:
    # SET LOCAL ROLE is TEST-ONLY impersonation. Production must use separate LOGINs.
    def __init__(self, role): self.role = role
    @contextmanager
    def connection(self):
        with psycopg.connect(URL, row_factory=dict_row) as c:
            c.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(self.role)))
            yield c


@unittest.skipUnless(URL, 'Requires disposable pocket_test PostgreSQL')
class RuntimePrivilegesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(URL).path != '/pocket_test': raise RuntimeError('Requires disposable pocket_test database')
        migrate(URL)
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute((ROOT/'infra/runtime-roles.sql').read_text(), prepare=False)
        cls.api = ScopedPool('pocket_api_runtime')
        cls.worker = ScopedPool('pocket_research_runtime')

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(URL, autocommit=True) as c:
            c.execute('DROP OWNED BY pocket_api_runtime,pocket_research_runtime')
            c.execute('DROP ROLE pocket_api_runtime,pocket_research_runtime')

    def test_api_login_session_and_campaign_controls_work(self):
        store = PostgresStore.__new__(PostgresStore); store.pool = self.api
        with psycopg.connect(URL) as c:
            c.execute('TRUNCATE owner_account,owner_session,login_challenge,login_rate,research_read_budget CASCADE')
        self.assertTrue(store.ready()); self.assertTrue(store.allow('role-test', 10))
        store.challenge('a'*64, 'b'*64, 'c'*64)
        self.assertTrue(store.consume('a'*64, 'b'*64, 'c'*64))
        material = new_session_material()
        store.session(GoogleIdentity('role-test-owner','owner@gmail.com',True),material,
                      Settings('https://app.test','client',URL,'x'*32,owner_email='owner@gmail.com'))
        self.assertIsNotNone(store.current(material['token_hash']))
        store.revoke(material['token_hash']); self.assertIsNone(store.current(material['token_hash']))
        campaigns = CampaignStore(self.api)
        identifier = campaigns.create('btc','2026-10-25','2026-10-25',str(uuid4()),
                                      now=datetime(2026,10,27,tzinfo=timezone.utc))
        self.assertIsNotNone(campaigns.get(identifier)); self.assertTrue(campaigns.days(identifier))
        self.assertTrue(campaigns.control(identifier,'pause')); self.assertTrue(campaigns.control(identifier,'resume'))
        self.assertFalse(campaigns.set_refresh('btc',False)['enabled'])
        with self.worker.connection() as c:
            job=c.execute('SELECT job_id FROM research_campaign WHERE id=%s',(identifier,)).fetchone()['job_id']
        self.assertIsNotNone(ResearchQueue(self.worker).claim(job_id=job))
        ReadBudget(self.worker).configure(1,1)

    def test_worker_can_publish_and_api_can_read_but_neither_can_rewrite_history(self):
        prepared = Fixture().prepare()
        datasets = DatasetStore(self.worker)
        dataset = datasets.publish('role-raw-'+str(uuid4()),prepared)
        stream = 'role-results-'+str(uuid4())
        result = ReportStore(self.worker).publish(stream,'btc',[dataset],latest_ids=[dataset])
        with self.api.connection() as c:
            self.assertEqual(c.execute('SELECT id FROM research_result WHERE id=%s',(result,)).fetchone()['id'],result)
        for role in (self.api,self.worker):
            for statement in ('TRUNCATE public.research_result',
                              'UPDATE public.research_result SET asset=asset',
                              'DELETE FROM public.research_dataset',
                              'ALTER TABLE public.research_result DISABLE TRIGGER ALL',
                              'CREATE TABLE public.shadow_history(id int)',
                              'CREATE TEMP TABLE shadow_history(id int)'):
                with self.subTest(role=role.role,statement=statement):
                    with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                        with role.connection() as c: c.execute(statement)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.api.connection() as c: c.execute("UPDATE owner_account SET google_subject='replacement'")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.worker.connection() as c: c.execute('SELECT * FROM public.owner_session')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with self.api.connection() as c: c.execute("INSERT INTO public.research_artifact VALUES('x','x','x','x',1)")
        with self.assertRaisesRegex(psycopg.Error, 'sealed'):
            with self.worker.connection() as c:
                c.execute("INSERT INTO research_observation VALUES(%s,'2026-10-25','late',1,'{}')",(result,))

    def test_catalog_audit_identifies_operator_and_does_not_mutate_database(self):
        result = audit_database(URL)
        self.assertTrue(result['migrations_match']); self.assertEqual(result['migration_count'],9)
        self.assertEqual(result['history_flags']['found'],len(HISTORY))
        self.assertFalse(result['privilege_boundary_ready'])
        with psycopg.connect(URL) as c:
            rows = c.execute("SELECT rolcanlogin,rolcreaterole,rolcreatedb,rolsuper,rolbypassrls FROM pg_roles WHERE rolname IN ('pocket_api_runtime','pocket_research_runtime')").fetchall()
            self.assertEqual(rows,[(False,False,False,False,False)]*2)
            self.assertEqual(c.execute("SELECT count(*) FROM pg_auth_members WHERE member IN (SELECT oid FROM pg_roles WHERE rolname IN ('pocket_api_runtime','pocket_research_runtime'))").fetchone()[0],0)


    def test_audit_accepts_direct_unprivileged_login_and_refuses_operator(self):
        password=uuid4().hex  # Disposable test-only credential, never printed.
        with psycopg.connect(URL,autocommit=True) as c:
            c.execute(sql.SQL('ALTER ROLE pocket_research_runtime LOGIN PASSWORD {}').format(sql.Literal(password)))
        try:
            parts=urlsplit(URL)
            direct=parts._replace(netloc='pocket_research_runtime:'+password+'@'+parts.netloc.rsplit('@',1)[-1]).geturl()
            result=audit_database(direct)
            self.assertTrue(result['privilege_boundary_ready'],result)
            self.assertFalse(audit_database(URL)['privilege_boundary_ready'])
        finally:
            with psycopg.connect(URL,autocommit=True) as c:
                c.execute('ALTER ROLE pocket_research_runtime NOLOGIN PASSWORD NULL')
