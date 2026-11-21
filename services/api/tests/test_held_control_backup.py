"""Backup-only scheduling preserves recovery holds and never starts normal work."""
import os
import unittest
from threading import Event
from unittest.mock import MagicMock, patch

from services.demo import held_control_backup as b
from services.demo.control_backup_v2 import FORMAT
from services.research.recovery_one_shot_guard import ONE_SHOTS
from services.api.tests import test_demo_postgres as fixture


def environment():
    return dict(MT_CONTROL_BACKUP_HELD_WORKER='true',
                MT_CONTROL_BACKUP_V2_ENABLED='true',MT_STORAGE_RECOVERY_HOLD='true',
                COLLECTION_ENABLED='false',WORKER_ROLE='collector',
                RUNTIME_DB_PROFILE='research',STAGING_ACCEPTANCE='off',
                STAGING_OPERATOR_ACTION='off',DATABASE_URL='postgresql://test-only')


def health(at=100):
    return dict(at=at,verified=True,format=FORMAT,records=1,chunks=1,
                reference={'key':'demo/backups/'+'a'*64+'.json.gz','sha256':'a'*64,'size':50},
                catalog_reference={'key':'demo/backups/roots/'+'b'*64+'.json.gz','sha256':'b'*64,'size':50})


class Stop:
    def __init__(self):self.stopped=False;self.waits=[]
    def is_set(self):return self.stopped
    def wait(self,seconds):
        self.waits.append(seconds)
        if seconds==60:self.stopped=True


