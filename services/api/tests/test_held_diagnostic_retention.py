"""Archive-only supervision cannot restart trading or retry failed reclamation."""
import os
import unittest
from unittest.mock import MagicMock,patch

from services.demo import shadow_diagnostic_retention as r
from services.api.tests import test_shadow_diagnostic_retention as fixtures
from services.api.tests import test_shadow_archive_recovery as archive_fixtures
from services.research.recovery_one_shot_guard import ONE_SHOTS
from services.api.tests import test_demo_postgres as database_fixture


def environment():
    return dict(fixtures.DiagnosticRetentionTests().env(),
                MT_DIAGNOSTIC_RETENTION_HELD_WORKER='true',
                MT_STORAGE_RECOVERY_HOLD='true',WORKER_ROLE='collector',
                COLLECTION_ENABLED='false',RUNTIME_DB_PROFILE='research',
                STAGING_ACCEPTANCE='off',STAGING_OPERATOR_ACTION='off')


class Stop:
    def __init__(self):self.stopped=False;self.waits=[]
    def is_set(self):return self.stopped
    def wait(self,seconds):
        self.waits.append(seconds)
        if seconds==60:self.stopped=True


class HeldRetentionTests(unittest.TestCase):
    def test_only_an_explicitly_disabled_collector_can_enable_held_mode(self):
        env=environment()
        self.assertEqual(r.settings(env,True)[1],15)
        for key,value in (('WORKER_ROLE','demo'),('WORKER_ROLE','processor'),
                          ('COLLECTION_ENABLED','true'),('RUNTIME_DB_PROFILE','api'),
                          ('MT_STORAGE_RECOVERY_HOLD','false'),
                          ('STAGING_ACCEPTANCE','r2-v1'),('STAGING_OPERATOR_ACTION','prepare-roles-v1')):
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                r.settings(dict(env,**{key:value}),True)
        with self.assertRaises(ValueError):
            r.settings(dict(env,MT_DIAGNOSTIC_RETENTION_HELD_WORKER='false'),True)

    def test_every_recovery_or_backup_overlap_is_rejected_before_io(self):
        for key in (*ONE_SHOTS,'MT_ARCHIVE_RECOVERY_LOOP','MT_CONTROL_BACKUP_V2_ENABLED'):
            with self.subTest(key=key),patch.object(r,'ConnectionPool') as pool, \
                 patch.object(r,'object_store') as objects,patch.object(r,'park_until_stopped'), \
                 patch('builtins.print'):
                r.run_held_worker(Stop(),dict(environment(),**{key:'true'}))
                pool.assert_not_called();objects.assert_not_called()

    def test_revocation_during_r2_read_prevents_the_sql_delete_transaction(self):
        env=environment();pool=MagicMock();objects=fixtures.MemoryObjects()
        objects.on_read=lambda:env.update(COLLECTION_ENABLED='true')
        row=archive_fixtures.ShadowArchiveRecoveryTests().row()
        with self.assertRaises(ValueError):
            r.reclaim_page(pool,objects,[row],r.PREFIX,1794500000,
                           safety_check=lambda:r.settings(env,True))
        pool.connection.assert_not_called()

    def harness(self, *, fail_cycle=False, lost_lease=False):
        stop=Stop();objects=MagicMock()
        with patch.object(r,'ConnectionPool'),patch.object(r,'verify_scoped_role') as role, \
             patch.object(r.psycopg,'connect') as connect, \
             patch.object(r,'object_store',return_value=objects), \
             patch.object(r,'cycle') as cycle,patch.object(r,'park_until_stopped') as park, \
             patch('builtins.print') as printed:
            lease=connect.return_value.__enter__.return_value
            claim_attempts=0
            def execute(query,args=None):
                nonlocal claim_attempts
                if 'pg_try_advisory_lock' in query:
                    claim_attempts+=1
                    return MagicMock(fetchone=lambda:dict(acquired=claim_attempts>1))
                if lost_lease:raise RuntimeError('simulated lost connection')
                return MagicMock(fetchone=lambda:dict(lease_alive=1))
            lease.execute.side_effect=execute
            def run_cycle(*args,**kwargs):
                kwargs['safety_check']()
                if fail_cycle:raise RuntimeError('postgresql://secret-test-only')
                return dict(deleted_rows=0,eligible_rows=0)
            cycle.side_effect=run_cycle
            r.run_held_worker(stop,environment())
            return stop,objects,cycle,park,printed,role

    def test_replacement_waits_for_lease_and_keeps_the_bounded_cycle(self):
        stop,objects,cycle,_,_,role=self.harness()
        self.assertEqual(stop.waits,[5,60])
        role.assert_called_once()
        cycle.assert_called_once()
        options=cycle.call_args.kwargs
        self.assertEqual((options['pages'],options['age_hours'],options['raw_page_size']), (10,24,100))
        self.assertIs(options['execute'],True)
        objects.client.close.assert_called_once()

    def test_source_failure_parks_without_retry_and_redacts_error_details(self):
        _,objects,cycle,park,printed,_=self.harness(fail_cycle=True)
        cycle.assert_called_once();park.assert_called_once()
        objects.client.close.assert_called_once()
        self.assertNotIn('secret-test-only',str(printed.call_args_list))

    def test_lost_lease_prevents_any_archive_cycle(self):
        _,_,cycle,park,_,_=self.harness(lost_lease=True)
        cycle.assert_not_called();park.assert_called_once()

    def test_runtime_routes_held_mode_without_constructing_normal_workers(self):
        from services.research import runtime
        env=environment();stop=Stop()
        with patch.dict(os.environ,env,clear=True), \
             patch.object(r,'run_held_worker',return_value='archive-only') as held, \
             patch.object(runtime,'ConnectionPool') as ordinary_pool:
            result=runtime.run(None,stop)
        self.assertEqual(result,'archive-only');held.assert_called_once()
        ordinary_pool.assert_not_called()


@unittest.skipUnless(database_fixture.URL,'Disposable PostgreSQL pocket_test required')
class RealRetentionLeaseTests(unittest.TestCase):
    def test_a_replacement_waits_until_the_original_session_closes(self):
        import psycopg
        with psycopg.connect(database_fixture.URL,autocommit=True) as second:
            with psycopg.connect(database_fixture.URL,autocommit=True) as first:
                self.assertTrue(first.execute('SELECT pg_try_advisory_lock(%s)',
                                               (r.RETENTION_LEASE_KEY,)).fetchone()[0])
                self.assertFalse(second.execute('SELECT pg_try_advisory_lock(%s)',
                                                 (r.RETENTION_LEASE_KEY,)).fetchone()[0])
            self.assertTrue(second.execute('SELECT pg_try_advisory_lock(%s)',
                                            (r.RETENTION_LEASE_KEY,)).fetchone()[0])
