"""Supplied archive catalog and checksum-verified R2 readback must agree."""
import unittest
from copy import deepcopy
from uuid import uuid4

from services.demo.shadow_catalog_r2_crosscheck import audit_supplied_catalog_readbacks
from services.demo.shadow_history_reconcile import HistoryReconciliationError
from services.demo.shadow_reclaimed_history import normalize_reclaimed_manifest_page
from services.api.tests.test_shadow_reclaimed_history import archived


def evidence(kind='raw', originals=2, *, legacy=False):
    source=archived(kind,originals)
    if legacy:
        source['manifest']['manifest_key']=(
            'demo/shadow/archive-manifest/'+('batch/' if kind=='packed' else '')
            +str(uuid4()))
    page=normalize_reclaimed_manifest_page(source,offset=0)
    m=source['manifest']
    summary=dict(
        manifest_key=m['manifest_key'],manifest_id=m['manifest_id'],
        manifest_digest=m['manifest_digest'],kind=kind,
        manifest_identity_mode=page['manifest_identity_mode'],
        archived_rows=(originals if kind=='raw' else 1),
        original_events=originals)
    return summary,[page]


def catalog(items, *, cursor=None, more=False):
    keys=sorted(items,key=lambda x:x['manifest_key'])
    return dict(source='manifests',order='manifest_key',
                items=keys,request_cursor=cursor,more=more,
                next_cursor=keys[-1]['manifest_key'] if more else None)


class CatalogR2CrosscheckTests(unittest.TestCase):
    def test_complete_supplied_raw_and_packed_legacy_readbacks(self):
        raw,rpages=evidence('raw',2)
        packed,ppages=evidence('packed',3,legacy=True)
        summary=audit_supplied_catalog_readbacks(
            [catalog([raw,packed])],
            {raw['manifest_key']:rpages,packed['manifest_key']:ppages})
        self.assertTrue(summary['readbacks_match_every_listed_manifest'])
        self.assertEqual(summary['listed_manifests'],2)
        self.assertEqual(summary['raw_manifests'],1)
        self.assertEqual(summary['packed_manifests'],1)
        self.assertEqual(summary['claimed_archived_source_rows'],3)
        self.assertEqual(summary['checked_archived_originals'],5)
        self.assertEqual(summary['unique_archived_original_ids'],5)
        self.assertEqual(len(summary['cross_manifest_identity_digest']),64)
        for flag in ('independent_r2_reverification_performed',
                     'live_postgres_snapshot_consistent',
                     'global_r2_catalog_exhaustion_verified',
                     'all_time_coverage_complete','safe_to_train',
                     'realized_pnl_reconciled','safe_to_restart_writers'):
            self.assertFalse(summary[flag])

    def test_catalog_keyset_cursors_and_terminal_required(self):
        a,pa=evidence()
        b,pb=evidence('packed',3)
        ordered=sorted([a,b],key=lambda x:x['manifest_key'])
        p1=catalog([ordered[0]],more=True)
        p2=catalog([ordered[1]],cursor=ordered[0]['manifest_key'])
        readbacks={a['manifest_key']:pa,b['manifest_key']:pb}
        result=audit_supplied_catalog_readbacks([p1,p2],readbacks)
        self.assertEqual(result['supplied_catalog_pages'],2)
        for bad in ([p1],[p2],
                    [p1,dict(p2,request_cursor=None)],
                    [p1,dict(p2,request_cursor='not-a-key')],
                    [p1,dict(p2,items=[ordered[0]])]):
            with self.subTest(pages=bad):
                with self.assertRaises(HistoryReconciliationError):
                    audit_supplied_catalog_readbacks(bad,readbacks)

    def test_missing_unlisted_or_duplicate_manifest_readbacks_rejected(self):
        a,pa=evidence()
        b,pb=evidence('packed',2)
        summary=catalog([a,b])
        complete={a['manifest_key']:pa,b['manifest_key']:pb}
        for readbacks in (
            {a['manifest_key']:pa},
            {**complete,'demo/shadow/archive-manifest/'+str(uuid4()):pa},
        ):
            with self.subTest(readbacks=list(readbacks)):
                with self.assertRaises(HistoryReconciliationError):
                    audit_supplied_catalog_readbacks([summary],readbacks)
        identical=deepcopy(b)
        identical['manifest_id']=a['manifest_id']
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_catalog_readbacks(
                [catalog([a,identical])],complete)

    def test_readback_digest_identity_counts_and_kind_are_strict(self):
        item,pages=evidence('raw',2)
        readbacks={item['manifest_key']:pages}
        for changed in (
            dict(manifest_digest='b'*64),
            dict(manifest_id=str(uuid4())),
            dict(original_events=3,archived_rows=3),
            dict(kind='packed',archived_rows=1),
            dict(archived_rows=1),
            dict(manifest_identity_mode='legacy_independent_key'),
        ):
            altered=dict(item,**changed)
            with self.subTest(changed=changed):
                with self.assertRaises(HistoryReconciliationError):
                    audit_supplied_catalog_readbacks([catalog([altered])],
                                                    readbacks)

    def test_original_uuid_collision_across_two_individually_valid_manifests(self):
        one,pone=evidence('raw',2)
        two,ptwo=evidence('packed',2)
        ptwo=deepcopy(ptwo)
        ptwo[0]['items'][0]=deepcopy(pone[0]['items'][0])
        with self.assertRaisesRegex(HistoryReconciliationError,'repeated across'):
            audit_supplied_catalog_readbacks(
                [catalog([one,two])],
                {one['manifest_key']:pone,two['manifest_key']:ptwo})

    def test_cold_without_verified_flag_or_missing_final_offset_fails(self):
        item,pages=evidence('raw',2)
        for changed in (dict(verified=False),dict(next_offset=1),
                        dict(page_events=3),dict(offset=1)):
            wrong=[dict(pages[0],**changed)]
            with self.subTest(changed=changed):
                with self.assertRaises(HistoryReconciliationError):
                    audit_supplied_catalog_readbacks(
                        [catalog([item])],{item['manifest_key']:wrong})

    def test_wrong_original_metadata_rejected_even_after_manifest_page_check(self):
        item,pages=evidence('raw',2)
        wrong=deepcopy(pages)
        wrong[0]['items'][0]['progress']['time']=float('nan')
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_catalog_readbacks(
                [catalog([item])],{item['manifest_key']:wrong})

    def test_empty_terminal_catalog_is_only_empty_supplied_catalog(self):
        summary=audit_supplied_catalog_readbacks(
            [catalog([])],{})
        self.assertEqual(summary['checked_archived_originals'],0)
        self.assertTrue(summary['supplied_catalog_terminal'])
        self.assertFalse(summary['global_r2_catalog_exhaustion_verified'])

    def test_unbounded_catalog_and_extra_data_are_rejected(self):
        item,pages=evidence()
        for supplied in ([],[catalog([item])]*9):
            with self.subTest(length=len(supplied)):
                with self.assertRaises(HistoryReconciliationError):
                    audit_supplied_catalog_readbacks(
                        supplied,{item['manifest_key']:pages})
        many=[]
        entries={}
        for _ in range(33):
            m,p=evidence('raw',1)
            many.append(m);entries[m['manifest_key']]=p
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_catalog_readbacks([catalog(many)],entries)


