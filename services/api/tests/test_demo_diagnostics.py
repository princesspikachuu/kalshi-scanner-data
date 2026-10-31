import unittest
from services.demo.diagnostics import exchange_issue,runtime_issue
from services.demo.exchange import ExchangeFailure
class Diagnostics(unittest.TestCase):
    def test_missing_order_names_phase_market_and_next_action(self):
        issue=exchange_issue(ExchangeFailure('exchange_rejected',status=404,provider_code='not_found'),'reconciliation',market='BTC',order_id='order-one')
        self.assertIn('saved order',issue['summary']);self.assertIn('Activity',issue['action'])
        self.assertEqual((issue['market'],issue['order_id'],issue['phase']),('BTC','order-one','reconciliation'))
    def test_authentication_and_ambiguous_writes_have_different_actions(self):
        self.assertEqual(exchange_issue(ExchangeFailure('authentication'),'trade')['control'],'connection')
        ambiguous=exchange_issue(ExchangeFailure('connection',True),'trade')
        self.assertEqual(ambiguous['control'],'activity');self.assertIn('will not be repeated',ambiguous['action'])
    def test_runtime_diagnostics_do_not_include_raw_exception_messages(self):
        issue=runtime_issue('stream',market='BTC')
        self.assertIn('price stream',issue['summary']);self.assertEqual(issue['code'],'runtime_recovery')
    def test_issue_is_published_on_state_change_and_cleared_after_verified_recovery(self):
        import threading
        from unittest.mock import patch
        from services.demo.runtime import Worker
        from services.api.tests.test_demo_engine import FakeStore
        store=FakeStore();exchange=type('Exchange',(),dict(reads=0,writes=0))()
        worker=Worker(store,exchange,threading.Event(),lambda:None)
        worker.issue=exchange_issue(ExchangeFailure('exchange_rejected',status=404,provider_code='not_found'),'reconciliation',market='BTC')
        with patch('services.demo.runtime.time.time',return_value=1000):worker.health('attention','Saved order missing')
        self.assertEqual(store.saved[-1][1]['issue']['market'],'BTC')
        with patch('services.demo.runtime.time.time',return_value=1001):worker.health('ready','Account verified')
        self.assertEqual(store.saved[-1][1]['state'],'ready');self.assertIsNone(store.saved[-1][1]['issue'])
