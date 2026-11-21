"""Safe, read-only scope sizes accompany successful full R2 backups only."""
import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock,patch

from services.demo.control_backup_v2 import (
    PART_FORMAT,backup_controls,canonical,collect_snapshot_spooled,digest_records,
)
from services.demo.shadow_prefix_boundary_guard import (
    KEY_COLLATION_SQL,BOUNDED_ABOVE_UPPER_SQL,
)


class BackupScopeTelemetryTests(unittest.TestCase):
    @staticmethod
    def row(key,idx):
        return dict(id='11111111-1111-1111-1111-%012d'%idx,
                    idempotency_key=key,
                    parameters={'private_token':'DO_NOT_LOG_PARAMETERS'},
                    progress={'secret':'DO_NOT_LOG_PROGRESS','count':idx})

    def test_complete_snapshot_reports_only_allowlisted_scope_counts_and_bytes(self):
        bot=self.row('demo/bot/one',1)
        shadow=self.row('demo/shadow/bot/two',2)
        shadow['parameters']['folder_id']='favorites'
        other_shadow=self.row('demo/shadow/bot/four',5)
        other_shadow['parameters']['folder_id']='favorites_statistics'
        write=self.row('live/write/three',3)
        singleton=self.row('demo/shadow/checkpoint',4)
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        def execute(sql,args=None):
            cur=MagicMock()
            if sql==KEY_COLLATION_SQL:
                cur.fetchone.return_value={'provider':'c','locale':'en_US.UTF-8'}
            elif sql==BOUNDED_ABOVE_UPPER_SQL:
                cur.fetchone.return_value=None
            elif 'FROM research_job' in sql:
                if 'idempotency_key=ANY' in sql:
                    cur.fetchall.return_value=[singleton]
                else:
                    cur.fetchall.return_value={
                        'demo/bot/':[bot],
                        'demo/shadow/bot/':[shadow,other_shadow],
                        'live/write/':[write],
                    }.get(args[0],[])
            return cur
        c.execute.side_effect=execute
        with patch('services.demo.control_backup_v2.tempfile.TemporaryFile',
                   return_value=BytesIO()):
            staged=collect_snapshot_spooled(pool)
        try:
            scope_sizes=staged['scope_sizes']
            self.assertEqual(set(scope_sizes),
                {'demo_bots','shadow_bots','live_writes','singletons'})
            records=[('demo_bots',bot),('shadow_bots',shadow),
                     ('shadow_bots',other_shadow),('live_writes',write),
                     ('singletons',singleton)]
            for name in scope_sizes:
                group=[r for label,r in records if label==name]
                sizes=[len(canonical(row))+1 for row in group]
                self.assertEqual(scope_sizes[name],dict(
                    records=len(group),bytes=sum(sizes),
                    largest_record_bytes=max(sizes)))
            split=staged['favorites_shadow_bot_sizes']
            for group,row in (('regular_favorites',shadow),
                              ('all_other_bots',other_shadow)):
                size=len(canonical(row))+1
                self.assertEqual(split[group],dict(
                    records=1,bytes=size,largest_record_bytes=size))
            self.assertEqual(sum(x['bytes'] for x in split.values()),
                             scope_sizes['shadow_bots']['bytes'])
            self.assertEqual(sum(x['records'] for x in split.values()),
                             scope_sizes['shadow_bots']['records'])
            self.assertNotIn('favorites_statistics',json.dumps(split))
            self.assertNotIn('DO_NOT_LOG',json.dumps(split))
            self.assertEqual(sum(s['bytes'] for s in scope_sizes.values()),
                             staged['staged_bytes'])
            self.assertEqual(sum(s['records'] for s in scope_sizes.values()),
                             staged['records'])
            self.assertEqual(staged['records'],5)
            self.assertEqual(staged['sha256'],
                             digest_records([bot,shadow,other_shadow,write,singleton]))
            self.assertNotIn('DO_NOT_LOG',json.dumps(scope_sizes))
            self.assertNotIn('demo/shadow/bot/two',json.dumps(scope_sizes))
        finally:
            staged['file'].close()

    def test_success_logs_scope_counts_but_does_not_modify_r2_root(self):
        row=self.row('demo/bot/private-abc',1)
        blob=canonical(dict(format=PART_FORMAT,count=1,records=[row]))
        staging=dict(file=BytesIO(len(blob).to_bytes(4,'big')+blob),records=1,
                     parts=1,sha256=digest_records([row]),
                     staged_bytes=len(canonical(row))+1,
                     scope_sizes={'demo_bots':dict(records=1,
                         bytes=len(canonical(row))+1,
                         largest_record_bytes=len(canonical(row))+1)},
                     favorites_shadow_bot_sizes={
                         'regular_favorites':dict(records=0,bytes=0,largest_record_bytes=0),
                         'all_other_bots':dict(records=0,bytes=0,largest_record_bytes=0)})
        refs=[dict(key='demo/backups/a',size=15,sha256='a'*64),
              dict(key='demo/backups/b',size=18,sha256='b'*64),
              dict(key='demo/backups/roots/c',size=22,sha256='c'*64)]
        store=MagicMock()
        with patch('services.demo.control_backup_v2.collect_snapshot_spooled',
                   return_value=staging),patch(
             'services.demo.control_backup_v2.put_verified',
             side_effect=refs) as upload,patch(
             'services.demo.control_backup_v2.verify_staged_archive',
             return_value=dict(records=1,sha256=digest_records([row]),chunks=1)),patch(
             'builtins.print') as emit:
            result=backup_controls(store,MagicMock(),now=101)
        self.assertTrue(result['verified'])
        self.assertEqual(result['scope_sizes'],staging['scope_sizes'])
        self.assertEqual(result['favorites_shadow_bot_sizes'],
                         staging['favorites_shadow_bot_sizes'])
        self.assertNotIn('scope_sizes',upload.call_args_list[1].args[2])
        self.assertNotIn('favorites_shadow_bot_sizes',upload.call_args_list[1].args[2])
        self.assertNotIn('scope_sizes',upload.call_args_list[2].args[2])
        self.assertNotIn('favorites_shadow_bot_sizes',upload.call_args_list[2].args[2])
        self.assertNotIn('scope_sizes',store.put.call_args.args[1])
        self.assertNotIn('favorites_shadow_bot_sizes',store.put.call_args.args[1])
        logged=emit.call_args.args[0]
        self.assertEqual(json.loads(logged)['scope_sizes'],staging['scope_sizes'])
        self.assertEqual(json.loads(logged)['favorites_shadow_bot_sizes'],
                         staging['favorites_shadow_bot_sizes'])
        self.assertNotIn('private-abc',logged)
        self.assertNotIn('DO_NOT_LOG',logged)
        self.assertTrue(staging['file'].closed)

    def test_failure_never_logs_sizes_or_publishes_verified_root(self):
        row=self.row('demo/bot/private',1)
        blob=canonical(dict(format=PART_FORMAT,count=1,records=[row]))
        staged=dict(file=BytesIO(len(blob).to_bytes(4,'big')+blob),records=1,
                    parts=1,sha256=digest_records([row]),staged_bytes=300,
                    scope_sizes={'demo_bots':dict(records=1,bytes=300,
                                                  largest_record_bytes=300)})
        store=MagicMock()
        with patch('services.demo.control_backup_v2.collect_snapshot_spooled',
                   return_value=staged),patch(
             'services.demo.control_backup_v2.put_verified',
             side_effect=[dict(key='part',size=15),dict(key='root',size=18)]) as upload,patch(
             'services.demo.control_backup_v2.verify_staged_archive',
             side_effect=ValueError('Control backup root digest or count mismatch')),patch(
             'builtins.print') as emit:
            with self.assertRaisesRegex(ValueError,'root digest'):
                backup_controls(store,MagicMock(),now=101)
        self.assertEqual(upload.call_count,2)
        store.put.assert_not_called()
        emit.assert_not_called()
        self.assertTrue(staged['file'].closed)


if __name__=='__main__':
    unittest.main()
