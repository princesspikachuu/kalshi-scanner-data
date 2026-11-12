"""Disposable PostgreSQL test for bounded hot/packed/R2 overlap.

Never connects to production or Cloudflare; R2 page data is a deliberately
supplied, already-verified fixture and does not attest live R2 credentials.
"""
import unittest
from copy import deepcopy
from uuid import uuid4

from services.api.tests import test_demo_postgres as fixture
from services.api.tests.test_shadow_reclaimed_history import archived
from services.api.tests.test_shadow_catalog_r2_crosscheck import catalog
from services.demo.shadow_reclaimed_history import normalize_reclaimed_manifest_page
from services.demo.shadow_hot_r2_overlap import audit_supplied_hot_r2_overlap
from services.demo.shadow_history_reconcile import HistoryReconciliationError
from services.demo.shadow_history_pages import page_history


@unittest.skipUnless(fixture.URL, 'Disposable PostgreSQL pocket_test required')
class RealPostgresHotR2OverlapTests(unittest.TestCase):
    setUp = fixture.DemoPostgres.setUp
    tearDown = fixture.DemoPostgres.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.DemoPostgres.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.DemoPostgres.tearDownClass.__func__(cls)

    def _supplied_sources(self):
        from services.paper_demo.shadow.storage import UPSERT, entry
        from services.paper_demo.shadow.diagnostic_batches import compact_diagnostic_rows

        original_keys = set()
        # Five real raw rows require a two-page pagination walk (max 4/page).
        for number in range(5):
            ident=self.demo.put('shadow/event/'+f'{number:04d}',
                dict(event='FAVORITE_STAT_DECISION',time=100+number,
                     audit_label='raw-'+str(number)),
                parameters=dict(series='KXTEST',index=number))
            original_keys.add(str(ident))

        # Two genuine diagnostic originals are compacted into one real packed
        # research_job row; one is a settlement audit to verify preservation.
        originals=[]
        for number in range(2):
            originals.append(entry('demo/shadow/event/'+str(uuid4()),
                dict(series='KXTEST',packed=number),
                dict(event='SETTLED' if number==1 else 'FAVORITE_STAT_DECISION',
                     time=200+number,fee_cents=number+3)))
        batch=compact_diagnostic_rows(originals,entry)
        self.assertEqual(len(batch),1)
        with self.store.pool.connection() as c:
            c.execute(UPSERT,batch[0])

        def pages(source):
            result=[]
            cursor=None
            while True:
                p=page_history(self.store.pool,source,cursor=cursor)
                result.append(p)
                if not p['more']:
                    return result
                cursor=p['next_cursor']
                self.assertLessEqual(len(result),8)

        raw,packed=pages('raw'),pages('packed')
        self.assertEqual(len(raw),2)
        self.assertEqual(len(packed),1)
        self.assertEqual(sum(len(p['items']) for p in raw),5)
        self.assertEqual(sum(len(p['items']) for p in packed),2)

        # A readback fixture matching one original from each hot source.
        source=archived('raw',2)
        selected=[deepcopy(raw[0]['items'][0]),
                  deepcopy(packed[0]['items'][1])]
        source['items']=[
            dict(id=x['id'],key=x['key'],parameters=x['parameters'],
                 progress=x['progress']) for x in selected
        ]
        cold=normalize_reclaimed_manifest_page(source,offset=0)
        m=source['manifest']
        metadata=dict(manifest_key=m['manifest_key'],
                      manifest_id=m['manifest_id'],
                      manifest_digest=m['manifest_digest'],
                      kind='raw',manifest_identity_mode='canonical_row_key',
                      archived_rows=2,original_events=2)
        return raw,packed,metadata,[cold],original_keys

    def test_real_sql_raw_and_genuine_packed_pages_dedup_cold_originals(self):
        raw,packed,metadata,cold,ids=self._supplied_sources()
        result=audit_supplied_hot_r2_overlap(
            raw,packed,[catalog([metadata])],
            {metadata['manifest_key']:cold})
        self.assertEqual(result['raw_source_rows'],5)
        self.assertEqual(result['packed_source_rows'],1)
        self.assertEqual(result['hot_originals_supplied'],7)
        self.assertEqual(result['archived_originals_supplied'],2)
        self.assertEqual(result['original_copies_examined'],9)
        self.assertEqual(result['unique_originals'],7)
        self.assertEqual(result['matching_duplicate_copies'],2)
        self.assertFalse(result['all_time_sources_exhausted'])
        self.assertFalse(result['safe_to_train'])
        self.assertFalse(result['safe_to_restart_writers'])
        self.assertTrue(any(x['progress']['event']=='SETTLED'
                            for x in packed[0]['items']))
        # The operation is read-only: all five original raw rows remain.
        with self.store.pool.connection() as c:
            n=c.execute("""SELECT COUNT(*) AS n FROM research_job
                WHERE idempotency_key LIKE 'demo/shadow/event/%'""").fetchone()['n']
        self.assertEqual(n,len(ids))

    def test_real_sql_page_and_changed_cold_payload_fails_closed(self):
        raw,packed,metadata,cold,_=self._supplied_sources()
        altered=deepcopy(cold)
        altered[0]['items'][0]['progress']['audit_label']='tampered'
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_hot_r2_overlap(
                raw,packed,[catalog([metadata])],
                {metadata['manifest_key']:altered})

    def test_missing_real_sql_page_rejected_even_with_valid_cold(self):
        raw,packed,metadata,cold,_=self._supplied_sources()
        # First page has a next cursor; dropping the terminal page must
        # never produce a plausible incomplete audit.
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_hot_r2_overlap(
                raw[:1],packed,[catalog([metadata])],
                {metadata['manifest_key']:cold})


if __name__=='__main__':
    unittest.main()
