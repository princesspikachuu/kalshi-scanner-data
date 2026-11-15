"""A larger backlog run must reserve measured physical headroom. No hosted I/O."""
from dataclasses import replace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from services.demo import shadow_archive_automatic as a
from services.api.tests import test_shadow_archive_automatic as fixtures
from services.api.tests.test_shadow_archive_automatic_limits import _Pool, _limits


class BacklogBudgetTests(TestCase):
    def limits(self, **kwargs):
        return replace(_limits(), max_wal_bytes=2048*1024**2, max_seconds=7200,
                       physical_used_bytes=9_000_000_000, physical_measured_at=1000, **kwargs)

    def test_defaults_keep_original_limits_and_need_no_extra_proof(self):
        limits = a.configuration(fixtures.RecoveryArchiveAutomaticTests().env())
        self.assertEqual((limits.max_wal_bytes, limits.max_seconds), (128*1024**2, 600))
        a.verify_physical_budget(limits)

    def test_larger_run_reserves_all_wal_plus_growth_and_batch_overshoot(self):
        a.verify_physical_budget(self.limits(), now=1000)
        limit = self.limits()
        boundary = 12_000_000_000 - limit.max_wal_bytes - 320*1024**2
        a.verify_physical_budget(replace(limit, physical_used_bytes=boundary), now=1000)
        with self.assertRaises(ValueError):
            a.verify_physical_budget(replace(limit, physical_used_bytes=boundary+1), now=1000)

    def test_missing_stale_and_future_measurements_are_rejected(self):
        for used, measured, now in ((0,1000,1000), (9_000_000_000,0,1000),
                                    (9_000_000_000,1000,1901), (9_000_000_000,1001,1000)):
            with self.subTest(used=used, measured=measured, now=now), self.assertRaises(ValueError):
                a.verify_physical_budget(replace(self.limits(), physical_used_bytes=used,
                                                 physical_measured_at=measured), now=now)

    def test_invalid_configuration_cannot_raise_caps(self):
        env = fixtures.RecoveryArchiveAutomaticTests().env()
        for key, value in (('MT_ARCHIVE_MAX_WAL_MIB','2049'), ('MT_ARCHIVE_MAX_SECONDS','7201'),
                           ('MT_ARCHIVE_MAX_WAL_MIB','0'), ('MT_ARCHIVE_MAX_SECONDS','-1'),
                           ('MT_ARCHIVE_PHYSICAL_USED_BYTES','nan')):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                a.configuration(dict(env, **{key:value}))

    def test_larger_run_without_headroom_never_opens_database_or_claims(self):
        env = dict(fixtures.RecoveryArchiveAutomaticTests().env(), MT_ARCHIVE_MAX_WAL_MIB='2048')
        with patch.object(a,'ConnectionPool') as pool, patch.object(a,'object_store') as objects, \
             patch.object(a,'park_until_stopped') as park, patch('builtins.print'):
            a.run(MagicMock(),env)
        pool.assert_not_called()
        objects.assert_not_called()
        park.assert_called_once()

    def test_extended_budget_is_cumulative_and_does_not_reset(self):
        limit = self.limits()
        budget = a.RunBudget(9_000_000_000,0,'0/1000000')
        safe = dict(wal_bytes=128*1024**2, db_bytes=9_000_000_000)
        end = dict(safe,wal_bytes=limit.max_wal_bytes)
        with patch.object(a,'database_bytes',return_value=9_000_000_000), \
             patch.object(a.time,'monotonic',return_value=601), \
             patch.object(a,'archive_and_reclaim_one',return_value=dict(archived=0,deleted=0)) as raw, \
             patch.object(a,'archive_one',return_value=dict(archived_rows=0,deleted_rows=0)):
            first = a.archive_cycle(_Pool([safe,safe,safe]),None,limit,budget=budget)
            second = a.archive_cycle(_Pool([end,end]),None,limit,budget=budget)
        self.assertIsNone(first['stop_reason'])
        self.assertEqual(second['stop_reason'],'wal_budget_reached')
        self.assertEqual(raw.call_count,1)

    def test_extended_time_still_stops_before_deletion(self):
        limit = self.limits()
        final = dict(wal_bytes=0,db_bytes=9_000_000_000)
        with patch.object(a,'database_bytes',return_value=9_000_000_000), \
             patch.object(a.time,'monotonic',return_value=7200), \
             patch.object(a,'archive_and_reclaim_one') as raw:
            report=a.archive_cycle(_Pool([final]),None,limit,budget=a.RunBudget(9_000_000_000,0,'0/1000000'))
        self.assertEqual(report['stop_reason'],'time_budget_reached')
        raw.assert_not_called()
