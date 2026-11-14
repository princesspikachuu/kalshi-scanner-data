"""Exclusive-mode handover rejects cached resumes and unverified exposure."""
import threading,unittest
from unittest.mock import Mock,MagicMock,patch
from services.trading.mode import complete_demo_drain,require_demo,ModeConflict
from services.api.tests.test_demo_cycles import worker,entry

class TradingModeTests(unittest.TestCase):
    def test_resume_requires_demo_under_transaction_lock(self):
        for mode in ('draining_demo','live','draining_live','unknown'):
            c=Mock();c.execute.return_value.fetchone.return_value=dict(progress=dict(mode=mode))
            with self.subTest(mode=mode),self.assertRaises(ModeConflict):require_demo(c)
            self.assertIn('pg_advisory_xact_lock',c.execute.call_args_list[0].args[0])
        c=Mock();c.execute.return_value.fetchone.return_value=None;require_demo(c)
        c.execute.return_value.fetchone.return_value=dict(progress=dict(mode='demo'));require_demo(c)
    def draining_worker(self):
        w=worker();w.store.pool=MagicMock();w.exchange=Mock();w.exchange.pages.return_value=[]
        w.bots[0]['desired']='paused';w.last_reconcile=200;w.guard=Mock()
        return w
    def test_no_handover_until_reconciliation_postdates_pause(self):
        w=self.draining_worker();w.last_reconcile=99
        with patch('services.trading.mode.read_mode',return_value=dict(mode='draining_demo',requested='live',drain_started_at=100)):
            self.assertFalse(complete_demo_drain(w))
        w.exchange.pages.assert_not_called()
    def test_manual_orders_and_unsettled_positions_block_handover(self):
        for orders,positions in [([dict(order_id='manual')],[]),([],[dict(position_fp='0.01')])]:
            w=self.draining_worker();w.exchange.pages.side_effect=[orders,positions]
            with self.subTest(orders=orders,positions=positions),patch('services.trading.mode.read_mode',return_value=dict(mode='draining_demo',requested='live',drain_started_at=100)):
                self.assertFalse(complete_demo_drain(w))
            w.store.pool.connection.assert_not_called()
    def test_expired_ambiguous_intent_still_blocks_handover(self):
        w=self.draining_worker();w.orders=[entry(status='uncertain',close=1,remaining=0)]
        with patch('services.trading.mode.read_mode',return_value=dict(mode='draining_demo',requested='live',drain_started_at=100)):
            self.assertFalse(complete_demo_drain(w))
        w.exchange.pages.assert_not_called()
    def test_recovery_failure_never_completes_handover(self):
        w=self.draining_worker();w.recovered=False
        with patch('services.trading.mode.read_mode',return_value=dict(mode='draining_demo',requested='live',drain_started_at=100)):
            self.assertFalse(complete_demo_drain(w))
        w.exchange.pages.assert_not_called()
    def test_cached_single_and_batch_entries_cannot_write_after_pause(self):
        w=worker();w.store.pool=MagicMock();w.exchange=Mock();intent=entry()
        with patch('services.trading.mode.read_mode',return_value=dict(mode='draining_demo')):
            from services.demo.runtime import Worker
            self.assertFalse(Worker.submit(w,intent))
            self.assertFalse(w.submit_entry_batch([intent]))
        w.exchange.submit.assert_not_called();w.exchange.submit_batch.assert_not_called()

    def test_flat_verified_demo_commits_handover_with_live_bots_still_paused(self):
        w=self.draining_worker();state=dict(mode='draining_demo',requested='live',drain_started_at=100)
        c=w.store.pool.connection.return_value.__enter__.return_value
        c.execute.return_value.fetchone.return_value=dict(progress=state)
        with patch('services.trading.mode.read_mode',return_value=state),patch('services.trading.mode.write_mode') as write:
            self.assertTrue(complete_demo_drain(w))
        self.assertEqual(write.call_args.args[1]['mode'],'live');w.guard.assert_called_once()
        self.assertEqual(len(w.exchange.pages.call_args_list),2)
        self.assertFalse(any('UPDATE research_job' in str(call) for call in c.execute.call_args_list))
    def test_nonflat_drain_checks_once_per_reconciled_snapshot(self):
        w=self.draining_worker();w.exchange.pages.side_effect=[[dict(order_id='manual')],[]]
        with patch('services.trading.mode.read_mode',return_value=dict(mode='draining_demo',requested='live',drain_started_at=100)):
            self.assertFalse(complete_demo_drain(w));self.assertFalse(complete_demo_drain(w))
        self.assertEqual(w.exchange.pages.call_count,2)
    def test_demo_loop_makes_no_exchange_calls_when_live_owns_worker(self):
        w=self.draining_worker();w.store.get=Mock(return_value=None)
        w.health=Mock(side_effect=lambda *args:w.stop.set());w.close_stream=Mock()
        w.stream=Mock();w.discover=Mock();w.poll_funding=Mock()
        with patch('services.trading.mode.read_mode',return_value=dict(mode='live',requested='live')),patch('services.demo.reset.ResetController'):
            w.loop()
        w.exchange.call.assert_not_called();w.exchange.pages.assert_not_called()
        w.stream.assert_not_called();w.discover.assert_not_called();w.poll_funding.assert_not_called()

    def test_verified_closed_flat_history_does_not_block_exclusive_handover(self):
        w=self.draining_worker();w.orders=[entry(status='uncertain',close=1,remaining=0)]
        w.quotes['t'].update(status='settled',close=1,metadata_at=200)
        w.ownership_details['t']=dict(informational=True,expected_contracts=0,exchange_contracts=0)
        state=dict(mode='draining_demo',requested='live',drain_started_at=100)
        c=w.store.pool.connection.return_value.__enter__.return_value
        c.execute.return_value.fetchone.return_value=dict(progress=state)
        with patch('services.trading.mode.read_mode',return_value=state),patch('services.trading.mode.write_mode') as write:
            self.assertTrue(complete_demo_drain(w))
        self.assertEqual(write.call_args.args[1]['mode'],'live');self.assertEqual(w.exchange.pages.call_count,2)
        self.assertEqual(w.orders[0]['status'],'uncertain','Historical evidence is retained')
    def test_historical_label_does_not_hide_unverified_market_or_inventory(self):
        for changes,detail in [(dict(status='active'),dict(informational=True,expected_contracts=0,exchange_contracts=0)),(dict(status='closed'),dict(informational=True,expected_contracts=1,exchange_contracts=0))]:
            w=self.draining_worker();w.orders=[entry(status='uncertain',close=1,remaining=0)]
            w.quotes['t'].update(changes);w.ownership_details['t']=detail
            with patch('services.trading.mode.read_mode',return_value=dict(mode='draining_demo',requested='live',drain_started_at=100)):
                self.assertFalse(complete_demo_drain(w))
            w.exchange.pages.assert_not_called()
