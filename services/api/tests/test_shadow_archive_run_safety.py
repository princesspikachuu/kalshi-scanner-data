"""Recovery run safety across cycles, failures and worker restarts. No hosted I/O."""
import io
import unittest
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
from services.demo import shadow_archive_automatic as automatic
from services.api.tests import test_shadow_archive_automatic as fixtures
from services.api.tests import test_shadow_archive_automatic_limits as limit_fixtures


class ConditionalObjects:
    def __init__(self):
        self.client = self
        self.bucket = 'test-only'
        self.data = {}
        self.writes = []
        self.read_error = False
        self.corrupt_read = False
        self.closed = 0
        self.last_stream = None

    def put_object(self, **args):
        self.writes.append(args)
        if args['IfNoneMatch'] != '*':
            raise AssertionError('Unconditional run claim')
        if args['Key'] in self.data:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'},
                               'ResponseMetadata': {'HTTPStatusCode': 412}}, 'PutObject')
        self.data[args['Key']] = args['Body']

    def get_object(self, **args):
        if self.read_error:
            raise RuntimeError('simulated read failure')
        body = self.data[args['Key']]
        self.last_stream = io.BytesIO(b'changed' if self.corrupt_read else body)
        return dict(ContentLength=len(body), Body=self.last_stream)

    def close(self):
        self.closed += 1


class ArchiveRunSafetyTests(unittest.TestCase):
    def test_run_id_is_explicit_and_bounded(self):
        env = fixtures.RecoveryArchiveAutomaticTests().env()
        for token in ('', None, 'a'*31, 'a'*33, 'A'*32, '../'+'a'*29):
            with self.subTest(token=token), self.assertRaises(ValueError):
                automatic.configuration(dict(env, MT_ARCHIVE_RUN_ID=token))
        self.assertEqual(automatic.configuration(env).run_id, 'a'*32)
        self.assertEqual(automatic.configuration(dict(env, MT_ARCHIVE_RAW_BATCHES='250',
                         MT_ARCHIVE_PACKED_BATCHES='0')).raw_batches, 250)
        with self.assertRaises(ValueError):
            automatic.configuration(dict(env, MT_ARCHIVE_RAW_BATCHES='251'))

    def test_claim_is_conditional_verified_and_cannot_be_reused(self):
        objects = ConditionalObjects()
        automatic.claim_run(objects, 'a'*32)
        self.assertTrue(objects.last_stream.closed)
        original = dict(objects.data)
        with self.assertRaises(ClientError):
            automatic.claim_run(objects, 'a'*32)
        self.assertEqual(objects.data, original)
        self.assertEqual(len(objects.data), 1)
        self.assertEqual(objects.writes[0]['ContentType'], 'application/json')
        self.assertNotIn(b'postgres', objects.writes[0]['Body'])

    def test_failed_readback_still_consumes_id(self):
        for failure in ('read_error', 'corrupt_read'):
            with self.subTest(failure=failure):
                objects = ConditionalObjects()
                setattr(objects, failure, True)
                with self.assertRaises(RuntimeError):
                    automatic.claim_run(objects, 'b'*32)
                setattr(objects, failure, False)
                with self.assertRaises(ClientError):
                    automatic.claim_run(objects, 'b'*32)
                if objects.last_stream is not None:
                    self.assertTrue(objects.last_stream.closed)

    def run_twice(self, *, reports=None, failure=None):
        objects = ConditionalObjects()
        stop = MagicMock()
        stop.is_set.return_value = False
        budget = automatic.RunBudget(9_000_000_000, 0, '0/1000000')
        env = fixtures.RecoveryArchiveAutomaticTests().env()
        with patch.object(automatic, 'ConnectionPool'), \
             patch.object(automatic, 'verify_scoped_role'), \
             patch.object(automatic, 'verify_archive_index'), \
             patch.object(automatic, 'object_store', return_value=objects), \
             patch.object(automatic, 'start_run_budget', return_value=budget) as start, \
             patch.object(automatic, 'archive_cycle', side_effect=failure or reports) as cycle, \
             patch.object(automatic, 'park_until_stopped') as park, \
             patch('builtins.print') as printed:
            automatic.run(stop, env)
            calls_after_first_run = cycle.call_count
            automatic.run(stop, env)
        self.assertEqual(start.call_count, 1)
        self.assertEqual(cycle.call_count, calls_after_first_run)
        self.assertEqual(park.call_count, 2)
        self.assertEqual(objects.closed, 2)
        self.assertEqual(len(objects.data), 1)
        return cycle, budget, printed

    def test_cycles_share_one_budget_and_restart_cannot_rearm(self):
        cycle, budget, _ = self.run_twice(reports=[
            dict(stop_reason=None, raw_rows=100, packed_rows=0),
            dict(stop_reason='wal_budget_reached', raw_rows=0, packed_rows=0)])
        self.assertEqual(cycle.call_count, 2)
        for call in cycle.call_args_list:
            self.assertIs(call.kwargs['budget'], budget)

    def test_verification_failure_parks_and_does_not_leak_or_retry(self):
        cycle, _, printed = self.run_twice(failure=RuntimeError('postgresql://private'))
        self.assertEqual(cycle.call_count, 1)
        self.assertNotIn('postgresql://private', str(printed.call_args_list))

    def test_exhausted_backlog_parks_and_restart_cannot_rearm(self):
        cycle, _, _ = self.run_twice(reports=[dict(
            stop_reason=None, raw_rows=0, packed_rows=0)])
        self.assertEqual(cycle.call_count, 1)

    def test_park_responds_to_shutdown(self):
        stop = MagicMock()
        stop.is_set.side_effect = [False, True]
        automatic.park_until_stopped(stop)
        stop.wait.assert_called_once_with(30)

    def test_wal_and_growth_budgets_do_not_reset_at_cycle_boundary(self):
        helper = limit_fixtures.ArchiveCycleBudgetTests()
        budget = automatic.RunBudget(9_000_000_000, 0, '0/1000000')
        for reading, expected in (
                (dict(wal_bytes=128*1024**2, db_bytes=9_000_000_000), 'wal_budget_reached'),
                (dict(wal_bytes=0, db_bytes=9_000_000_000+256*1024**2+1), 'database_growth_guard_reached')):
            with self.subTest(expected=expected), patch.object(automatic.time, 'monotonic', return_value=60):
                report, raw, packed = helper._run([reading], budget=budget)
            self.assertEqual(report['stop_reason'], expected)
            self.assertEqual((raw, packed), (0, 0))
            self.assertEqual(report['elapsed_seconds'], 60)

    def test_run_time_includes_wait_between_cycles(self):
        budget = automatic.RunBudget(9_000_000_000, 0, '0/1000000')
        with patch.object(automatic.time, 'monotonic', return_value=601):
            report, raw, packed = limit_fixtures.ArchiveCycleBudgetTests()._run([], budget=budget)
        self.assertEqual(report['stop_reason'], 'time_budget_reached')
        self.assertEqual((raw, packed), (0, 0))
