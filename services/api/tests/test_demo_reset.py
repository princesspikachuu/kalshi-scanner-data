import unittest
from unittest.mock import MagicMock,patch
from services.demo.reset import ResetController,ResetRequest

class Reset(unittest.TestCase):
    def test_old_cached_request_fields_remain_accepted(self):
        body=ResetRequest.model_validate(dict(request_id='00000000-0000-0000-0000-000000000001',fresh_bots=False,target_balance_cents=100000))
        self.assertEqual(body.target_balance_cents,100000)
    def test_legacy_funding_wait_finishes_without_exchange_calls_or_lost_receipt(self):
        store=MagicMock();exchange=MagicMock();connection=store.pool.connection.return_value.__enter__.return_value
        current=dict(parameters=dict(sources=[]),progress=dict(state='awaiting_funds',pending=dict(client_id='unresolved-sale'),cloned=True))
        connection.execute.return_value.fetchone.return_value=current
        row=dict(current)
        with patch('services.demo.reset.archive_bots') as archive:ResetController(store,exchange).step(row)
        exchange.assert_not_called();self.assertEqual(exchange.mock_calls,[])
        self.assertEqual(row['progress']['state'],'complete')
        self.assertEqual(row['progress']['pending'],dict(client_id='unresolved-sale'))
        archive.assert_called_once()


class UndoRecentReset(unittest.TestCase):
    def prepare(self,*,used=False):
        from services.demo.reset import ACCIDENT_RUNNING_CATEGORIES
        import time
        from uuid import uuid4
        now=time.time();request_id=str(uuid4())
        sources=[]
        for i,asset in enumerate(sorted(ACCIDENT_RUNNING_CATEGORIES)):
            sources.append(dict(old=f'old-{i}',new=f'copy-{i}',
                config=dict(name=f'Bot {asset}',strategy='buy_low_sell_high',squares=[dict(asset=asset)])))
        params=dict(request_id=request_id,mode='archive_copy',sources=sources,requested_at=now-10)
        reset=dict(parameters=params,progress=dict(state='complete',completed_at=now-8))
        rows=[]
        for src in sources:
            rows.append(dict(idempotency_key='demo/bot/'+src['old'],
                parameters=dict(config=src['config'],revision=1),
                progress=dict(archived=True,desired='paused',message='Archived')))
            rows.append(dict(idempotency_key='demo/bot/'+src['new'],
                parameters=dict(reset_source=src['old'],revision=1,config=dict(src['config'],name=src['config']['name'][:72]+' · fresh')),
                progress=dict(archived=False,desired='paused',message='Fresh statistics; ready to resume')))
        from unittest.mock import Mock
        store=MagicMock();c=store.pool.connection.return_value.__enter__.return_value
        updates=[]
        def execute(sql,params=()):
            updates.append((sql,params))
            result=Mock()
            if "SELECT parameters,progress FROM research_job WHERE idempotency_key='demo/reset'" in sql:
                result.fetchone.return_value=reset
            elif 'SELECT idempotency_key,parameters,progress FROM research_job' in sql:
                result.fetchall.return_value=rows
            elif 'SELECT 1 FROM research_job' in sql:
                result.fetchone.return_value={'id':1} if used else None
            return result
        c.execute.side_effect=execute
        return store,reset,updates

    def test_accidental_reset_restores_all_28_previously_running_originals_and_removes_unused_copies(self):
        from services.demo.reset import undo_reset
        store,row,queries=self.prepare()
        result=undo_reset(store,row['parameters']['request_id'],incident=True)
        self.assertEqual((result['restored'],result['resumed']),(28,28))
        original=[(p[0],p[1]) for sql,p in queries if sql.startswith('UPDATE research_job SET progress=') and len(p)>1 and p[1].startswith('demo/bot/')]
        self.assertEqual(len(original),28)
        self.assertTrue(all(progress.obj['desired']=='running' and not progress.obj['archived'] for progress,key in original))
        deletion=[p for sql,p in queries if sql.startswith('DELETE FROM research_job')]
        self.assertEqual(len(deletion),1)
        self.assertEqual(len(deletion[0][0]),28)
        self.assertTrue(all(key.startswith('demo/bot/copy-') for key in deletion[0][0]))

    def test_post_reset_trades_prevent_undo_without_any_mutation(self):
        from services.demo.reset import undo_reset,ResetConflict
        store,row,queries=self.prepare(used=True)
        with self.assertRaises(ResetConflict):undo_reset(store,row['parameters']['request_id'],incident=True)
        self.assertFalse(any(sql.startswith('UPDATE research_job') or sql.startswith('DELETE FROM research_job') for sql,p in queries))

    def test_wrong_request_id_or_old_reset_never_restores_bots(self):
        from services.demo.reset import undo_reset,ResetConflict
        from uuid import uuid4
        store,row,queries=self.prepare()
        with self.assertRaises(ResetConflict):undo_reset(store,str(uuid4()),incident=True)
        self.assertFalse(any(sql.startswith('UPDATE research_job') for sql,p in queries))
        row['parameters']['requested_at']-=7200
        with self.assertRaises(ResetConflict):undo_reset(store,row['parameters']['request_id'],incident=True)

    def test_cached_client_cannot_request_reset_without_typed_confirmation(self):
        from services.demo.reset import ResetRequest,request_reset,ResetConflict
        store=MagicMock()
        request=ResetRequest.model_validate(dict(request_id='00000000-0000-0000-0000-000000000001'))
        with self.assertRaises(ResetConflict):request_reset(store,request)
        store.pool.connection.assert_not_called()

    def test_incident_undo_is_tightly_time_scoped(self):
        from services.demo.reset import undo_recent_incident
        store,row,queries=self.prepare()
        store.get.return_value=row
        self.assertFalse(undo_recent_incident(store))
        self.assertFalse(any(sql.startswith('UPDATE research_job') for sql,p in queries))
