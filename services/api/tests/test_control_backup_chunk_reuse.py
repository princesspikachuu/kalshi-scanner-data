"""An opt-in backup may reuse immutable chunks but never skip R2 readback."""
import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock,patch

from services.demo.control_backup_chunk_reuse import (
    CATALOG_FORMAT,FORMAT,exact_part_fingerprint,
    matching_reference,prior_verified_chunks,
)
from services.demo.control_backup_v2 import (
    PART_FORMAT,backup_controls,canonical,digest_records,
)


MOD='services.demo.control_backup_v2'
REUSE='services.demo.control_backup_chunk_reuse'


def ref(digest,size,*,catalog=False):
    namespace='demo/backups/roots/' if catalog else 'demo/backups/'
    return dict(key=namespace+digest+'.json.gz',sha256=digest,size=size,at=17)


def record(index=1):
    return dict(id='11111111-1111-1111-1111-%012d'%index,
                idempotency_key='live/write/private-key-%d'%index,
                parameters={'account_private':'SECRET_PARAMETERS'},
                progress={'private_value':'SECRET_PROGRESS','done':False})


def snapshot(rows):
    part=dict(format=PART_FORMAT,count=len(rows),records=rows)
    blob=canonical(part)
    return dict(file=BytesIO(len(blob).to_bytes(4,'big')+blob),
                records=len(rows),parts=1,
                sha256=digest_records(rows),staged_bytes=len(blob))


def old_root_for(part):
    chunk_digest,chunk_size=exact_part_fingerprint(part)
    chunk=ref(chunk_digest,chunk_size)
    root=ref('a'*64,500)
    receipt=ref('b'*64,200,catalog=True)
    digest='f'*64
    root_contents=dict(format=FORMAT,records=part['count'],
                       sha256=digest,chunks=[
                           dict(reference=chunk,count=part['count'])])
    catalog=dict(format=CATALOG_FORMAT,root_reference=root,
                 records=part['count'],chunks=1,snapshot_sha256=digest)
    state=dict(progress=dict(format=FORMAT,verified=True,
                reference=root,catalog_reference=receipt,
                records=part['count']))
    return chunk,root_contents,catalog,state


