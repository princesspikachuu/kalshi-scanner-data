"""Checkpoint-stage telemetry cannot change serialized state or commit behavior."""
import json
import shutil
import unittest
from unittest.mock import Mock, patch

from services.paper_demo.shadow.core import Engine, StrategyFleet
from services.paper_demo.shadow.storage import HostedAudit


class CheckpointStageCosts(unittest.TestCase):
    def test_metrics_do_not_modify_checkpoint_bytes_or_wallet(self):
        audit = HostedAudit(Mock(), lambda: None)
        self.addCleanup(shutil.rmtree, audit.path)
        audit.engine = Engine(audit, cash='1000.123')
        audit.fleet = StrategyFleet(audit.engine, [])
        audit.experiments = Mock()
        audit.experiments.state.return_value = dict(_summary={}, favorites=dict(state='preserved'))
        with patch('builtins.print') as output:
            first = audit.checkpoint_snapshot()
            second = audit.checkpoint_snapshot()
        self.assertEqual(first, second)
        self.assertEqual(str(audit.engine.wallet.cash), '1000.123')
        events = [json.loads(c.args[0]) for c in output.call_args_list
                  if c.args and isinstance(c.args[0], str)
                  and 'shadow_checkpoint_stage_cost' in c.args[0]]
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event['event'], 'shadow_checkpoint_stage_cost')
        self.assertEqual(event['samples'], 1)
        self.assertEqual(event['encoded_bytes'], first.get('bytes'))
        self.assertEqual(event['stored_bytes'], len(first.get('data', '')))
        for key in ('engine_state_ms', 'experiment_state_ms',
                    'packing_ms', 'total_ms', 'peak_packing_ms', 'peak_state_ms'):
            self.assertGreaterEqual(event[key], 0)
        self.assertFalse('wallet' in event or 'favorites' in event)
        for key in ('rss_before_bytes', 'rss_after_state_bytes',
                    'rss_after_pack_bytes', 'rss_capture_delta_bytes',
                    'rss_pack_delta_bytes'):
            self.assertIn(key, event)

    def test_unavailable_rss_does_not_interrupt_checkpoint(self):
        with patch('services.paper_demo.shadow.storage.current_rss_bytes',
                   return_value=None):
            audit = HostedAudit(Mock(), lambda: None)
            self.addCleanup(shutil.rmtree, audit.path)
            audit.engine = Engine(audit, cash='123.45')
            audit.fleet = StrategyFleet(audit.engine, [])
            with patch('builtins.print') as output:
                payload = audit.checkpoint_snapshot()
        self.assertIsInstance(payload, dict)
        event = next(json.loads(call.args[0]) for call in output.call_args_list
                     if call.args and isinstance(call.args[0],str)
                     and 'shadow_checkpoint_stage_cost' in call.args[0])
        self.assertIsNone(event['rss_before_bytes'])
        self.assertIsNone(event['rss_capture_delta_bytes'])
        self.assertIsNone(event['rss_pack_delta_bytes'])

    def test_stage_counters_are_bounded_and_reset_after_log(self):
        audit = HostedAudit(Mock(), lambda: None)
        self.addCleanup(shutil.rmtree, audit.path)
        audit.engine = Engine(audit, cash='1000')
        audit.fleet = StrategyFleet(audit.engine, [])
        audit.checkpoint_stage_log_at = float('inf')
        with patch('builtins.print'):
            for _ in range(3):
                audit.checkpoint_snapshot()
        self.assertEqual(audit.checkpoint_stage_profile['samples'], 3)
        self.assertLessEqual(len(audit.checkpoint_stage_profile), 7)
        audit.checkpoint_stage_log_at = 0
        with patch('builtins.print'):
            audit.checkpoint_snapshot()
        self.assertEqual(audit.checkpoint_stage_profile['samples'], 0)


if __name__ == '__main__':
    unittest.main()
