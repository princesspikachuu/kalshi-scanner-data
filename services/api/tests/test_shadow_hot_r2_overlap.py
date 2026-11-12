"""MT-019 offline hot/R2 overlap tests: no SQL, R2 or trading I/O."""
import unittest
from copy import deepcopy
from uuid import uuid4

from services.api.tests.test_shadow_catalog_r2_crosscheck import evidence, catalog
from services.api.tests.test_shadow_history_reconcile import event
from services.demo.shadow_hot_r2_overlap import audit_supplied_hot_r2_overlap
from services.demo.shadow_history_reconcile import HistoryReconciliationError


def hot(source, originals=(), *, cursor=None, more=False):
    originals=list(originals)
    prefix=('demo/shadow/event/' if source=='raw'
            else 'demo/shadow/event-batch/')
    if source=='raw':
        keys=[x['key'] for x in originals]
    else:
        keys=[prefix+str(uuid4())] if originals else []
        for original in originals:
            original['packed_batch_key']=keys[0]
    return dict(source=source,order='idempotency_key_ascending',
                request_cursor=cursor,items=originals,
                source_keys=keys,source_rows=len(keys),
                original_events=len(originals),more=more,
                next_cursor=keys[-1] if more and keys else None)


def case():
    m, cold=evidence('raw',2)
    # Copy an already verified original from a cold manifest back into hot
    # PostgreSQL: this is the expected behavior before verified reclaim.
    common=deepcopy(cold[0]['items'][0])
    raw=hot('raw',[common])
    packed=hot('packed',[event()])
    return raw,packed,m,cold


class BoundedHotR2OverlapTests(unittest.TestCase):
    def test_matching_hot_and_cold_copy_deduplicates(self):
        raw,packed,m,cold=case()
        out=audit_supplied_hot_r2_overlap(
            [raw],[packed],[catalog([m])],{m['manifest_key']:cold})
        self.assertEqual(out['original_copies_examined'],4)
        self.assertEqual(out['unique_originals'],3)
        self.assertEqual(out['matching_duplicate_copies'],1)
        self.assertEqual(out['archived_manifests_supplied'],1)
        for key in ('all_time_sources_exhausted','all_time_coverage_complete',
                    'stable_postgres_snapshot_verified',
                    'independently_authenticated_r2_reads','safe_to_train',
                    'safe_to_restart_writers','realized_pnl_reconciled'):
            self.assertFalse(out[key])

    def test_conflicting_hot_r2_original_fails(self):
        raw,packed,m,cold=case()
        changed=deepcopy(raw)
        changed['items'][0]['progress']['new']='changed'
        with self.assertRaisesRegex(HistoryReconciliationError,'Conflicting'):
            audit_supplied_hot_r2_overlap(
                [changed],[packed],[catalog([m])],{m['manifest_key']:cold})

    def test_hot_key_collision_under_distinct_original_id_fails(self):
        raw,packed,m,cold=case()
        changed=deepcopy(raw)
        changed['items'][0]['id']=str(uuid4())
        with self.assertRaisesRegex(HistoryReconciliationError,'key reused'):
            audit_supplied_hot_r2_overlap(
                [changed],[packed],[catalog([m])],{m['manifest_key']:cold})

    def test_raw_source_key_mismatch_refused(self):
        raw,packed,m,cold=case()
        changed=deepcopy(raw)
        changed['source_keys']=['demo/shadow/event/not-the-original']
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_hot_r2_overlap(
                [changed],[packed],[catalog([m])],{m['manifest_key']:cold})

    def test_packed_batch_provenance_mismatch_refused(self):
        raw,packed,m,cold=case()
        changed=deepcopy(packed)
        changed['items'][0]['packed_batch_key']='demo/shadow/event-batch/wrong'
        with self.assertRaisesRegex(HistoryReconciliationError,'batch key mismatch'):
            audit_supplied_hot_r2_overlap(
                [raw],[changed],[catalog([m])],{m['manifest_key']:cold})

    def test_missing_hot_terminal_page_refused(self):
        raw,packed,m,cold=case()
        changed=deepcopy(raw)
        changed['more']=True
        changed['next_cursor']=changed['source_keys'][-1]
        with self.assertRaisesRegex(HistoryReconciliationError,'more indexed pages'):
            audit_supplied_hot_r2_overlap(
                [changed],[packed],[catalog([m])],{m['manifest_key']:cold})

    def test_unverified_r2_readback_is_rejected(self):
        raw,packed,m,cold=case()
        changed=deepcopy(cold)
        changed[0]['verified']=False
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_hot_r2_overlap(
                [raw],[packed],[catalog([m])],{m['manifest_key']:changed})

    def test_missing_catalog_readback_rejected(self):
        raw,packed,m,cold=case()
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_hot_r2_overlap([raw],[packed],[catalog([m])],{})

    def test_empty_hot_sources_and_empty_catalog_are_not_full_history(self):
        result=audit_supplied_hot_r2_overlap(
            [hot('raw')],[hot('packed')],[catalog([])],{})
        self.assertEqual(result['unique_originals'],0)
        self.assertFalse(result['all_time_sources_exhausted'])

    def test_bounded_input_refuses_oversized_hot_page(self):
        raw,packed,m,cold=case()
        excessive=hot('raw',[event() for _ in range(5)])
        excessive['items'].sort(key=lambda x:x['key'])
        excessive['source_keys']=[x['key'] for x in excessive['items']]
        with self.assertRaises(HistoryReconciliationError):
            audit_supplied_hot_r2_overlap(
                [excessive],[packed],[catalog([m])],{m['manifest_key']:cold})


if __name__=='__main__':
    unittest.main()