from services.api.tests import test_demo_postgres as fixture


@unittest.skipUnless(fixture.URL, 'Disposable PostgreSQL is required')
class RealPostgresCatalogCrosscheckTests(unittest.TestCase):
    setUp=fixture.DemoPostgres.setUp
    tearDown=fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def test_exact_sql_manifest_catalog_pages_match_verified_raw_and_packed(self):
        import hashlib
        import json
        from psycopg.types.json import Jsonb
        from services.demo.shadow_archive_reader import list_manifests
        readbacks={}
        for kind,legacy in (('raw',True),('packed',False)):
            row=archived(kind,2)
            ident=row['manifest']['manifest_id']
            key=row['manifest']['manifest_key']
            if legacy:
                key='demo/shadow/archive-manifest/'+str(uuid4())
                row['manifest']['manifest_key']=key
            is_raw=kind=='raw'
            pg_manifest=dict(
                format=('shadow-r2-event-batch-v1' if is_raw else
                        'shadow-diagnostic-r2-manifest-v1'),
                count=(2 if is_raw else 1),
                **({} if is_raw else dict(original_events=2)))
            digest=hashlib.sha256(json.dumps(
                pg_manifest,sort_keys=True,separators=(',',':'),
                allow_nan=False).encode('utf-8')).hexdigest()
            row['manifest']['manifest_digest']=digest
            with self.store.pool.connection() as c:
                c.execute("""INSERT INTO research_job
                    (id,asset,parameters,progress,idempotency_key,status,finished_at)
                    VALUES (%s,'crypto',%s,%s,%s,'succeeded',clock_timestamp())""",
                    (ident,Jsonb(dict(kind=('shadow_event_r2_manifest' if is_raw else
                          'diagnostic_batch_r2_manifest'))),
                     Jsonb(pg_manifest),key))
            readbacks[key]=[normalize_reclaimed_manifest_page(row,offset=0)]
        first=list_manifests(self.store.pool,limit=1)
        self.assertTrue(first['more'])
        second=list_manifests(self.store.pool,limit=1,
                              cursor=first['next_cursor'])
        self.assertFalse(second['more'])
        result=audit_supplied_catalog_readbacks([first,second],readbacks)
        self.assertEqual(result['listed_manifests'],2)
        self.assertEqual(result['checked_archived_originals'],4)
        self.assertTrue(result['readbacks_match_every_listed_manifest'])
        self.assertFalse(result['all_time_coverage_complete'])
        # Genuine source manifests remain intact after this read-only audit.
        with self.store.pool.connection() as c:
            count=c.execute("""SELECT count(*) AS n FROM research_job
                WHERE idempotency_key LIKE 'demo/shadow/archive-manifest/%'""").fetchone()['n']
        self.assertEqual(count,2)


if __name__=='__main__':
    unittest.main()