class ReusedBackupTests(unittest.TestCase):
    def test_catalog_lineage_and_exact_compressed_part_identity(self):
        rows=[record()]
        part=dict(format=PART_FORMAT,count=1,records=rows)
        chunk,root,catalog,health=old_root_for(part)
        store=MagicMock()
        store.get.return_value=health
        with patch(REUSE+'.read_verified',side_effect=[catalog,root]) as read:
            candidates=prior_verified_chunks(store,MagicMock())
        self.assertEqual(read.call_count,2)
        self.assertEqual(set(candidates),{chunk['sha256']})
        self.assertEqual(matching_reference(part,candidates),chunk)
        self.assertIsNone(matching_reference(
            dict(part,records=[record(2)]),candidates))
        self.assertIsNone(matching_reference(part,dict(
            candidates,**{chunk['sha256']:dict(chunk,size=1)})))
        self.assertIsNone(matching_reference(part,{}))

    def test_no_candidates_for_absent_or_legacy_backup(self):
        store=MagicMock()
        store.get.return_value=None
        self.assertEqual(prior_verified_chunks(store,MagicMock()),{})
        store.get.return_value=dict(progress=dict(format='old',verified=True))
        self.assertEqual(prior_verified_chunks(store,MagicMock()),{})

    def test_bad_catalog_or_chunk_cannot_be_reused(self):
        part=dict(format=PART_FORMAT,count=1,records=[record()])
        chunk,root,catalog,health=old_root_for(part)
        store=MagicMock()
        store.get.return_value=health
        for replacement in (
                dict(catalog,root_reference=ref('c'*64,500)),
                dict(catalog,chunks=2),
                dict(catalog,snapshot_sha256='0'*64)):
            with self.subTest(replacement=replacement):
                with patch(REUSE+'.read_verified',
                           side_effect=[replacement,root]):
                    with self.assertRaisesRegex(ValueError,'reuse root mismatch'):
                        prior_verified_chunks(store,MagicMock())
        badroot=dict(root,chunks=[dict(reference=dict(chunk,size=True),
                                       count=1)])
        with patch(REUSE+'.read_verified',side_effect=[catalog,badroot]):
            with self.assertRaisesRegex(ValueError,'reuse part invalid'):
                prior_verified_chunks(store,MagicMock())

    def test_unchanged_chunk_reuses_verified_reference_without_put(self):
        rows=[record()]
        part=dict(format=PART_FORMAT,count=1,records=rows)
        chunk,root,catalog,health=old_root_for(part)
        staging=snapshot(rows)
        store=MagicMock()
        store.get.return_value=health
        newly_written=[ref('c'*64,500),ref('d'*64,150,catalog=True)]
        with patch(MOD+'.collect_snapshot_spooled',return_value=staging),patch(
                REUSE+'.read_verified',side_effect=[catalog,root]),patch(
                MOD+'.put_verified',side_effect=newly_written) as put,patch(
                MOD+'.verify_staged_archive',
                return_value=dict(records=1,sha256=digest_records(rows),
                                  chunks=1)) as verify,patch(
                'builtins.print') as output:
            result=backup_controls(store,MagicMock(),now=456,reuse_previous=True)
        self.assertTrue(staging['file'].closed)
        self.assertEqual(result['reused_chunks'],1)
        self.assertEqual(result['new_chunks'],0)
        self.assertEqual(result['reused_bytes'],chunk['size'])
        self.assertFalse(result['reuse_source_unavailable'])
        self.assertEqual(put.call_count,2)
        self.assertEqual(put.call_args_list[0].args[1],'backups')
        self.assertEqual(put.call_args_list[0].args[2]['chunks'][0]['reference'],chunk)
        self.assertEqual(put.call_args_list[1].args[1],'backups/roots')
        self.assertEqual(verify.call_count,1)
        self.assertEqual(store.put.call_args.args[0],'backup-health')
        logged=output.call_args.args[0]
        self.assertEqual(json.loads(logged)['reused_chunks'],1)
        self.assertNotIn('SECRET',logged)
        self.assertNotIn('private-key',logged)

    def test_changed_part_is_uploaded_and_fully_verified(self):
        old_part=dict(format=PART_FORMAT,count=1,records=[record()])
        chunk,root,catalog,health=old_root_for(old_part)
        rows=[record(2)]
        staging=snapshot(rows)
        store=MagicMock()
        store.get.return_value=health
        newref=ref('c'*64,100)
        roots=[newref,ref('d'*64,300),ref('e'*64,150,catalog=True)]
        with patch(MOD+'.collect_snapshot_spooled',return_value=staging),patch(
                REUSE+'.read_verified',side_effect=[catalog,root]),patch(
                MOD+'.put_verified',side_effect=roots) as put,patch(
                MOD+'.verify_staged_archive',
                return_value=dict(records=1,sha256=digest_records(rows),chunks=1)):
            result=backup_controls(store,MagicMock(),reuse_previous=True)
        self.assertEqual(put.call_count,3)
        self.assertEqual(result['reused_chunks'],0)
        self.assertEqual(result['new_chunks'],1)
        self.assertTrue(staging['file'].closed)

    def test_unavailable_old_root_falls_back_to_full_verified_write(self):
        rows=[record()]
        staging=snapshot(rows)
        store=MagicMock()
        with patch(MOD+'.collect_snapshot_spooled',return_value=staging),patch(
                REUSE+'.prior_verified_chunks',side_effect=RuntimeError(
                    'PRIVATE OLD ROOT ERROR')),patch(
                MOD+'.put_verified',side_effect=[
                    ref('c'*64,100),ref('d'*64,500),
                    ref('e'*64,200,catalog=True)]) as put,patch(
                MOD+'.verify_staged_archive',return_value=dict(
                    records=1,sha256=digest_records(rows),chunks=1)),patch(
                'builtins.print') as output:
            result=backup_controls(store,MagicMock(),reuse_previous=True)
        self.assertEqual(put.call_count,3)
        self.assertTrue(result['reuse_source_unavailable'])
        messages=[c.args[0] for c in output.call_args_list]
        self.assertEqual(len(messages),2)
        self.assertNotIn('PRIVATE OLD ROOT ERROR',''.join(messages))
        self.assertTrue(staging['file'].closed)

    def test_reused_missing_or_corrupt_object_aborts_without_recovery_catalog(self):
        rows=[record()]
        part=dict(format=PART_FORMAT,count=1,records=rows)
        chunk,root,catalog,health=old_root_for(part)
        staging=snapshot(rows)
        store=MagicMock()
        store.get.return_value=health
        with patch(MOD+'.collect_snapshot_spooled',return_value=staging),patch(
                REUSE+'.read_verified',side_effect=[catalog,root]),patch(
                MOD+'.put_verified',return_value=ref('c'*64,500)) as put,patch(
                MOD+'.verify_staged_archive',side_effect=ValueError(
                    'Archive verification failed')),patch(
                'builtins.print') as output:
            with self.assertRaisesRegex(ValueError,'Archive verification'):
                backup_controls(store,MagicMock(),reuse_previous=True)
        self.assertEqual(put.call_count,1)  # unverified root only
        store.put.assert_not_called()
        output.assert_not_called()
        self.assertTrue(staging['file'].closed)


if __name__=='__main__':
    unittest.main()
