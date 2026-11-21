"""Real compressed object readback validates mixed-epoch R2 chunk lineage."""
import json
import unittest
from io import BytesIO
from unittest.mock import patch

from services.demo.control_backup_v2 import (
    PART_FORMAT,backup_controls,canonical,digest_records,
    verify_staged_archive,restore_verified_snapshot,
)
from services.demo.maintenance import read_verified


MODULE='services.demo.control_backup_v2'


class InMemoryR2:
    bucket='test'
    def __init__(self):
        self.client=self
        self.entries={}
        self.put_keys=[]
    def put_object(self,*,Bucket,Key,Body,ContentType,IfNoneMatch):
        assert Bucket==self.bucket and ContentType=='application/gzip'
        assert IfNoneMatch=='*'
        if Key in self.entries:
            error=RuntimeError('immutable object exists')
            error.response={'ResponseMetadata':{'HTTPStatusCode':412}}
            raise error
        self.entries[Key]=Body
        self.put_keys.append(Key)
    def get_object(self,*,Bucket,Key):
        assert Bucket==self.bucket
        body=self.entries[Key]
        return dict(ContentLength=len(body),Body=BytesIO(body))


class HealthStore:
    pool=None
    def __init__(self):
        self.state={}
        self.writes=[]
    def put(self,key,data):
        self.state[key]=data
        self.writes.append((key,data))
    def get(self,key):
        return {'progress':self.state[key]} if key in self.state else None


def row(idx=1):
    return dict(id='11111111-1111-1111-1111-%012d'%idx,
                idempotency_key='demo/shadow/bot/secret-%d'%idx,
                parameters={'private':'NO_LOG_PARAMETERS'},
                progress={'private':'NO_LOG_PROGRESS','ordinal':idx})


def staged(rows):
    data=canonical(dict(format=PART_FORMAT,count=len(rows),records=rows))
    return dict(file=BytesIO(len(data).to_bytes(4,'big')+data),
                records=len(rows),parts=1,sha256=digest_records(rows),
                staged_bytes=sum(len(canonical(r))+1 for r in rows),
                scope_sizes={'shadow_bots':dict(records=len(rows),
                    bytes=sum(len(canonical(r))+1 for r in rows),
                    largest_record_bytes=max(len(canonical(r))+1 for r in rows))})


class FullReuseReadbackTests(unittest.TestCase):
    def test_prior_part_is_not_rewritten_but_is_verified_in_new_root(self):
        objects=InMemoryR2();store=HealthStore()
        rows=[row()]
        first=staged(rows)
        with patch(MODULE+'.collect_snapshot_spooled',return_value=first),patch(
             'builtins.print') as log:
            result1=backup_controls(store,objects,now=100)
        self.assertTrue(first['file'].closed)
        self.assertTrue(result1['verified'])
        self.assertEqual(result1['chunks'],1)
        self.assertEqual(len(objects.put_keys),3)
        old_health=store.state['backup-health']
        old_root=read_verified(objects,old_health['reference'])
        old_part=old_root['chunks'][0]['reference']
        old_part_bytes=objects.entries[old_part['key']]

        second=staged(rows)
        with patch(MODULE+'.collect_snapshot_spooled',return_value=second),patch(
             'builtins.print') as emit:
            result2=backup_controls(store,objects,now=200,reuse_previous=True)
        self.assertTrue(second['file'].closed)
        self.assertTrue(result2['verified'])
        self.assertTrue(result2['catalog_stored'])
        self.assertEqual(result2['reused_chunks'],1)
        self.assertEqual(result2['new_chunks'],0)
        self.assertFalse(result2['reuse_source_unavailable'])
        self.assertEqual(result2['reused_bytes'],len(old_part_bytes))
        self.assertEqual(len(objects.put_keys),5)  # only new root and catalog
        new_health=store.state['backup-health']
        new_root=read_verified(objects,new_health['reference'])
        self.assertEqual(new_root['chunks'][0]['reference'],old_part)
        self.assertEqual(objects.entries[old_part['key']],old_part_bytes)
        self.assertEqual(verify_staged_archive(objects,new_health['reference'])[
                         'sha256'],digest_records(rows))
        self.assertEqual(len(store.writes),2)
        self.assertTrue(all(key=='backup-health' for key,_ in store.writes))
        self.assertNotIn('NO_LOG',emit.call_args.args[0])
        self.assertNotIn('secret-1',emit.call_args.args[0])

    def test_missing_reused_chunk_fails_before_catalog_and_health_publication(self):
        objects=InMemoryR2();store=HealthStore()
        rows=[row(1)]
        first=staged(rows)
        with patch(MODULE+'.collect_snapshot_spooled',return_value=first),patch(
             'builtins.print'):
            backup_controls(store,objects,now=100)
        original_health=store.state['backup-health']
        old_root=read_verified(objects,original_health['reference'])
        part_key=old_root['chunks'][0]['reference']['key']
        del objects.entries[part_key]  # simulate lost/corrupt immutable object
        old_count=len(objects.put_keys)
        second=staged(rows)
        with patch(MODULE+'.collect_snapshot_spooled',return_value=second),patch(
             'builtins.print') as output:
            with self.assertRaises(KeyError):
                backup_controls(store,objects,now=200,reuse_previous=True)
        self.assertTrue(second['file'].closed)
        # A new unverified root is harmless, but no independent recovery
        # catalog or backup-health marker can be published for it.
        self.assertEqual(len(objects.put_keys),old_count+1)
        self.assertEqual(store.state['backup-health'],original_health)
        self.assertEqual(len(store.writes),1)
        output.assert_not_called()


    def test_expiring_old_root_must_keep_reused_chunk(self):
        """Older root/catalog may expire; their shared part must not expire."""
        objects=InMemoryR2();store=HealthStore()
        rows=[row(7)]
        first=staged(rows)
        with patch('builtins.print'):
            backup_controls(store,objects,now=100)
        old_health=dict(store.state['backup-health'])
        old_root=read_verified(objects,old_health['reference'])
        shared_part=old_root['chunks'][0]['reference']

        second=staged(rows)
        with patch('builtins.print'):
            result=backup_controls(store,objects,now=200,
                                   reuse_previous=True)
        self.assertEqual(result['reused_chunks'],1)
        new_health=dict(store.state['backup-health'])
        new_root=read_verified(objects,new_health['reference'])
        self.assertEqual(new_root['chunks'][0]['reference'],shared_part)

        # A retention policy can drop an expired old root and its independent
        # catalog without affecting the latest complete verified snapshot.
        del objects.entries[old_health['reference']['key']]
        del objects.entries[old_health['catalog_reference']['key']]
        self.assertEqual(restore_verified_snapshot(
            objects,new_health['reference']),rows)

        # An AGE-ONLY policy that also expires the old part would corrupt
        # a *newer* verified root. This deliberately proves the activation
        # gate: old shared parts need reference-aware retention.
        del objects.entries[shared_part['key']]
        with self.assertRaises(KeyError):
            restore_verified_snapshot(objects,new_health['reference'])
        self.assertEqual(store.state['backup-health'],new_health)


if __name__=='__main__':
    unittest.main()
