"""Unit tests for opt-in archival cycle resource and safety budgets.

Uses fakes: no database, R2 or destructive cleanup calls.
"""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from services.demo import shadow_archive_automatic as automatic


class _Connection:
    def __init__(self, readings):
        self.readings = readings

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, args=None):
        if "pg_current_wal_lsn()::text AS lsn" in query:
            return SimpleNamespace(fetchone=lambda: {"lsn": "0/1000000"})
        if "pg_wal_lsn_diff" in query:
            return SimpleNamespace(fetchone=lambda: next(self.readings))
        raise AssertionError("Unexpected query")


class _Pool:
    def __init__(self, readings):
        self.readings = iter(readings)

    def connection(self):
        return _Connection(self.readings)


def _limits():
    return automatic.Limits(
        database_url="postgresql://fake",
        capacity_gb=15,
        interval_seconds=60,
        raw_batch_size=100,
        raw_batches=2,
        packed_batch_size=2,
        packed_batches=1,
    )


class ArchiveCycleBudgetTests(unittest.TestCase):
    def _run(self, readings, **kwargs):
        pool = _Pool(readings)
        limits = _limits()
        with patch.object(automatic, "database_bytes", return_value=9_000_000_000), \
             patch.object(automatic, "archive_and_reclaim_one") as raw, \
             patch.object(automatic, "archive_one") as packed:
            result = automatic.archive_cycle(pool, object(), limits, **kwargs)
            return result, raw.call_count, packed.call_count

    def test_valid_index_required_before_archival(self):
        class IndexPool:
            def __init__(self, row):
                self.row = row

            def connection(self):
                parent = self

                class Connection:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return False

                    def execute(self, statement):
                        return SimpleNamespace(fetchone=lambda: parent.row)

                return Connection()

        for row in (None, {"indisvalid": False, "indisready": True},
                    {"indisvalid": True, "indisready": False}):
            with self.subTest(row=row):
                with self.assertRaises(RuntimeError):
                    automatic.verify_archive_index(IndexPool(row))
        automatic.verify_archive_index(IndexPool(
            {"indisvalid": True, "indisready": True}))

    def test_wal_guard_stops_before_any_archive(self):
        report, raw, packed = self._run([
            {"wal_bytes": 128 * 1024 ** 2, "db_bytes": 9_000_000_000},
        ])
        self.assertEqual(report["stop_reason"], "wal_budget_reached")
        self.assertEqual((raw, packed), (0, 0))

    def test_database_growth_guard_stops_before_any_archive(self):
        report, raw, packed = self._run([
            {"wal_bytes": 0, "db_bytes": 9_000_000_000 + 256 * 1024 ** 2 + 1},
        ])
        self.assertEqual(report["stop_reason"], "database_growth_guard_reached")
        self.assertEqual((raw, packed), (0, 0))

    def test_shutdown_stops_before_any_archive(self):
        report, raw, packed = self._run([], stopped=lambda: True)
        self.assertEqual(report["stop_reason"], "shutdown_requested")
        self.assertEqual((raw, packed), (0, 0))

    def test_safety_check_rejects_before_any_archive(self):
        with self.assertRaisesRegex(RuntimeError, "Hold revoked"):
            self._run([], safety_check=lambda: (_ for _ in ()).throw(
                RuntimeError("Hold revoked")))

    def test_time_guard_stops_before_any_archive(self):
        with patch.object(automatic.time, "monotonic", side_effect=[0, 601]):
            report, raw, packed = self._run([])
        self.assertEqual(report["stop_reason"], "time_budget_reached")
        self.assertEqual((raw, packed), (0, 0))


if __name__ == "__main__":
    unittest.main()
