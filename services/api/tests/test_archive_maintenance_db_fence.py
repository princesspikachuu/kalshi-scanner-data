"""Disposable PostgreSQL proves only old diagnostics can be reclaimed.

No Render connection and no owner credentials. The CI-only pocket_test database
uses a known local password; runtime/operator deployment contains no secret.
"""
import os
import unittest
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from services.api.manage import migrate
from services.demo.shadow_archive_recovery import archive_payload

URL=os.environ.get('POCKET_TEST_DATABASE_URL')
ROOT=Path(__file__).resolve().parents[3]
ROLE='pocket_archive_maintenance'
TEST_PASSWORD='disposable-ci-archive-test-only'


@unittest.skipUnless(URL,'Disposable POCKET_TEST_DATABASE_URL required')
class ArchiveMaintenanceDatabaseFenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from urllib.parse import urlparse
        if urlparse(URL).path!='/pocket_test':
            raise RuntimeError('Archive SQL tests are restricted to pocket_test')
        migrate(URL)
        with psycopg.connect(URL,autocommit=True) as c:
            script=(ROOT/'infra/archive-maintenance-role.sql').read_text()
            c.execute(script,prepare=False)
            # Test-only fixed credential in a disposable local container.
            c.execute("ALTER ROLE pocket_archive_maintenance LOGIN PASSWORD 'disposable-ci-archive-test-only'")
        cls.created_ids=[]
        cls.created_manifest_ids=[]

    @classmethod
    def tearDownClass(cls):
        with psycopg.connect(URL,autocommit=True) as c:
            for ident in cls.created_ids+cls.created_manifest_ids:
                c.execute('DELETE FROM research_job WHERE id=%s',(ident,))
            c.execute('DROP FUNCTION IF EXISTS public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb)')
            c.execute('DROP OWNED BY pocket_archive_maintenance')
            c.execute('DROP ROLE pocket_archive_maintenance')

    def test_role_has_no_table_delete_update_or_create_privilege(self):
        with psycopg.connect(URL) as owner:
            p=owner.execute("""SELECT
              has_table_privilege(%s,'research_job','DELETE'),
              has_table_privilege(%s,'research_job','UPDATE'),
              has_table_privilege(%s,'research_job','TRUNCATE'),
              has_column_privilege(%s,'research_job','id','INSERT'),
              has_function_privilege(%s,
                'public.mt_reclaim_shadow_diagnostics(uuid,text,jsonb,jsonb)','EXECUTE'),
              has_schema_privilege(%s,'public','CREATE')
            """,(ROLE,ROLE,ROLE,ROLE,ROLE,ROLE)).fetchone()
        self.assertEqual(p,(False,False,False,False,True,False))

    def test_direct_delete_denied_and_only_old_safe_raw_evidence_reclaimed(self):
        safe=self.create_record('demo/shadow/event/',{'event':'FAVORITE_STAT_DECISION'},aged=True)
        manifest=self.create_manifest(safe)
        with psycopg.connect(URL,user=ROLE,password=TEST_PASSWORD,autocommit=True) as archive:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                archive.execute('DELETE FROM public.research_job WHERE id=%s',(safe['id'],))
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                archive.execute("""INSERT INTO public.research_job(
                    id,asset,parameters,progress,idempotency_key,status)
                    VALUES (%s,'crypto','{}','{}',%s,'succeeded')""",
                    (uuid4(),'demo/shadow/event/'+str(uuid4())))
            result=archive.execute(
                'SELECT id FROM public.mt_reclaim_shadow_diagnostics(%s,%s,%s,%s)',
                (manifest[0],'shadow_event_r2_manifest',Jsonb(manifest[1]),
                 Jsonb([archive_payload([safe])[0]]))).fetchall()
            self.assertEqual(result,[(str(safe['id']),)])
        with psycopg.connect(URL) as owner:
            self.assertIsNone(owner.execute(
                'SELECT id FROM research_job WHERE id=%s',(safe['id'],)).fetchone())
            self.assertIsNotNone(owner.execute(
                'SELECT id FROM research_job WHERE id=%s',(manifest[0],)).fetchone())

    def test_financial_and_fresh_diagnostics_cannot_be_reclaimed(self):
        financial=self.create_record('demo/shadow/event/',{'event':'SETTLED','cash':100},aged=True)
        current=self.create_record('demo/shadow/event/',{'event':'FAVORITE_STAT_DECISION'},aged=False)
        wrong_namespace=self.create_record('demo/order/',{'event':'FAVORITE_STAT_DECISION'},aged=True)
        for row in (financial,current,wrong_namespace):
            manifest=self.create_manifest(row)
            with psycopg.connect(URL,user=ROLE,password=TEST_PASSWORD,autocommit=True) as archive:
                with self.assertRaises(psycopg.Error):
                    archive.execute(
                        'SELECT id FROM public.mt_reclaim_shadow_diagnostics(%s,%s,%s,%s)',
                        (manifest[0],'shadow_event_r2_manifest',Jsonb(manifest[1]),
                         Jsonb([archive_payload([row])[0]]))).fetchall()
            with psycopg.connect(URL) as owner:
                self.assertIsNotNone(owner.execute(
                    'SELECT id FROM research_job WHERE id=%s',(row['id'],)).fetchone())

    def test_a_modified_snapshot_and_owner_direct_invocation_are_rejected(self):
        safe=self.create_record('demo/shadow/event/',{'event':'FAVORITE_STAT_DECISION'},aged=True)
        manifest=self.create_manifest(safe)
        altered=archive_payload([safe])[0]
        altered['progress']=dict(event='FAVORITE_STAT_DECISION',altered=True)
        with psycopg.connect(URL,user=ROLE,password=TEST_PASSWORD,autocommit=True) as archive:
            with self.assertRaises(psycopg.Error):
                archive.execute(
                    'SELECT id FROM public.mt_reclaim_shadow_diagnostics(%s,%s,%s,%s)',
                    (manifest[0],'shadow_event_r2_manifest',Jsonb(manifest[1]),
                     Jsonb([altered])))
        with psycopg.connect(URL,autocommit=True) as owner:
            with self.assertRaises(psycopg.Error):
                owner.execute(
                    'SELECT id FROM public.mt_reclaim_shadow_diagnostics(%s,%s,%s,%s)',
                    (manifest[0],'shadow_event_r2_manifest',Jsonb(manifest[1]),
                     Jsonb([archive_payload([safe])[0]])))
            self.assertIsNotNone(owner.execute(
                'SELECT id FROM research_job WHERE id=%s',(safe['id'],)).fetchone())

    def create_record(self,prefix,progress,*,aged):
        ident=uuid4()
        with psycopg.connect(URL,autocommit=True,row_factory=dict_row) as c:
            row=c.execute("""INSERT INTO research_job
                (id,asset,parameters,progress,idempotency_key,status,
                 created_at,finished_at,available_at)
                VALUES (%s,'crypto','{}'::jsonb,%s,%s,'succeeded',
                        clock_timestamp()-make_interval(days=>%s),
                        clock_timestamp(),clock_timestamp()-make_interval(days=>%s))
                RETURNING id::text,idempotency_key,asset,status,parameters,progress,
                    created_at,started_at,finished_at,lease_expires_at,attempts,
                    error_code,available_at,max_attempts,lease_token""",
                (ident,Jsonb(progress),prefix+str(ident),3 if aged else 0,
                 3 if aged else 0)).fetchone()
        self.created_ids.append(ident)
        return row

    def create_manifest(self,row):
        from datetime import datetime,timezone
        ident=uuid4()
        payload=dict(format='shadow-r2-event-batch-v1',
            source_prefix='demo/shadow/event/',count=1,ids=[row['id']],
            restorable=True,created_at=datetime.now(timezone.utc).timestamp(),
            reference=dict(key='demo/events/'+'a'*64+'.json.gz',
                           sha256='a'*64,size=320))
        # The function creates its manifest atomically; no table INSERT
        # privilege is granted to the maintenance login itself.
        self.created_manifest_ids.append(ident)
        return ident,payload


if __name__=='__main__':
    unittest.main()