class HeldBackupTests(unittest.TestCase):
    def test_rejects_invalid_worker_configuration_before_io(self):
        wrong=dict(MT_CONTROL_BACKUP_HELD_WORKER='false',
                   MT_CONTROL_BACKUP_V2_ENABLED='false',MT_STORAGE_RECOVERY_HOLD='false',
                   COLLECTION_ENABLED='true',WORKER_ROLE='demo',RUNTIME_DB_PROFILE='api',
                   STAGING_ACCEPTANCE='r2-v1',STAGING_OPERATOR_ACTION='prepare-roles-v1',
                   DATABASE_URL='')
        for k,v in wrong.items():
            with self.subTest(key=k),patch.object(b,'ConnectionPool') as pool, \
                 patch.object(b,'object_store') as objects,patch.object(b,'park_until_stopped'), \
                 patch('builtins.print'):
                b.run_held_worker(Stop(),dict(environment(),**{k:v}))
                pool.assert_not_called();objects.assert_not_called()

    def test_rejects_all_recovery_and_archiving_overlaps(self):
        for key in (*ONE_SHOTS,'MT_ARCHIVE_RECOVERY_LOOP',
                    'MT_DIAGNOSTIC_RETENTION_HELD_WORKER','MT_DIAGNOSTIC_RETENTION_ENABLED'):
            with self.subTest(key=key),self.assertRaises(ValueError):
                b.validate_environment(dict(environment(),**{key:'true'}))

    def test_only_recent_verified_discoverable_snapshot_defers_backup(self):
        self.assertFalse(b.backup_due(health(),100+86399))
        self.assertTrue(b.backup_due(health(),100+86400))
        for invalid in (None,{},dict(health(),at=True),dict(health(),at=float('nan')),
                        dict(health(),at=float('inf')),dict(health(),at=102),
                        dict(health(),verified=False),dict(health(),records=0),
                        dict(health(),chunks=False),dict(health(),format='legacy'),
                        dict(health(),catalog_reference={}),dict(health(),reference=None),
                        dict(health(),reference={'key':'root'}),dict(health(),chunks=2),
                        dict(health(),reference=dict(health()['reference'],size=True)),
                        dict(health(),reference=dict(health()['reference'],sha256='c'*64))):
            with self.subTest(value=invalid):self.assertTrue(b.backup_due(invalid,101))

    def test_healthy_backup_is_not_reuploaded_on_every_restart(self):
        store=MagicMock();store.get.return_value={'progress':health()}
        with patch.object(b,'backup_controls') as upload:
            result=b.cycle(store,object(),101,lambda:None)
        upload.assert_not_called();self.assertFalse(result['backup_performed'])

    def test_due_backup_uses_verified_multipart_path_once(self):
        store=MagicMock();store.get.return_value=None;objects=object();check=MagicMock()
        with patch.object(b,'backup_controls',return_value={'verified':True}) as upload:
            report=b.cycle(store,objects,999,check)
        upload.assert_called_once_with(store,objects,now=999)
        self.assertTrue(report['backup_performed']);self.assertEqual(check.call_count,2)

    def test_revoked_hold_aborts_before_upload(self):
        store=MagicMock();store.get.return_value=None
        check=MagicMock(side_effect=[None,ValueError('revoked')])
        with patch.object(b,'backup_controls') as upload,self.assertRaises(ValueError):
            b.cycle(store,object(),999,check)
        upload.assert_not_called()

    def harness(self,*,fail=False,lost=False,principal='pocket_research_runtime'):
        stop=Stop();objects=MagicMock()
        with patch.object(b,'ConnectionPool') as pool,patch.object(b.psycopg,'connect') as connect, \
             patch.object(b,'DemoStore'),patch.object(b,'object_store',return_value=objects) as object_factory, \
             patch.object(b,'cycle') as cycle,patch.object(b,'park_until_stopped') as park, \
             patch('builtins.print') as printed:
            pool.return_value.__enter__.return_value.connection.return_value.__enter__.return_value.execute.return_value.fetchone.return_value={'principal':principal}
            lease=connect.return_value.__enter__.return_value;attempts=0
            def execute(sql,args=None):
                nonlocal attempts
                if 'pg_try_advisory_lock' in sql:
                    attempts+=1;return MagicMock(fetchone=lambda:{'acquired':attempts>1})
                if lost:raise RuntimeError('private lease error')
                return MagicMock()
            lease.execute.side_effect=execute
            def run_cycle(store,client,now,safety):
                safety()
                if fail:raise RuntimeError('postgresql://secret-test-only')
                return {'event':'held_control_backup_checked'}
            cycle.side_effect=run_cycle
            b.run_held_worker(stop,environment())
            return stop,objects,cycle,park,printed,object_factory

    def test_replacement_waits_for_lease_before_backup(self):
        stop,objects,cycle,_,_,_=self.harness()
        self.assertEqual(stop.waits,[5,60]);cycle.assert_called_once()
        objects.client.close.assert_called_once()

    def test_failed_backup_parks_with_no_immediate_retry_or_secret_logging(self):
        _,objects,cycle,park,printed,_=self.harness(fail=True)
        cycle.assert_called_once();park.assert_called_once()
        objects.client.close.assert_called_once()
        self.assertNotIn('secret-test-only',str(printed.call_args_list))

    def test_lost_lease_prevents_backup(self):
        _,_,cycle,park,_,_=self.harness(lost=True)
        cycle.assert_called_once();park.assert_called_once()

    def test_owner_or_maintenance_credentials_cannot_run_backup_worker(self):
        for role in ('pocket_staging','pocket_archive_maintenance'):
            _,_,cycle,park,_,factory=self.harness(principal=role)
            factory.assert_not_called();cycle.assert_not_called();park.assert_called_once()

    def test_runtime_never_constructs_normal_workers(self):
        from services.research import runtime
        with patch.dict(os.environ,environment(),clear=True), \
             patch.object(b,'run_held_worker',return_value='backup-only') as held, \
             patch.object(runtime,'ConnectionPool') as ordinary:
            self.assertEqual(runtime.run(None,Event()),'backup-only')
        ordinary.assert_not_called();held.assert_called_once()


@unittest.skipUnless(fixture.URL,'Disposable PostgreSQL pocket_test required')
class RealBackupLeaseTests(unittest.TestCase):
    def test_backup_serializes_replacements_but_allows_separate_archiver(self):
        import psycopg
        from services.demo.shadow_diagnostic_retention import RETENTION_LEASE_KEY
        with psycopg.connect(fixture.URL,autocommit=True) as second:
            with psycopg.connect(fixture.URL,autocommit=True) as first:
                self.assertTrue(first.execute('SELECT pg_try_advisory_lock(%s)',(b.BACKUP_LEASE_KEY,)).fetchone()[0])
                self.assertFalse(second.execute('SELECT pg_try_advisory_lock(%s)',(b.BACKUP_LEASE_KEY,)).fetchone()[0])
                self.assertTrue(second.execute('SELECT pg_try_advisory_lock(%s)',(RETENTION_LEASE_KEY,)).fetchone()[0])
            self.assertTrue(second.execute('SELECT pg_try_advisory_lock(%s)',(b.BACKUP_LEASE_KEY,)).fetchone()[0])
