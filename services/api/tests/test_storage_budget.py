"""Storage signals are logical-only and cannot authorize operations."""
import unittest
from services.research.storage_budget import budget_snapshot, growth_snapshot, GB


class LogicalStorageBudgetTests(unittest.TestCase):
    def test_warning_and_critical_limits_are_explicit(self):
        self.assertEqual(budget_snapshot(6*GB,15)['threshold_level'],'below_warning')
        self.assertEqual(budget_snapshot(11*GB,15)['threshold_level'],'warning')
        self.assertEqual(budget_snapshot(13*GB,15)['threshold_level'],'critical')

    def test_never_reports_physical_disk_capacity_or_safe_deletion(self):
        for value in (0,9*GB,20*GB):
            row=budget_snapshot(value,15)
            self.assertFalse(row['physical_headroom_verified'])
            self.assertFalse(row['safe_to_reclaim'])
            self.assertFalse(row['safe_to_restart_writers'])
            self.assertIsNone(row['wal_headroom_bytes'])
            self.assertIsNone(row['filesystem_free_bytes'])
            self.assertEqual(row['metric'],'logical_pg_database_size_only')

    def test_invalid_config_refused(self):
        for capacity in (0,-1,'NaN','Infinity','hidden',None,True,1025):
            with self.subTest(capacity=capacity):
                with self.assertRaises(ValueError):
                    budget_snapshot(100,capacity)
        for value in (-1,True,10.5,'100'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    budget_snapshot(value,15)

    def test_growth_and_shrink_are_observations_not_delete_approvals(self):
        a=dict(at=1000,database_bytes=8*GB)
        b=dict(at=4600,database_bytes=9*GB)
        result=growth_snapshot(a,b,15)
        self.assertEqual(result['delta_bytes'],GB)
        self.assertTrue(result['rapid_growth_flag'])
        self.assertEqual(result['action'],'observe_only')
        self.assertFalse(result['physical_headroom_verified'])
        decreased=growth_snapshot(b,dict(at=8200,database_bytes=8*GB),15)
        self.assertFalse(decreased['rapid_growth_flag'])
        self.assertLess(decreased['delta_bytes'],0)

    def test_existing_read_only_audit_adds_budget_without_more_sql(self):
        from unittest.mock import MagicMock,patch
        from services.research.storage_audit import inspect_storage
        pool=MagicMock()
        c=pool.connection.return_value.__enter__.return_value
        c.execute.return_value.fetchone.return_value=dict(bytes=11*GB)
        c.execute.return_value.fetchall.return_value=[]
        with patch.dict('os.environ',{'DATABASE_CAPACITY_GB':'15'}):
            result=inspect_storage(pool)
        self.assertEqual(result['logical_storage_budget']['threshold_level'],'warning')
        self.assertFalse(result['logical_storage_budget']['physical_headroom_verified'])
        self.assertEqual(c.execute.call_count,5)
        self.assertEqual(pool.connection.call_count,2)

    def test_invalid_time_and_duplicate_timestamp_rejected(self):
        a=dict(at=100,database_bytes=100)
        for b in (dict(at=100,database_bytes=200),
                  dict(at='NaN',database_bytes=200),
                  dict(at=90,database_bytes=200),
                  dict(at=200,database_bytes=True)):
            with self.subTest(b=b):
                with self.assertRaises(ValueError):
                    growth_snapshot(a,b,15)


if __name__=='__main__':
    unittest.main()
