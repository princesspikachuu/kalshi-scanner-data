"""Startup must never restart on an optional read-only bot catalog timeout."""
import json
import unittest
from threading import Event
from unittest.mock import MagicMock,Mock,call,patch

from psycopg.errors import QueryCanceled

from services.paper_demo.shadow.bot_catalog import BotCatalogCapacityError
from services.paper_demo.shadow.host import (
    ShadowStartupStopped,load_startup_controls,run,
)


MODULE='services.paper_demo.shadow.host'


class StartupCatalogRetryTests(unittest.TestCase):
    def test_two_transient_timeouts_retry_and_return_only_complete_catalog(self):
        rows=[dict(parameters=dict(id='bot-a'),progress=dict(desired='paused'))]
        stop=Mock()
        stop.wait.return_value=False
        with patch(MODULE+'.load_bots',side_effect=[
                   QueryCanceled('statement timeout'),
                   QueryCanceled('statement timeout'),rows]) as reader,patch(
                   'builtins.print') as output:
            result=load_startup_controls(MagicMock(),stop)
        self.assertIs(result,rows)
        self.assertEqual(reader.call_count,3)
        stop.wait.assert_has_calls([call(2),call(2)])
        self.assertEqual(stop.wait.call_count,2)
        records=[json.loads(c.args[0]) for c in output.call_args_list]
        self.assertEqual([r['event'] for r in records],
                         ['shadow_startup_control_read_deferred',
                          'shadow_startup_control_read_restored'])
        self.assertTrue(records[0]['new_entries_blocked'])
        self.assertEqual(records[1]['retries'],2)
        self.assertTrue(all(r['real_orders_enabled'] is False for r in records))
        self.assertNotIn('bot-a',json.dumps(records))

    def test_capacity_or_unknown_error_remains_fatal(self):
        for error in (BotCatalogCapacityError('full catalog unavailable'),
                      RuntimeError('DB fence unavailable')):
            with self.subTest(error=type(error).__name__):
                stop=Mock()
                with patch(MODULE+'.load_bots',side_effect=error):
                    with self.assertRaises(type(error)):
                        load_startup_controls(MagicMock(),stop)
                stop.wait.assert_not_called()

    def test_stop_during_timeout_exits_without_partial_simulator(self):
        stop=Mock()
        stop.wait.return_value=True
        with patch(MODULE+'.load_bots',
                   side_effect=QueryCanceled('statement timeout')),patch(
                   'builtins.print'):
            with self.assertRaises(ShadowStartupStopped):
                load_startup_controls(MagicMock(),stop)
        stop.wait.assert_called_once_with(2)

    def test_router_cleanly_returns_if_startup_retry_stopped(self):
        stop=Event()
        with patch(MODULE+'.credentials',return_value=object()),patch(
             MODULE+'.HostedRun',side_effect=ShadowStartupStopped),patch(
             MODULE+'.asyncio.run') as event_loop:
            run(stop,MagicMock(),lambda:None,{})
            event_loop.assert_not_called()


if __name__=='__main__':
    unittest.main()
