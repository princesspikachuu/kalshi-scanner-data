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
